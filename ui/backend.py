"""UI 與後端之間唯一的接點。

兩種資料來源：
  - mock：讀 mock_result.json（/recommend 回應格式，含實測與推導樣本）
  - api ：呼叫 api/server.py（POST /recommend）

不論哪一種，都先經 normalize() 轉成 UI 用的結構，app.py 只看轉換後的結果。
API 格式見 api/API.md；轉換規則與 relevance 分級見 ui/README.md。
"""
import json
import math
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

MOCK = Path(__file__).parent / "mock_result.json"
DEFAULT_API = "http://127.0.0.1:8000"

CHECK_LABELS = {"budget": "預算", "transit": "交通", "hours": "營業"}
GROUP_TITLES = {"recommended": "推薦", "uncertain": "不確定（請自行確認）", "rejected": "不通過"}

# relevance 分級（暫定，待與組員討論）。relevance 是 BM25 除以理論上限、夾在 0–1，
# 數值天生偏低（示意資料查「慶生」只有 0.32–0.37），所以不直接顯示數字或星等。
RELEVANCE_HIGH = 0.6
RELEVANCE_MID = 0.3


class ApiError(Exception):
    """後端回錯誤。status 為 HTTP 狀態碼；連不上時為 None。message 可直接給使用者看。"""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------- 取得原始回應 ----------------
def _load():
    return json.loads(MOCK.read_text(encoding="utf-8"))


def scenario_names():
    return list(_load()["scenarios"])


def default_query():
    return _load()["default_query"]


def _fetch_mock(scenario):
    raw = _load()["scenarios"][scenario]
    err = raw.get("_http_error")
    if err:
        raise ApiError(err["status"], err["error"])
    return raw


def _fetch_api(query, base_url, offline):
    body = {
        "context": query["context"],
        "budget": query["budget_per_person"],
        "depart": query["depart"],
        "origin": [query["origin"]["lat"], query["origin"]["lng"]],
        "offline": bool(offline),
        "walk_min": query["walk_max_min"],
        "recall_k": query["k"],
    }
    if query.get("meal_min"):  # 不帶才會由後端標示「用餐時長為假設」
        body["meal_min"] = query["meal_min"]
    req = urllib.request.Request(base_url.rstrip("/") + "/recommend", json.dumps(body).encode("utf-8"),
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:  # 真的查 TDX 時每家店約 13 秒
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("error") or f"後端回應 HTTP {e.code}"
        except Exception:
            msg = f"後端回應 HTTP {e.code}"
        raise ApiError(e.code, msg)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise ApiError(None, f"連不上後端（{base_url}），請確認 api/server.py 已啟動：{e}")


# ---------------- 轉換 ----------------
_TAG = re.compile(r"^【([^｜】]*)｜([^】]*)】\s*(.*)$", re.S)


def relevance_level(x):
    if x is None:
        return "—"
    return "高" if x >= RELEVANCE_HIGH else "中" if x >= RELEVANCE_MID else "低"


def _hhmm(iso):
    return iso[11:16] if iso else None


def _check_list(item):
    """checks 物件 → list，並標出「未查」：
    被判 F 的店，其餘 U 多半只是沒必要再查（例如「未查（其他條件已不符）」），不是真的不確定。"""
    out = []
    for key, c in item["checks"].items():
        skipped = c["state"] == "U" and (item["state"] == "F" or c["reason"].startswith("未查"))
        out.append({"key": key, "label": CHECK_LABELS.get(key, key), "state": c["state"],
                    "reason": c["reason"], "skipped": skipped})
    return out


def _route(route, item, meal_min):
    if not route:
        return None
    secs = []
    last = len(route["sections"]) - 1
    for i, s in enumerate(route["sections"]):
        secs.append({
            "type": s["type"], "minutes": s["minutes"], "start": _hhmm(s["depart"]), "end": _hhmm(s["arrive"]),
            # 出發地與餐廳在 API 裡是 null，由 UI 補名稱
            "from": s.get("from") or ("出發地" if i == 0 else None),
            "to": s.get("to") or (item["name"] if i == last else None),
            "bus": s.get("bus"), "headsign": s.get("headsign"),
            "from_location": s["from_location"], "to_location": s["to_location"],
        })
    arrive = datetime.fromisoformat(route["arrive"])
    return {
        "start": _hhmm(route["depart"]), "arrive": _hhmm(route["arrive"]),
        # API 沒有離店時間：到店 + 用餐時長
        "leave": (arrive + timedelta(minutes=meal_min)).strftime("%H:%M") if meal_min else None,
        "travel_min": route["travel_min"],  # 不要用 sections 加總：各段分別四捨五入，加起來可能差 1 分
        "transfers": route["transfers"], "fare": route.get("fare"), "summary": route["summary"], "sections": secs,
    }


def _item(x, meal_min):
    m = _TAG.match(x["evidence"]) if x.get("evidence") else None
    checks = _check_list(x)
    return {
        "id": x["id"], "name": x["name"], "address": x.get("address"), "lat": x["lat"], "lng": x["lng"],
        "state": x["state"], "relevance": x["relevance"], "level": relevance_level(x["relevance"]),
        # 固定模板只是把下面的欄位串成一句，沒有新資訊；只有通過事實查核的 LLM 說明才顯示
        "explanation": x["explanation"] if x.get("explanation_source") == "llm" else None,
        "evidence": m.group(3) if m else x.get("evidence"),
        "evidence_aspect": m.group(1) if m else None,
        "evidence_tag": m.group(2) if m else None,
        "counter_evidence": x.get("counter_evidence", []),
        "price": x.get("price"), "hours": x.get("hours"), "closed_weekdays": x.get("closed_weekdays", []),
        "checks": checks,
        "unknowns": [c["reason"] for c in checks if c["state"] == "U" and not c["skipped"]],
        "route": _route(x.get("route"), x, meal_min),
        "sources": x.get("sources", []),
    }


def normalize(raw, extra_notes=()):
    meal = raw["request"].get("meal_min")
    groups = {g: [_item(x, meal) for x in raw[g]] for g in GROUP_TITLES}
    notes = list(extra_notes) + list(raw.get("notes", []))
    empty = not any(groups.values())
    return {
        "request": raw["request"], "groups": groups, "notes": notes,
        # 有候選但被淘汰的店會出現在 rejected，所以三組全空 = 沒有情境相符的店；原因在最後一則 notes
        "status": "no_candidates" if empty else "ok",
        "empty_reason": raw["notes"][-1] if empty and raw.get("notes") else None,
        "derived": raw.get("_derived"),
    }


# ---------------- 對外介面 ----------------
def get_recommendations(query, source="mock", scenario="all_kinds", base_url=DEFAULT_API, offline=True):
    """query 欄位：context、depart、origin{lat,lng}、budget{amount,unit,party_size?}、
    walk_max_min、meal_min?、k。失敗時丟 ApiError。"""
    q = dict(query)
    extra = []
    b = q["budget"]
    # API 只收每人預算（整數）；整團時換算並提醒使用者（無條件捨去，不超過原預算）
    if b["unit"] == "group":
        q["budget_per_person"] = max(1, math.floor(b["amount"] / b["party_size"]))
        extra.append(f"預算 {b['amount']} 元是 {b['party_size']} 人總共，換算每人 {q['budget_per_person']} 元")
    else:
        q["budget_per_person"] = int(b["amount"])
    raw = _fetch_mock(scenario) if source == "mock" else _fetch_api(q, base_url, offline)
    return normalize(raw, extra)
