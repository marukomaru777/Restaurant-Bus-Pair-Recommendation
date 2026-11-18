"""最小原型：情境召回 → TDX 公車方案 → 時間線 → T／F／U 查核 → 排序。

用法（在 prototype/ 底下執行；TDX 金鑰設定同 tdx/tdx.py）：
    python proto.py --context 慶生 --budget 600 --depart 2026-11-20T19:00 --origin 24.1372,120.6869
    python proto.py ... --offline        # 不呼叫 TDX，用 tdx/samples 的回應樣本跑流程
    python proto.py selftest             # 依 OpenSpec 情境檢查判定規則

ponytail: 跳過 LLM 解析（需求直接用參數給）、向量檢索（先用字元二元組重疊）、圖譜；
這三塊接上後，查核與排序邏輯不用改。
"""
import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent
TDX_DIR = HERE.parent / "tdx"
sys.path.insert(0, str(TDX_DIR))

T, F, U = "T", "F", "U"


# ---------- 1. 情境召回 ----------
def bigrams(s):
    s = "".join(ch for ch in s if not ch.isspace())
    return {s[i:i + 2] for i in range(len(s) - 1)}  # 不用單字：「學生」不該算符合「慶生」


def relevance(context, restaurant):
    """情境詞和評論的字元重疊比例。ponytail: 換成 BM25／向量後介面不變。"""
    q = bigrams(context) or {context}
    best = max((len(q & bigrams(r)) / len(q) for r in restaurant["reviews"]), default=0)
    return round(best, 2)


def best_review(context, restaurant):
    q = bigrams(context)
    return max(restaurant["reviews"], key=lambda r: len(q & bigrams(r)))


# ---------- 2. 公車方案 ----------
def plans_online(origin, r, depart, walk_min):
    import tdx  # 延後載入：selftest／offline 不需要金鑰
    status, text = tdx.call("/maas/routing", origin=origin, destination=f"{r['lat']},{r['lng']}",
                            gc="1.0", top="3", transit="5", depart=depart.strftime("%Y-%m-%dT%H:%M:%S"),
                            first_mile_mode="0", first_mile_time=str(walk_min),
                            last_mile_mode="0", last_mile_time=str(walk_min))
    time.sleep(13)  # 免費方案每分鐘 5 次
    if status != 200:
        return status  # 工具失敗 → 交通條件 U（429 通常是同一把金鑰同時有人在跑）
    return json.loads(text).get("data", {}).get("routes", [])


def plans_offline(origin, r, depart, walk_min):
    """用實測樣本，依出發時間平移，只為了讓流程能離線跑。"""
    routes = json.loads((TDX_DIR / "samples" / "trip_walk_gc0.json").read_text(encoding="utf-8"))["data"]["routes"]
    out = []
    for route in routes:
        shift = depart - datetime.fromisoformat(route["start_time"])
        mv = lambda t: (datetime.fromisoformat(t) + shift).isoformat()
        rr = json.loads(json.dumps(route))
        rr["start_time"], rr["end_time"] = mv(rr["start_time"]), mv(rr["end_time"])
        for s in rr["sections"]:
            for end in ("departure", "arrival"):
                s[end]["time"] = mv(s[end]["time"])
        out.append(rr)
    return out


# ---------- 3. 查核 ----------
def check_budget(price, budget):
    if not price:
        return U, "查不到價格"
    lo, hi = price
    if hi <= budget:
        return T, f"{lo}–{hi} 元，在 {budget} 元內"
    if lo > budget:
        return F, f"最低 {lo} 元已超過 {budget} 元"
    return U, f"{lo}–{hi} 元跨過預算 {budget} 元"


def check_hours(hours, arrive, meal_min):
    if not hours:
        return U, "缺營業時間"
    day = arrive.date()
    open_t, close_t = (datetime.combine(day, datetime.strptime(h, "%H:%M").time()) for h in hours)
    # ponytail: 不處理跨午夜營業與公休日，O012 定案後補
    leave = arrive + timedelta(minutes=meal_min)
    if arrive < open_t:
        return F, f"{arrive:%H:%M} 到時還沒開（{hours[0]} 開）"
    if leave > close_t:
        return F, f"{arrive:%H:%M} 到、{leave:%H:%M} 吃完，但 {hours[1]} 打烊"
    return T, f"{arrive:%H:%M} 到、{leave:%H:%M} 吃完，{hours[1]} 打烊前"


def check_route(route, walk_min, depart):
    # 實測：depart=19:00 時 TDX 仍可能回傳 18:53 出發的方案，不能只信任參數
    start = datetime.fromisoformat(route["start_time"])
    if start < depart:
        return F, f"方案要 {start:%H:%M} 出發，早於你的 {depart:%H:%M}"
    for s in route["sections"]:
        if s["type"] == "drive":
            return F, "路段含計程車／開車（D018）"
        if s["type"] == "pedestrian" and s["travelSummary"]["duration"] > walk_min * 60:
            return F, f"單段步行 {s['travelSummary']['duration'] // 60} 分超過 {walk_min} 分"
    return T, "全程公車＋步行"


def combine(states):
    if F in states:
        return F
    return T if all(s == T for s in states) else U


