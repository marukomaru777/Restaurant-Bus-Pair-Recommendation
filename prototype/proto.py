"""最小原型：情境召回 → TDX 公車方案 → 時間線 → T／F／U 查核 → 排序。

用法（在 prototype/ 底下執行；金鑰放 repo 根目錄 .env，預設值在 config.toml）：
    python proto.py --context 慶生 --budget 600 --depart 2026-11-20T19:00 --origin 24.1372,120.6869
    python proto.py ... --offline        # 不呼叫 TDX，用 tdx/samples 的回應樣本跑流程
    python proto.py selftest             # 依 OpenSpec 情境檢查判定規則

ponytail: 這裡跳過 LLM 解析（需求直接用參數給；API 的 /parse 有）與圖譜；接上後查核與排序邏輯不用改。
"""
import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent
TDX_DIR = HERE.parent / "tdx"
sys.path[:0] = [str(HERE.parent), str(TDX_DIR)]
from settings import setting  # noqa: E402
from retrieve import retrieve  # noqa: E402

T, F, U = "T", "F", "U"


# ---------- 1. 情境召回：retrieve.py（bigram／bm25／vector／hybrid，config.toml [retrieval]）----------


# ---------- 2. 公車方案 ----------
def plans_online(origin, r, depart, walk_min):
    import tdx  # 延後載入：selftest／offline 不需要金鑰
    status, text = tdx.call("/maas/routing", origin=origin, destination=f"{r['lat']},{r['lng']}",
                            gc="1.0", top="3", transit="5", depart=depart.strftime("%Y-%m-%dT%H:%M:%S"),
                            first_mile_mode="0", first_mile_time=str(walk_min),
                            last_mile_mode="0", last_mile_time=str(walk_min))
    time.sleep(tdx.INTERVAL)  # 免費方案每分鐘 5 次
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


WEEK = "一二三四五六日"


def check_hours(hours, arrive, meal_min, closed=()):
    """hours：當天營業時段 [["11:30","14:00"],["17:30","21:00"]]；closed：公休星期（0=週一）。
    打烊早於開店視為跨午夜（17:00–00:00）。ponytail: 凌晨到店算前一天時段的情況不處理。"""
    if not hours:
        return U, "缺營業時間"
    if arrive.weekday() in closed:
        return F, f"週{WEEK[arrive.weekday()]}公休"
    leave = arrive + timedelta(minutes=meal_min)
    # 說明欄常寫 24:00，strptime 不收，當成 00:00（下面會視為跨午夜）
    at = lambda h: datetime.combine(arrive.date(), datetime.strptime(h.replace("24:00", "00:00"), "%H:%M").time())
    for o, c in hours:
        open_t, close_t = at(o), at(c)
        if close_t <= open_t:
            close_t += timedelta(days=1)
        if open_t <= arrive and leave <= close_t:
            return T, f"{arrive:%H:%M} 到、{leave:%H:%M} 吃完，{c} 打烊前"
    spans = "、".join(f"{o}–{c}" for o, c in hours)
    return F, f"{arrive:%H:%M} 到、{leave:%H:%M} 吃完，不在營業時段 {spans} 內"


