"""情境召回（模組 5，RQ1）：給情境詞，替每間餐廳算 0–1 分數並挑出最支持的評論。

方法在 config.toml [retrieval] method 切換，方便 RQ1 比較：
    bigram  字元二元組重疊比例（原本的基準）
    bm25    BM25（以字元二元組為詞，中文不用斷詞）
    vector  Gemini embedding 餘弦相似度
    hybrid  w·bm25 + (1−w)·vector（DESIGN §9：正規化後加權融合）

固定規則（DESIGN §9 要求版本化，O005 未定案前先用這組）：
- 每間店的文件 = 每則評論各一份 + 店名一份；店分數取文件最高分（片段聚合 = max）。
- 正規化不看這次的候選集：BM25 除以該查詢的理論上限 Σ idf·(k1+1)；餘弦夾到 [0, 1]。
- 進候選的門檻：bm25 > 0，或 vector 餘弦 ≥ min_cos。只靠店名對上時，不拿評論充當依據。
- vector／hybrid 呼叫 Gemini 失敗或沒金鑰時退回 bm25，回傳 note 讓使用者知道。

    python retrieve.py selftest            # 不呼叫 Gemini
    python retrieve.py compare 慶生 古早味  # 用真實語料印出四種方法的排名（要 GEMINI_API_KEY）
"""
import hashlib
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from settings import setting  # noqa: E402

K1, B = 1.5, 0.75
CACHE = ROOT / "corpus" / "raw" / "embeddings.json"   # 由語料衍生，不進 git（D017）


def grams(s):
    s = "".join(ch for ch in s if not ch.isspace())
    return [s[i:i + 2] for i in range(len(s) - 1)] or ([s] if s else [])  # 不用單字：「學生」不該算符合「慶生」


def docs_of(r):
    return [(text, True) for text in r["reviews"]] + [(r["name"], False)]   # (文字, 是不是評論)


# ---------- 詞彙方法 ----------
def bigram_scores(context, restaurants):
    q = set(grams(context))
    return [[len(q & set(grams(t))) / len(q) if q else 0 for t, _ in docs_of(r)] for r in restaurants]


def bm25_scores(context, restaurants):
    docs = [Counter(grams(t)) for r in restaurants for t, _ in docs_of(r)]
    n, avg = len(docs), sum(sum(d.values()) for d in docs) / max(len(docs), 1)
    q = set(grams(context))
    idf = {t: math.log(1 + (n - (df := sum(t in d for d in docs)) + 0.5) / (df + 0.5)) for t in q}
    top = sum(idf.values()) * (K1 + 1) or 1   # 理論上限：固定尺度，不依候選集縮放

    def score(d):
        length = sum(d.values())
        return sum(idf[t] * d[t] * (K1 + 1) / (d[t] + K1 * (1 - B + B * length / avg)) for t in q if t in d) / top

    it = iter(docs)
    return [[score(next(it)) for _ in docs_of(r)] for r in restaurants]


# ---------- 向量方法 ----------
def embed(texts, task):
    """Gemini embedding；文件向量快取在 CACHE（以 模型+任務+文字 為鍵），查詢不快取。"""
    from google import genai
    from google.genai import types
    model = setting("retrieval", "embed_model")
    key = lambda t: hashlib.sha1(f"{model}|{task}|{t}".encode()).hexdigest()
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() and task == "RETRIEVAL_DOCUMENT" else {}
    todo = [t for t in dict.fromkeys(texts) if key(t) not in cache]
    if todo:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options=types.HttpOptions(timeout=30_000))
        config = types.EmbedContentConfig(task_type=task)
        for i in range(0, len(todo), 100):   # 一次最多 100 則
            batch = todo[i:i + 100]
            vecs = [e.values for e in client.models.embed_content(model=model, contents=batch, config=config).embeddings]
            if len(vecs) != len(batch):   # gemini-embedding-2 會把整批併成一個向量 → 改成一則一則送
                vecs = [client.models.embed_content(model=model, contents=t, config=config).embeddings[0].values for t in batch]
            cache.update({key(t): v for t, v in zip(batch, vecs)})
        if task == "RETRIEVAL_DOCUMENT":
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return [cache[key(t)] for t in texts]


def cos(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1)


def vector_scores(context, restaurants):
    texts = [t for r in restaurants for t, _ in docs_of(r)]
    q = embed([context], "RETRIEVAL_QUERY")[0]
    it = iter(embed(texts, "RETRIEVAL_DOCUMENT"))
    return [[max(0.0, cos(q, next(it))) for _ in docs_of(r)] for r in restaurants]