# ---------- 4. 主流程 ----------
def recommend(args, restaurants, get_plans):
    depart = datetime.fromisoformat(args.depart)
    # 情境完全不相符的店不進候選，交通再好也不推薦（D002：先情境、後交通）
    cands = sorted((r for r in restaurants if relevance(args.context, r) > 0),
                   key=lambda r: -relevance(args.context, r))[:args.k]
    results = []
    for r in cands:
        rel = relevance(args.context, r)
        budget = check_budget(r["price"], args.budget)
        routes = get_plans(args.origin, r, depart, args.walk)
        if isinstance(routes, int):
            hint = "，超過每分鐘 5 次，稍後重跑" if routes == 429 else ""
            results.append(dict(r=r, rel=rel, state=combine([budget[0], U]), checks={"預算": budget, "交通": (U, f"TDX 查詢失敗 HTTP {routes}{hint}")}))
            continue
        if not routes:
            results.append(dict(r=r, rel=rel, state=F, checks={"預算": budget, "交通": (F, "找不到公車方案")}))
            continue
        options = []
        for route in routes:
            arrive = datetime.fromisoformat(route["end_time"])
            checks = {"預算": budget, "交通": check_route(route, args.walk, depart), "營業": check_hours(r["hours"], arrive, args.meal)}
            options.append((combine([c[0] for c in checks.values()]), route["travel_time"], checks, route))
        # 每店只保留最佳方案：先比狀態（T > U > F），再比旅行時間（D008）
        state, tt, checks, route = min(options, key=lambda o: ({T: 0, U: 1, F: 2}[o[0]], o[1]))
        results.append(dict(r=r, rel=rel, state=state, checks=checks, route=route))
    ok = sorted([x for x in results if x["state"] == T], key=lambda x: (-x["rel"], x["route"]["travel_time"]))[:3]
    maybe = [x for x in results if x["state"] == U]
    no = [x for x in results if x["state"] == F]
    return ok, maybe, no


def describe_route(route):
    parts = []
    for s in route["sections"]:
        if s["type"] == "transit":
            parts.append(f"{s['departure']['time'][11:16]} 搭 {s['transport']['name']} 到 {s['arrival']['place'].get('name', '')}")
        elif s["type"] == "pedestrian":
            parts.append(f"走 {round(s['travelSummary']['duration'] / 60)} 分")
    return "，".join(parts) + f"（{route['end_time'][11:16]} 到店，{route['transfers']} 次轉乘）"


def show(ok, maybe, no, context):
    print("\n== 推薦（全部條件通過）==")
    for i, x in enumerate(ok, 1):
        print(f"{i}. {x['r']['name']}  情境分數 {x['rel']}")
        print(f"   評論依據：「{best_review(context, x['r'])}」")
        print(f"   交通：{describe_route(x['route'])}")
        for k, (st, why) in x["checks"].items():
            print(f"   {k} {st}：{why}")
    if not ok:
        print("（沒有全部通過的餐廳）")
    for title, group in (("== 不確定（請自行確認）==", maybe), ("== 不通過 ==", no)):
        print("\n" + title)
        if not group:
            print("（無）")
        for x in group:
            bad = "；".join(f"{k} {st}：{why}" for k, (st, why) in x["checks"].items() if st != T)
            print(f"- {x['r']['name']}：{bad}")


def selftest():
    # 對應 openspec/.../constraint-checking/spec.md 的情境
    assert check_budget([400, 800], 600)[0] == U          # 區間跨預算
    assert check_budget([700, 900], 600)[0] == F          # 下界超過預算
    assert check_budget([200, 500], 600)[0] == T
    assert check_budget(None, 600)[0] == U
    arrive = datetime(2026, 11, 20, 18, 50)
    assert check_hours(["11:00", "19:00"], arrive, 90)[0] == F   # 用餐超過打烊
    assert check_hours(["11:00", "22:00"], arrive, 90)[0] == T
    assert check_hours(None, arrive, 90)[0] == U
    walk = lambda d: {"type": "pedestrian", "travelSummary": {"duration": d}}
    dep = datetime(2026, 11, 20, 19, 0)
    route = lambda *secs, start="2026-11-20T19:02:00": {"start_time": start, "sections": list(secs)}
    assert check_route(route(walk(720)), 10, dep)[0] == F    # 單段步行上限
    assert check_route(route(walk(300), {"type": "drive"}), 10, dep)[0] == F
    assert check_route(route(walk(300), {"type": "transit"}, walk(400)), 10, dep)[0] == T
    assert check_route(route(walk(300), start="2026-11-20T18:53:18"), 10, dep)[0] == F  # 早於出發時間
    assert combine([T, U, T]) == U and combine([T, U, F]) == F and combine([T, T]) == T  # 有 U 無 F
    assert relevance("慶生", {"reviews": ["包廂很適合慶生"]}) == 1.0
    assert relevance("慶生", {"reviews": ["學生聚餐首選"]}) == 0     # 單字「生」不算
    print("selftest ok")


def main():
    if sys.argv[1:] == ["selftest"]:
        return selftest()
    p = argparse.ArgumentParser()
    p.add_argument("--context", required=True, help="用餐情境，例如 慶生、約會")
    p.add_argument("--budget", type=int, required=True, help="每人預算（元）")
    p.add_argument("--depart", required=True, help="出發時間，例如 2026-11-20T19:00（須晚於現在）")
    p.add_argument("--origin", required=True, help="出發地 緯度,經度")
    p.add_argument("--meal", type=int, default=90, help="用餐分鐘（預設 90，為假設值）")
    p.add_argument("--walk", type=int, default=10, help="單段步行上限分鐘")
    p.add_argument("--k", type=int, default=5, help="情境召回幾家")
    p.add_argument("--offline", action="store_true")
    args = p.parse_args()
    data = json.loads((HERE / "restaurants.json").read_text(encoding="utf-8"))["restaurants"]
    ok, maybe, no = recommend(args, data, plans_offline if args.offline else plans_online)
    show(ok, maybe, no, args.context)
    if args.offline:
        print("\n※ --offline：所有店都套用同一份實測路線樣本，交通結果不代表真實路線。")


if __name__ == "__main__":
    main()
