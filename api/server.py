"""推薦 API（FastAPI）：把 prototype/proto.py 包成 HTTP，給前端呼叫。

    pip install -r requirements.txt
    python server.py              # http://127.0.0.1:8000 ；Swagger 文件 /docs（設定在 config.toml [api]）
    python server.py selftest     # 起一個臨時伺服器，用離線模式打一次，檢查回傳格式

欄位說明看 /docs（由下面的 Pydantic 模型自動產生），補充說明見 api/API.md。
ponytail: 路由用一般 def（FastAPI 會丟到執行緒池跑），TDX 免費方案每分鐘只能 5 次，
多人同時查會被擋（429）；要多人用時先換付費 TDX 方案或加佇列。
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(ROOT / "prototype")]
import explain  # noqa: E402
import parse as parser  # noqa: E402
import proto  # noqa: E402
from settings import setting  # noqa: E402

State = Literal["T", "U", "F"]


def data_path():
    """有真實資料（corpus/2_餐廳抽取.ipynb 產生）就用真實的，否則用原型的示意資料。"""
    real = ROOT / "corpus" / "restaurants.json"
    return real if real.exists() else ROOT / "prototype" / "restaurants.json"


# ---------- 請求 ----------
class RecommendRequest(BaseModel):
    context: str = Field(min_length=1, description="用餐情境，例如 慶生、約會、朋友聚餐", examples=["慶生"])
    budget: StrictInt = Field(gt=0, description="每人預算（元）", examples=[600])
    depart: datetime = Field(description="出發時間 YYYY-MM-DDTHH:MM（台灣時間）；非離線模式須晚於現在", examples=["2026-11-20T19:00"])
    origin: List[float] = Field(min_length=2, max_length=2, description="出發地 [緯度, 經度]，緯度在前", examples=[[24.1372, 120.6869]])
    offline: StrictBool = Field(False, examples=[True], description="true：不查 TDX、馬上回傳，交通是同一份樣本（開發畫面用）")
    meal_min: StrictInt = Field(default_factory=lambda: setting("defaults", "meal_min"), ge=10, le=300, description="用餐分鐘；不填用預設 90", examples=[90])
    walk_min: StrictInt = Field(default_factory=lambda: setting("defaults", "walk_min"), ge=1, le=30, description="單段步行上限分鐘；不填用預設 10", examples=[10])
    recall_k: StrictInt = Field(default_factory=lambda: setting("defaults", "recall_k"), ge=1, le=10, description="先依情境挑幾家再查交通；越多越慢（每家約 13 秒）；不填用預設 5", examples=[5])

    @field_validator("context")
    @classmethod
    def strip_context(cls, v):
        if not v.strip():
            raise ValueError("empty")
        return v.strip()

    @field_validator("origin")
    @classmethod
    def lat_first(cls, v):
        if not (21 < v[0] < 26 and 119 < v[1] < 123):
            raise ValueError("not in Taiwan")
        return v

    @model_validator(mode="after")
    def future_depart(self):
        if not self.offline and self.depart.replace(tzinfo=None) <= datetime.now():
            raise ValueError("depart in past")
        return self


class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500, description="使用者的一句需求；回答補問時把回答接在原句後面再送一次",
                      examples=["明天晚上七點跟女友慶生，兩個人預算一千五"])


# 驗證失敗時給使用者看的中文訊息（依欄位）；400 + {"error": ...}，前端可直接顯示
HINTS = {
    "context": "context（用餐情境）必填，例如 \"慶生\"",
    "budget": "budget（每人預算，元）要是正整數",
    "depart": "depart（出發時間）格式要像 \"2026-11-20T19:00\"",
    "origin": "origin（出發地）要是 [緯度, 經度]，例如 [24.1372, 120.6869]",
    "offline": "offline 要是 true 或 false",
    "meal_min": "meal_min 要是 10–300 的整數",
    "walk_min": "walk_min 要是 1–30 的整數",
    "recall_k": "recall_k 要是 1–10 的整數",
    "text": "text（需求句子）必填，最多 500 字",
}


# ---------- 回應 ----------
class Check(BaseModel):
    state: State
    reason: str = Field(description="給使用者看的判定理由")


class Location(BaseModel):
    lat: float
    lng: float


class Section(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    type: Literal["walk", "bus"] | str = Field(description="walk 走路、bus 公車")
    minutes: int
    depart: str
    arrive: str
    from_: Optional[str] = Field(None, alias="from", description="起點名稱（站名）；出發地為 null")
    to: Optional[str] = Field(None, description="終點名稱（站名）；餐廳為 null")
    from_location: Location
    to_location: Location
    bus: Optional[str] = Field(None, description="公車路線號（type=bus 才有）")
    headsign: Optional[str] = Field(None, description="往哪個方向（type=bus 才有）")


class Route(BaseModel):
    depart: str
    arrive: str = Field(description="到店時間")
    travel_min: int
    transfers: int
    fare: Optional[int] = None
    summary: str = Field(description="一句話路線說明，可直接顯示")
    sections: List[Section] = Field(description="依序的每一段；畫地圖用 from_location → to_location 連線")


class Checks(BaseModel):
    budget: Check
    transit: Check
    hours: Check


class Restaurant(BaseModel):
    id: str
    name: str
    address: Optional[str] = None
    lat: float
    lng: float
    state: State = Field(description="T 全部通過、U 有條件查不到、F 有條件不符合")
    relevance: float = Field(description="情境符合程度 0–1")
    explanation: Optional[str] = Field(None, description="推薦說明，可直接顯示；只有 recommended 有，其他組是 null")
    explanation_source: Optional[Literal["llm", "template"]] = Field(None, description="llm：Gemini 寫且通過事實查核；template：固定模板（離線、失敗或查核沒過）")
    evidence: Optional[str] = Field(None, description="支持情境的原文引文；開頭【面向｜標籤】可拆成徽章")
    counter_evidence: List[str] = Field(default_factory=list, description="負評（反證）")
    price: Optional[List[int]] = Field(None, description="[最低, 最高]；null 為查不到")
    hours: Optional[List[List[str]]] = Field(None, description="營業時段，可能多段；打烊早於開店表示營業到隔天")
    closed_weekdays: List[int] = Field(default_factory=list, description="公休日，0＝週一、6＝週日")
    checks: Checks
    route: Optional[Route] = Field(None, description="公車方案；查不到時 null（看 checks.transit.reason）")
    sources: List[dict] = Field(default_factory=list, description="資料來源影片")


class RecommendResponse(BaseModel):
    request: dict = Field(description="實際採用的參數（含預設值）")
    recommended: List[Restaurant] = Field(description="推薦，最多 3 間，已排序")
    uncertain: List[Restaurant] = Field(description="有條件查不到，請使用者自行確認；也要顯示")
    rejected: List[Restaurant] = Field(description="有條件不符合")
    notes: List[str] = Field(description="要讓使用者看到的提醒，照原文顯示")
    data: str = Field(description="目前用的餐廳資料檔")


class Question(BaseModel):
    field: str = Field(description="要補的欄位：context、budget、people、depart")
    question: str = Field(description="給使用者看的補問")


class Tags(BaseModel):
    occasions: List[str] = Field(description="場合標籤（DESIGN §9.1）")
    companions: List[str] = Field(description="同行對象標籤")
    aspects: List[str] = Field(description="在意的面向")


class ParseResponse(BaseModel):
    request: dict = Field(description="已確定的 /recommend 欄位（context、budget、depart、meal_min 中有確定的才有）；origin 不在這裡，要前端定位")
    tags: Tags
    people: Optional[int] = Field(description="人數；原句推不出來是 null")
    origin_text: Optional[str] = Field(description="原句提到的出發地點，只供提醒")
    questions: List[Question] = Field(description="補問，依序問；空的表示可以直接送 /recommend")
    ready: bool = Field(description="true：request 加上 origin 就能送 /recommend")
    notes: List[str] = Field(description="要讓使用者看到的提醒，例如整團預算換算")


class Health(BaseModel):
    ok: bool
    data: str


class Error(BaseModel):
    error: str


# ---------- 轉換 ----------
def route_json(route):
    sections = []
    for s in route["sections"]:
        sec = {"type": {"transit": "bus", "pedestrian": "walk"}.get(s["type"], s["type"]),
               "minutes": round(s["travelSummary"]["duration"] / 60),
               "depart": s["departure"]["time"], "arrive": s["arrival"]["time"],
               "from": s["departure"]["place"].get("name"), "to": s["arrival"]["place"].get("name"),
               "from_location": s["departure"]["place"]["location"], "to_location": s["arrival"]["place"]["location"]}
        if s["type"] == "transit":
            sec["bus"] = s["transport"].get("name")
            sec["headsign"] = s["transport"].get("headsign")
        sections.append(sec)
    return {"depart": route["start_time"], "arrive": route["end_time"],
            "travel_min": round(route["travel_time"] / 60), "transfers": route["transfers"],
            "fare": route.get("total_price"), "summary": proto.describe_route(route), "sections": sections}


def item_json(x):
    r = x["r"]
    checks = {key: {"state": st, "reason": why} for key, (st, why) in
              zip(("budget", "transit", "hours"), (x["checks"].get(k, (proto.U, "未查核")) for k in ("預算", "交通", "營業")))}
    return {
        "id": r["id"], "name": r["name"], "address": r.get("address"), "lat": r["lat"], "lng": r["lng"],
        "state": x["state"], "relevance": x["rel"],
        "explanation": x.get("explanation"), "explanation_source": x.get("explanation_source"),
        "evidence": x["quote"],
        "counter_evidence": r.get("counter", []), "price": r.get("price"), "hours": r.get("hours"),
        "closed_weekdays": r.get("closed_weekdays", []), "checks": checks,
        "route": route_json(x["route"]) if x.get("route") else None, "sources": r.get("sources", []),
    }


# ---------- 路由 ----------
app = FastAPI(title="臺中公車餐廳推薦 API",
              description="情境召回 → TDX 公車方案 → T／F／U 查核 → 排序。開發畫面時請在請求加 `\"offline\": true`。")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(RequestValidationError)
def bad_request(request: Request, exc: RequestValidationError):
    err = exc.errors()[0]
    field = next((str(p) for p in err["loc"] if p in HINTS), None)
    if field is None and "depart in past" in str(err.get("msg")):
        msg = "depart（出發時間）要晚於現在，TDX 不收過去的時間"
    else:
        msg = HINTS.get(field, "請送 JSON 物件，欄位見 /docs")
    return JSONResponse({"error": msg}, status_code=400)


@app.get("/", include_in_schema=False)
def demo():
    return FileResponse(HERE / "demo.html")


@app.get("/health", response_model=Health, summary="確認伺服器活著、目前用哪份資料")
def health():
    return {"ok": True, "data": data_path().relative_to(ROOT).as_posix()}


@app.post("/recommend", response_model=RecommendResponse, response_model_by_alias=True,
          responses={400: {"model": Error, "description": "欄位缺漏或格式錯，error 可直接顯示給使用者"},
                     422: {"description": "不會出現：驗證錯誤一律改回 400"}},
          summary="依情境、預算、出發時間與地點推薦餐廳")
def recommend(req: RecommendRequest):
    args = proto_args(req)
    restaurants = json.loads(data_path().read_text(encoding="utf-8"))["restaurants"]
    ok, maybe, no, found = proto.recommend(args, restaurants, proto.plans_offline if req.offline else proto.plans_online)
    found += explain.explain(ok, req.context, use_llm=not req.offline)   # offline 不呼叫 Gemini，用固定模板
    notes = found + (["offline：所有店套用同一份路線樣本，交通結果不是真的"] if req.offline else []) \
        + ([f"用餐時長未指定，假設 {req.meal_min} 分鐘"] if "meal_min" not in req.model_fields_set else []) \
        + ([] if ok or maybe or no else [f"語料裡沒有提到「{req.context}」的餐廳，換個說法或等語料擴充"])
    return {
        "request": {**req.model_dump(), "depart": args.depart},
        "recommended": [item_json(x) for x in ok],
        "uncertain": [item_json(x) for x in maybe],
        "rejected": [item_json(x) for x in no],
        "notes": notes,
        "data": data_path().relative_to(ROOT).as_posix(),
    }


@app.post("/parse", response_model=ParseResponse,
          responses={400: {"model": Error, "description": "text 缺漏或太長"},
                     502: {"model": Error, "description": "Gemini 忙線或失敗；請使用者稍後再試或直接填表單"},
                     503: {"model": Error, "description": "伺服器沒設定 GEMINI_API_KEY"},
                     422: {"description": "不會出現：驗證錯誤一律改回 400"}},
          summary="把一句需求解析成 /recommend 的欄位，缺的列成補問（Gemini）")
def parse_text(req: ParseRequest):
    if not os.environ.get("GEMINI_API_KEY"):
        return JSONResponse({"error": "伺服器沒設定 GEMINI_API_KEY，請直接填表單"}, status_code=503)
    try:
        return parser.parse(req.text)
    except Exception as e:
        return JSONResponse({"error": f"需求解析失敗（{parser.gemini_error(e)}），請稍後再試或直接填表單"}, status_code=502)


def proto_args(req):
    from types import SimpleNamespace
    return SimpleNamespace(context=req.context, budget=req.budget,
                           depart=req.depart.replace(tzinfo=None).isoformat(timespec="minutes"),
                           origin=f"{req.origin[0]},{req.origin[1]}",
                           meal=req.meal_min, walk=req.walk_min, k=req.recall_k)


# ---------- 自我檢查 ----------
def selftest():
    import threading
    import time
    import urllib.error
    import urllib.request

    import uvicorn
    global data_path
    data_path = lambda: ROOT / "prototype" / "restaurants.json"  # 固定用示意資料，結果才可預期
    os.environ["RETRIEVAL_METHOD"] = "bm25"   # 召回固定用 bm25：不呼叫 Gemini，結果才可預期
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    base = "http://127.0.0.1:8765"

    def post(body):
        req = urllib.request.Request(base + "/recommend", json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    good = {"context": "慶生", "budget": 600, "depart": "2026-11-20T19:00", "origin": [24.1372, 120.6869], "offline": True}
    status, res = post(good)
    assert status == 200, res
    assert res["recommended"] and res["uncertain"], res   # 示意資料：A 推薦；C 缺價格、D 跨預算 → 不確定
    for x in res["recommended"]:
        assert x["checks"]["budget"]["state"] == "T" and x["evidence"]
        assert x["explanation_source"] == "template" and x["explanation"].startswith(x["name"])   # offline → 模板
        assert "from" in x["route"]["sections"][1] and x["route"]["sections"][1]["bus"]   # 欄位名是 from，不是 from_
    assert res["request"]["origin"] == [24.1372, 120.6869] and res["request"]["meal_min"] == 90
    assert "假設 90 分鐘" in " ".join(res["notes"])
    assert post({**good, "budget": "600"}) == (400, {"error": HINTS["budget"]})
    assert post({**good, "origin": [120.68, 24.13]}) == (400, {"error": HINTS["origin"]})   # 經緯度寫反
    assert "晚於現在" in post({**good, "offline": False, "depart": "2020-01-01T10:00"})[1]["error"]
    assert "沒有提到" in post({**good, "context": "火星料理"})[1]["notes"][-1]
    # /parse：不打 Gemini，換成假的解析結果，只測路由、驗證與回傳格式
    fake = parser.Parsed(context="慶生", context_quote="慶生", budget_amount=600, budget_scope="每人", budget_quote="600")
    parser.parse = lambda text: parser.finish(fake, text, datetime(2026, 11, 19, 15, 0))
    os.environ.setdefault("GEMINI_API_KEY", "selftest")
    def post_parse(body):
        req = urllib.request.Request(base + "/parse", json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)
    status, pres = post_parse({"text": "慶生 每人600"})
    assert status == 200 and pres["request"] == {"context": "慶生", "budget": 600}, pres
    assert not pres["ready"] and pres["questions"][0]["field"] == "depart"
    assert post_parse({"text": ""}) == (400, {"error": HINTS["text"]})
    with urllib.request.urlopen(base + "/health") as r:
        assert json.load(r)["ok"]
    with urllib.request.urlopen(base + "/openapi.json") as r:
        assert "/recommend" in json.load(r)["paths"]
    server.should_exit = True
    print(f"api selftest ok（推薦 {len(res['recommended'])}、不確定 {len(res['uncertain'])}、不通過 {len(res['rejected'])}）")


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        selftest()
    else:
        import uvicorn
        host, port = setting("api", "host"), setting("api", "port")
        print(f"推薦 API：http://{host}:{port}  （示範頁 /、Swagger 文件 /docs）")
        print(f"資料：{data_path().relative_to(ROOT).as_posix()}；Ctrl+C 停止")
        uvicorn.run(app, host=host, port=port)