# ---------- 對外介面 ----------
def retrieve(context, restaurants, method=None):
    """回傳 ({餐廳 id: {"score", "quote"}}, notes)。只含通過門檻的店；quote 是最支持的評論（沒有就 None）。"""
    method = method or setting("retrieval", "method")
    if method not in ("bigram", "bm25", "vector", "hybrid"):
        raise ValueError(f"[retrieval] method 不認得：{method}")
    notes = []
    lexical = (bigram_scores if method == "bigram" else bm25_scores)(context, restaurants)
    vector = None
    if method in ("vector", "hybrid"):
        try:
            if not os.environ.get("GEMINI_API_KEY"):
                raise RuntimeError("沒有 GEMINI_API_KEY")
            vector = vector_scores(context, restaurants)
        except Exception as e:
            notes.append(f"語意檢索失敗（{type(e).__name__}），改用關鍵字比對")
            method = "bm25"
    w, min_cos = setting("retrieval", "hybrid_weight"), setting("retrieval", "min_cos")
    out = {}
    for i, r in enumerate(restaurants):
        docs = docs_of(r)
        lex = lexical[i]
        vec = vector[i] if vector else [0.0] * len(docs)
        if method == "vector":
            passed, score = [v >= min_cos for v in vec], vec
        elif method == "hybrid":
            passed = [l > 0 or v >= min_cos for l, v in zip(lex, vec)]
            score = [w * l + (1 - w) * v for l, v in zip(lex, vec)]
        else:
            passed, score = [l > 0 for l in lex], lex
        hits = [j for j in range(len(docs)) if passed[j]]
        if not hits:
            continue
        reviews = [j for j in hits if docs[j][1]]
        out[r["id"]] = {"score": round(max(score[j] for j in hits), 2),
                        "quote": docs[max(reviews, key=lambda j: score[j])][0] if reviews else None}
    return out, notes


def selftest():
    shops = [{"id": "A", "name": "示意餐廳", "reviews": ["包廂很適合慶生", "學生聚餐首選"]},
             {"id": "B", "name": "蘇媽媽湯圓", "reviews": ["皮很Q，湯頭清甜"]},
             {"id": "C", "name": "老店", "reviews": ["學生很多"]}]
    for m in ("bigram", "bm25"):
        hits, notes = retrieve("慶生", shops, m)
        assert list(hits) == ["A"] and hits["A"]["quote"] == "包廂很適合慶生" and not notes, (m, hits)   # 單字「生」不算
        hits, _ = retrieve("湯圓", shops, m)
        assert list(hits) == ["B"] and hits["B"]["quote"] is None    # 只靠店名，不拿評論充當依據
        assert retrieve("火星料理", shops, m)[0] == {}
    assert 0 < retrieve("慶生", shops, "bm25")[0]["A"]["score"] <= 1   # 固定尺度
    # 沒金鑰時 vector／hybrid 退回 bm25，並告知
    key = os.environ.pop("GEMINI_API_KEY", None)
    hits, notes = retrieve("慶生", shops, "hybrid")
    assert list(hits) == ["A"] and "改用關鍵字" in notes[0]
    if key:
        os.environ["GEMINI_API_KEY"] = key
    # 向量路徑：換掉 embed，用假的向量測融合與門檻
    global embed
    real, fake = embed, {"慶生": [1, 0], "包廂很適合慶生": [0.9, 0.1], "學生聚餐首選": [0.2, 1], "示意餐廳": [0, 1],
                         "蘇媽媽湯圓": [0, 1], "皮很Q，湯頭清甜": [0, 1], "老店": [0, 1], "學生很多": [0.5, 0.866]}
    embed = lambda texts, task: [fake[t] for t in texts]
    os.environ.setdefault("GEMINI_API_KEY", "selftest")
    hits, _ = retrieve("慶生", shops, "vector")
    assert list(hits) == ["A"], hits   # C 的餘弦 0.5 < min_cos 0.6
    embed = real
    if not key:
        os.environ.pop("GEMINI_API_KEY")
    print("retrieve selftest ok")


def compare(contexts):
    data = json.loads((ROOT / "corpus" / "restaurants.json").read_text(encoding="utf-8"))["restaurants"]
    name = {r["id"]: r["name"] for r in data}
    for c in contexts:
        print(f"\n== {c}")
        for m in ("bigram", "bm25", "vector", "hybrid"):
            hits, notes = retrieve(c, data, m)
            ranked = sorted(hits.items(), key=lambda kv: -kv[1]["score"])
            print(f"  {m:6} " + ("、".join(f"{name[i]} {h['score']}" for i, h in ranked) or "（無）") + (f"  ※{notes}" if notes else ""))