def precheck_hours(hours, depart, meal_min, closed=()):
    """查公車前的粗篩（模組 6）：還不知道幾點到，但到店一定在 depart 之後、max_travel_min 之內。
    這段時間內不管幾點到都吃不完才判 F；可能來得及就回 U，交給查完公車後的 check_hours。
    ponytail: 公休日看出發當天，深夜出發、隔天才到的情況不處理。"""
    if not hours:
        return U, "缺營業時間"
    if depart.weekday() in closed:
        return F, f"週{WEEK[depart.weekday()]}公休"
    latest = depart + timedelta(minutes=setting("defaults", "max_travel_min"))
    at = lambda h: datetime.combine(depart.date(), datetime.strptime(h.replace("24:00", "00:00"), "%H:%M").time())
    not_open_yet = True
    for o, c in hours:
        open_t, close_t = at(o), at(c)
        if close_t <= open_t:
            close_t += timedelta(days=1)
        earliest = max(depart, open_t)
        if earliest <= latest and earliest + timedelta(minutes=meal_min) <= close_t:
            return U, "營業時段內來得及，待查公車"
        not_open_yet &= open_t > latest
    spans = "、".join(f"{o}–{c}" for o, c in hours)
    if not_open_yet:
        return F, f"{depart:%H:%M} 出發，{setting('defaults', 'max_travel_min') // 60} 小時內到店都還沒開（{spans}）"
    return F, f"{depart:%H:%M} 出發，來不及在打烊前用餐 {meal_min} 分鐘（{spans}）"


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
    """回傳 (推薦, 不確定, 不通過, notes)；每筆有 r（餐廳）、rel（情境分數）、quote（支持評論）、state、checks。"""
    depart = datetime.fromisoformat(args.depart)
    # 情境完全不相符的店不進候選，交通再好也不推薦（D002：先情境、後交通）
    hits, notes = retrieve(args.context, restaurants)
    relevant = sorted((r for r in restaurants if r["id"] in hits), key=lambda r: (-hits[r["id"]]["score"], r["id"]))
    tag = lambda r: dict(r=r, rel=hits[r["id"]]["score"], quote=hits[r["id"]]["quote"])
    results, cands = [], []
    # 模組 6 粗篩：預算、營業已確定不符的不查 TDX（每家省 13 秒），也不佔召回名額 K
    for r in relevant:
        budget = check_budget(r["price"], args.budget)
        hours = precheck_hours(r["hours"], depart, args.meal, r.get("closed_weekdays", ()))
        if F in (budget[0], hours[0]):
            results.append(dict(**tag(r), state=F,
                                checks={"預算": budget, "交通": (U, "未查（其他條件已不符）"), "營業": hours}))
        elif len(cands) < args.k:
            cands.append(r)
    for r in cands:
        budget = check_budget(r["price"], args.budget)
        routes = get_plans(args.origin, r, depart, args.walk)
        if isinstance(routes, int):
            hint = "，超過每分鐘 5 次，稍後重跑" if routes == 429 else ""
            results.append(dict(**tag(r), state=combine([budget[0], U]), checks={"預算": budget, "交通": (U, f"TDX 查詢失敗 HTTP {routes}{hint}")}))
            continue
        if not routes:
            results.append(dict(**tag(r), state=F, checks={"預算": budget, "交通": (F, "找不到公車方案")}))
            continue
        options = []
        for route in routes:
            arrive = datetime.fromisoformat(route["end_time"])
            checks = {"預算": budget, "交通": check_route(route, args.walk, depart), "營業": check_hours(r["hours"], arrive, args.meal, r.get("closed_weekdays", ()))}
            options.append((combine([c[0] for c in checks.values()]), route["travel_time"], checks, route))
        # 每店只保留最佳方案：先比狀態（T > U > F），再比旅行時間（D008）
        state, tt, checks, route = min(options, key=lambda o: ({T: 0, U: 1, F: 2}[o[0]], o[1]))
        results.append(dict(**tag(r), state=state, checks=checks, route=route))
    ok = sorted([x for x in results if x["state"] == T], key=lambda x: (-x["rel"], x["route"]["travel_time"]))[:setting("defaults", "max_results")]
    maybe = [x for x in results if x["state"] == U]
    no = [x for x in results if x["state"] == F]
    return ok, maybe, no, notes


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
        quote = x["quote"]
        print(f"   評論依據：「{quote}」" if quote else f"   評論依據：無（店名符合「{context}」）")
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
    assert check_hours([["11:00", "19:00"]], arrive, 90)[0] == F   # 用餐超過打烊
    assert check_hours([["11:00", "22:00"]], arrive, 90)[0] == T
    assert check_hours(None, arrive, 90)[0] == U
    assert check_hours([["11:30", "14:00"], ["17:30", "21:00"]], arrive, 90)[0] == T  # 晚上時段
    assert check_hours([["11:30", "14:00"], ["17:30", "20:00"]], arrive, 90)[0] == F
    assert check_hours([["17:00", "00:00"]], arrive, 90)[0] == T                       # 跨午夜
    assert check_hours([["17:00", "24:00"]], arrive, 90)[0] == T
    assert check_hours([["11:00", "22:00"]], arrive, 90, closed=[4])[0] == F           # 2026-11-20 是週五
    # 粗篩：19:00 出發，只有確定來不及的才 F
    dep19 = datetime(2026, 11, 20, 19, 0)
    assert precheck_hours([["05:30", "11:30"]], dep19, 90)[0] == F                     # 早餐店已打烊
    assert precheck_hours([["11:00", "20:00"]], dep19, 90)[0] == F                     # 19:00 出發吃不完 90 分
    assert precheck_hours([["11:00", "21:00"]], dep19, 90)[0] == U                     # 可能來得及 → 查公車
    assert precheck_hours([["11:30", "14:00"], ["17:30", "21:00"]], dep19, 90)[0] == U
    assert precheck_hours([["17:00", "00:00"]], dep19, 90)[0] == U                     # 跨午夜
    assert precheck_hours([["11:00", "22:00"]], dep19, 90, closed=[4])[0] == F         # 公休
    assert precheck_hours(None, dep19, 90)[0] == U
    assert precheck_hours([["23:30", "02:00"]], dep19, 90)[0] == F                     # 晚於最長車程才開
    assert "還沒開" in precheck_hours([["11:30", "14:00"]], datetime(2026, 11, 20, 8, 0), 90)[1]
    assert "來不及" in precheck_hours([["11:00", "20:00"]], dep19, 90)[1]
    # 粗篩不呼叫 TDX：只有早餐店時 get_plans 一次都不會被叫到
    calls = []
    args = argparse.Namespace(context="湯包", budget=300, depart="2026-11-20T19:00", origin="24.13,120.68", walk=10, meal=90, k=5)
    shop = {"id": "B", "name": "湯包早餐", "lat": 24.13, "lng": 120.68, "price": None,
            "hours": [["05:30", "11:30"]], "closed_weekdays": [], "reviews": ["湯包很好吃"]}
    ok_, maybe_, no_, _ = recommend(args, [shop], lambda *a: calls.append(a) or [])
    assert not calls and not ok_ and not maybe_ and no_[0]["checks"]["營業"][0] == F
    walk = lambda d: {"type": "pedestrian", "travelSummary": {"duration": d}}
    dep = datetime(2026, 11, 20, 19, 0)
    route = lambda *secs, start="2026-11-20T19:02:00": {"start_time": start, "sections": list(secs)}
    assert check_route(route(walk(720)), 10, dep)[0] == F    # 單段步行上限
    assert check_route(route(walk(300), {"type": "drive"}), 10, dep)[0] == F
    assert check_route(route(walk(300), {"type": "transit"}, walk(400)), 10, dep)[0] == T
    assert check_route(route(walk(300), start="2026-11-20T18:53:18"), 10, dep)[0] == F  # 早於出發時間
    assert combine([T, U, T]) == U and combine([T, U, F]) == F and combine([T, T]) == T  # 有 U 無 F
    print("selftest ok")


