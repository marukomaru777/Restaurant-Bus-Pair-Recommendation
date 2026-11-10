"""TDX 台中公車資料：API 實測(probe) 與到站預估蒐集(collect)。

金鑰不寫在程式裡：Client ID 從環境變數 TDX_CLIENT_ID 讀取；
Secret 若沒有設 TDX_CLIENT_SECRET，就讀本機檔案 .tdx_secret（已列入 .gitignore）。

用法：
    python tdx.py probe                    # 打一次各 API，存回應樣本到 samples/
    python tdx.py probe walk               # 只測路線規劃（含步行參數對照）
    python tdx.py collect 300 [路線...]     # 每分鐘抓一次到站預估，存到 data/eta_YYYYMMDD.jsonl
"""
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
API = "https://tdx.transportdata.tw/api"
HERE = Path(__file__).parent
_token = None


def get_token():
    global _token
    if not os.environ.get("TDX_CLIENT_ID", "").strip():
        sys.exit('沒有設定 Client ID：先執行 $env:TDX_CLIENT_ID = "你的 Client ID"（每開一個新終端機都要重設）')
    if not os.environ.get("TDX_CLIENT_SECRET", "").strip():
        # 優先讀本機檔案 .tdx_secret（已列入 .gitignore），避免 Secret 留在終端機畫面
        f = HERE / ".tdx_secret"
        secret = f.read_text(encoding="utf-8-sig").strip() if f.exists() else getpass.getpass("TDX Client Secret: ")
        if not secret.strip():
            sys.exit("沒有讀到 Secret：請把它存進 .tdx_secret 檔案")
        os.environ["TDX_CLIENT_SECRET"] = secret.strip()
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": os.environ["TDX_CLIENT_ID"].strip(),
        "client_secret": os.environ["TDX_CLIENT_SECRET"].strip(),
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, body)) as r:
            _token = json.load(r)["access_token"]
    except urllib.error.HTTPError as e:
        cid = os.environ["TDX_CLIENT_ID"]
        sys.exit(f"取得 token 失敗 HTTP {e.code}: {e.read().decode(errors='replace')}\n"
                 f"Client ID 長度 {len(cid)}，開頭 {cid[:4]!r}、結尾 {cid[-4:]!r}"
                 f"；Secret 長度 {len(os.environ['TDX_CLIENT_SECRET'])}")


def call(path, **params):
    """回傳 (HTTP 狀態, 內容文字)。401 時重拿一次 token。"""
    if _token is None:
        get_token()
    # MaaS 路線規劃不接受 $format（實測回 400），只有 basic API 加
    fmt = {"$format": "JSON"} if path.startswith("/basic") else {}
    url = f"{API}{path}?" + urllib.parse.urlencode({**fmt, **params})
    for _ in range(2):
        req = urllib.request.Request(url, headers={"authorization": f"Bearer {_token}",
                                                   "Accept-Encoding": "identity"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            if e.code == 401:
                get_token()
                continue
            return e.code, e.read().decode(errors="replace")
    return 401, ""


def probe():
    out = HERE / "samples"
    out.mkdir(exist_ok=True)
    # 出發時間不能早於送出當下（實測回 400），probe 中間會等待，所以往後抓 10 分鐘
    depart = (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S")
    # ponytail: 起訖點寫死（台中車站 → 勤美誠品），只為確認 API 能不能用、回什麼欄位
    tests = {
        "eta_route300": ("/basic/v2/Bus/EstimatedTimeOfArrival/City/Taichung/300", {"$top": "5"}),
        "stops_route300": ("/basic/v2/Bus/StopOfRoute/City/Taichung/300", {"$top": "1"}),
        "schedule_route300": ("/basic/v2/Bus/Schedule/City/Taichung/300", {"$top": "1"}),
        "trip_planning": ("/maas/routing", {"origin": "24.1372,120.6869",
                                             "destination": "24.1510,120.6635",
                                             "gc": "1.0", "top": "1", "transit": "5",
                                             "depart": depart}),
        # gc=1.0（時間最短）時第一／最後一哩實測變成 YOXI 計程車；以下兩組對照找出步行設定
        "trip_walk_gc1": ("/maas/routing", {"origin": "24.1372,120.6869",
                                             "destination": "24.1510,120.6635",
                                             "gc": "1.0", "top": "1", "transit": "5", "depart": depart,
                                             "first_mile_mode": "0", "first_mile_time": "10",
                                             "last_mile_mode": "0", "last_mile_time": "10"}),
        "trip_walk_gc0": ("/maas/routing", {"origin": "24.1372,120.6869",
                                             "destination": "24.1510,120.6635",
                                             "gc": "0.0", "top": "1", "transit": "5", "depart": depart,
                                             "first_mile_mode": "0", "first_mile_time": "10",
                                             "last_mile_mode": "0", "last_mile_time": "10"}),
    }
    if sys.argv[2:] == ["walk"]:
        tests = {k: v for k, v in tests.items() if k.startswith("trip")}
    for name, (path, params) in tests.items():
        status, text = call(path, **params)
        (out / f"{name}.json").write_text(text, encoding="utf-8")
        print(f"{name:20s} HTTP {status}  {len(text):>7,d} bytes")
        time.sleep(13)  # 免費方案每分鐘 5 次


def collect(routes):
    out = HERE / "data"
    out.mkdir(exist_ok=True)
    print(f"蒐集 {routes}，Ctrl+C 停止")
    get_token()
    while True:
        start = time.time()
        f = out / f"eta_{datetime.now():%Y%m%d}.jsonl"
        for route in routes:
            fetched_at = datetime.now().isoformat(timespec="seconds")
            status, text = call(f"/basic/v2/Bus/EstimatedTimeOfArrival/City/Taichung/{route}")
            rec = {"fetched_at": fetched_at, "route": route, "status": status,
                   "data": json.loads(text) if status == 200 else text[:500]}
            with f.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(fetched_at, route, status)
        time.sleep(max(0, 60 - (time.time() - start)))


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("probe", "collect"):
        sys.exit(__doc__)
    if sys.argv[1] == "probe":
        probe()
    else:
        # ponytail: 每分鐘每條路線 1 次，免費方案上限 5 次/分，所以最多 4 條
        collect(sys.argv[2:6] or ["300"])