METHODS = ("bigram", "bm25", "vector", "hybrid")


def evaluate(labels, data, k, methods=METHODS):
    """RQ1：每種方法對標註集算 Recall@k、Precision@k、MRR（只算有相關店的查詢），
    以及沒有相關店的查詢平均誤召回幾家。方法退回 bm25（Gemini 失敗）時整個方法記為失敗，不把 bm25 的分數算給它。"""
    by_name = {r["name"]: r["id"] for r in data}
    unknown = sorted({n for q in labels for n in q["relevant"] if n not in by_name})
    if unknown:
        raise ValueError(f"標註的店名不在語料裡：{unknown}")
    out = {}
    for m in methods:
        rows, fps = [], []
        for q in labels:
            hits, notes = retrieve(q["context"], data, m)
            if notes:
                out[m] = {"error": notes[0]}
                break
            top = [i for i, _ in sorted(hits.items(), key=lambda kv: (-kv[1]["score"], kv[0]))][:k]
            rel = {by_name[n] for n in q["relevant"]}
            if not rel:
                fps.append(len(top))
                continue
            first = next((rank for rank, i in enumerate(top, 1) if i in rel), None)
            rows.append((len(rel & set(top)) / len(rel), len(rel & set(top)) / len(top) if top else 0.0, 1 / first if first else 0.0))
        else:
            mean = lambda xs: round(sum(xs) / len(xs), 2) if xs else None
            out[m] = {"recall": mean([r[0] for r in rows]), "precision": mean([r[1] for r in rows]),
                      "mrr": mean([r[2] for r in rows]), "false_hits": mean(fps), "queries": len(labels)}
    return out


def run_evaluate(path):
    data = json.loads((ROOT / "corpus" / "restaurants.json").read_text(encoding="utf-8"))["restaurants"]
    labels = json.loads(Path(path).read_text(encoding="utf-8"))["queries"]
    k = setting("defaults", "recall_k")
    print(f"語料 {len(data)} 家、標註 {len(labels)} 個查詢、k = {k}（config [defaults] recall_k）\n")
    print(f"{'method':8}{'Recall@k':>10}{'Prec@k':>9}{'MRR':>7}{'誤召回':>8}")
    for m, s in evaluate(labels, data, k).items():
        print(f"{m:8}" + (f"  失敗：{s['error']}" if "error" in s else
                          f"{s['recall']:>10}{s['precision']:>9}{s['mrr']:>7}{s['false_hits']:>8}"))
    print("\n誤召回＝沒有相關店的查詢（例如語料裡沒有慶生）平均還召回幾家，越少越好。")


def selftest_evaluate():
    shops = [{"id": "A", "name": "甲", "reviews": ["包廂很適合慶生"]},
             {"id": "B", "name": "乙", "reviews": ["湯頭清甜"]},
             {"id": "C", "name": "丙", "reviews": ["湯頭很鹹"]}]
    labels = [{"context": "湯頭", "relevant": ["乙"]}, {"context": "湯頭", "relevant": ["丙"]},
              {"context": "慶生", "relevant": ["甲"]}, {"context": "火鍋", "relevant": []}]
    s = evaluate(labels, shops, k=5, methods=("bm25",))["bm25"]
    # 湯頭：乙丙同分、依 id 排，乙第 1、丙第 2 → MRR (1 + 0.5 + 1) / 3；Precision (0.5 + 0.5 + 1) / 3
    assert s["recall"] == 1.0 and s["precision"] == 0.67 and s["mrr"] == 0.83 and s["false_hits"] == 0, s
    try:
        evaluate([{"context": "x", "relevant": ["不存在"]}], shops, 5)
        raise AssertionError("未知店名要報錯")
    except ValueError:
        pass
    key = os.environ.pop("GEMINI_API_KEY", None)
    assert "error" in evaluate(labels, shops, 5, ("vector",))["vector"]   # 退回 bm25 → 記為失敗，不冒充
    if key:
        os.environ["GEMINI_API_KEY"] = key
    print("evaluate selftest ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        selftest()
        selftest_evaluate()
    elif sys.argv[1:2] == ["compare"]:
        compare(sys.argv[2:])
    elif sys.argv[1:2] == ["evaluate"]:
        run_evaluate(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).parent / "rq1_labels.json")