def main():
    if sys.argv[1:] == ["selftest"]:
        return selftest()
    p = argparse.ArgumentParser()
    p.add_argument("--context", required=True, help="用餐情境，例如 慶生、約會")
    p.add_argument("--budget", type=int, required=True, help="每人預算（元）")
    p.add_argument("--depart", required=True, help="出發時間，例如 2026-11-20T19:00（須晚於現在）")
    p.add_argument("--origin", required=True, help="出發地 緯度,經度")
    p.add_argument("--meal", type=int, default=setting("defaults", "meal_min"), help="用餐分鐘（未給時為假設值）")
    p.add_argument("--walk", type=int, default=setting("defaults", "walk_min"), help="單段步行上限分鐘")
    p.add_argument("--k", type=int, default=setting("defaults", "recall_k"), help="情境召回幾家")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--data", default=str(HERE / "restaurants.json"),
                   help="餐廳資料；真實資料由 corpus/2_餐廳抽取.ipynb 產生在 ../corpus/restaurants.json")
    args = p.parse_args()
    data = json.loads(Path(args.data).read_text(encoding="utf-8"))["restaurants"]
    ok, maybe, no, notes = recommend(args, data, plans_offline if args.offline else plans_online)
    for n in notes:
        print("※", n)
    show(ok, maybe, no, args.context)
    if args.offline:
        print("\n※ --offline：所有店都套用同一份實測路線樣本，交通結果不代表真實路線。")


if __name__ == "__main__":
    main()
