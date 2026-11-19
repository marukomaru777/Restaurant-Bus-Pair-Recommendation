# 推薦 API（給前端）

## 啟動

```bash
cd api
pip install -r requirements.txt   # 第一次：FastAPI、uvicorn
python server.py                  # http://127.0.0.1:8000
```

- 需要 Python 3.11 以上。
- 不是離線模式時要查 TDX，所以 repo 根目錄 `.env` 要有 TDX 金鑰（範本 `.env.example`）。
- **http://127.0.0.1:8000/docs**：Swagger 文件，每個欄位都有說明。按「Try it out」就能直接送請求看回傳，**建議先從這裡開始**。
- http://127.0.0.1:8000 是**示範頁**（`api/demo.html`），正式畫面照它改。
- 已開放跨來源（CORS），前端開發伺服器在別的 port（例如 Vite 的 5173）也能直接呼叫。

## 開發畫面時請用離線模式

在請求裡加上 `"offline": true`：

- **不查 TDX，馬上回傳**。
- 所有店都套用同一條公車路線樣本，所以交通結果不是真的，但格式和真的一模一樣。

真的查 TDX 時，**每家候選店約要 13 秒**（免費方案每分鐘 5 次），5 家就要 1 分多鐘。畫面一定要有「查詢中」的狀態。

## `GET /health`

確認伺服器活著。

```json
{ "ok": true, "data": "corpus/restaurants.json" }
```

`data` 表示目前用哪份餐廳資料：

- `corpus/restaurants.json`：真實影片資料。
- `prototype/restaurants.json`：示意資料，有 5 家假餐廳。

## `POST /recommend`

### 請求

```json
{
  "context": "慶生",
  "budget": 600,
  "depart": "2026-11-20T19:00",
  "origin": [24.1372, 120.6869],
  "offline": true
}
```

| 欄位 | 必填 | 型別 | 說明 |
|---|---|---|---|
| `context` | ✅ | 字串 | 用餐情境，例如 `慶生`、`約會`、`朋友聚餐` |
| `budget` | ✅ | 正整數 | 每人預算（元） |
| `depart` | ✅ | 字串 | 出發時間 `YYYY-MM-DDTHH:MM`，可直接用 `<input type="datetime-local">` 的值。**不是離線模式時，必須晚於現在** |
| `origin` | ✅ | `[緯度, 經度]` | 出發地。**緯度在前**（台中約 24.1、120.6），寫反會回 400 |
| `offline` | | 布林 | 預設 `false`；開發畫面時用 `true` |
| `meal_min` | | 整數 10–300 | 用餐分鐘，預設 90 |
| `walk_min` | | 整數 1–30 | 單段步行上限分鐘，預設 10 |
| `recall_k` | | 整數 1–10 | 先依情境挑幾家再查交通，預設 5。越多越慢 |

### 回應（200）

```json
{
  "request": { "context": "慶生", "budget": 600, "depart": "2026-11-20T19:00", "origin": [24.1372, 120.6869],
               "meal_min": 90, "walk_min": 10, "recall_k": 5, "offline": true },
  "recommended": [ /* 餐廳，最多 3 間，已排序 */ ],
  "uncertain":   [ /* 餐廳：有條件查不到，請使用者自行確認 */ ],
  "rejected":    [ /* 餐廳：有條件不符合 */ ],
  "notes": ["offline：所有店套用同一份路線樣本，交通結果不是真的", "用餐時長未指定，假設 90 分鐘"],
  "data": "prototype/restaurants.json"
}
```

- 三組都要顯示，**不要只顯示 `recommended`**。`uncertain` 的店可能其實可以去，只是缺資料，例如影片沒講價格。
- `notes` 是要讓使用者看到的提醒，請照原文顯示。
- 三組都空的時候，`notes` 最後一則會說明原因，例如語料沒有提到這個情境。

### 一間餐廳

```json
{
  "id": "R1",
  "name": "示意餐廳 A（勤美）",
  "address": "台中市西區…",
  "lat": 24.151, "lng": 120.6635,
  "state": "T",
  "relevance": 1.0,
  "evidence": "包廂很適合慶生，店家會幫忙準備蛋糕",
  "counter_evidence": [],
  "price": [450, 580],
  "hours": [["11:30", "21:30"]],
  "closed_weekdays": [],
  "checks": {
    "budget":  { "state": "T", "reason": "450–580 元，在 600 元內" },
    "transit": { "state": "T", "reason": "全程公車＋步行" },
    "hours":   { "state": "T", "reason": "19:23 到、20:53 吃完，21:30 打烊前" }
  },
  "route": {
    "depart": "2026-11-20T19:00:00", "arrive": "2026-11-20T19:23:32",
    "travel_min": 24, "transfers": 0, "fare": 18,
    "summary": "走 1 分，19:01 搭 309 到 中正國小(專用道)，走 8 分（19:23 到店，0 次轉乘）",
    "sections": [
      { "type": "walk", "minutes": 1, "depart": "…", "arrive": "…", "from": null, "to": "臺中車站(A月台)",
        "from_location": {"lat": 24.137199, "lng": 120.686897}, "to_location": {"lat": 24.137749, "lng": 120.686462} },
      { "type": "bus", "minutes": 14, "depart": "…", "arrive": "…", "from": "臺中車站(A月台)", "to": "中正國小(專用道)",
        "bus": "309", "headsign": "梧棲觀光漁港",
        "from_location": {"lat": 24.137749, "lng": 120.686462}, "to_location": {"lat": 24.152529, "lng": 120.667992} },
      { "type": "walk", "minutes": 8, "depart": "…", "arrive": "…", "from": "中正國小(專用道)", "to": null,
        "from_location": {"lat": 24.152529, "lng": 120.667992}, "to_location": {"lat": 24.150999, "lng": 120.663498} }
    ]
  },
  "sources": [ { "video": "https://www.youtube.com/watch?v=…", "published_at": "2025-05-28", "transcript_source": "人工字幕" } ]
}
```

| 欄位 | 說明 |
|---|---|
| `state` | `T` 全部通過、`U` 有條件查不到、`F` 有條件不符合 |
| `evidence` | 支持這個情境的原文引文，例如影片裡怎麼說，建議顯示成引號。開頭的 `【面向｜標籤】` 是標籤，可以拆開來顯示成標籤徽章 |
| `counter_evidence` | 負評（反證），例如「口味稍微偏鹹」，可以收合顯示 |
| `price` | `[最低, 最高]` 或 `null`（查不到） |
| `hours` | 當天營業時段，可能有多段；打烊早於開店表示營業到隔天 |
| `closed_weekdays` | 公休日，`0`＝週一、`6`＝週日 |
| `checks.*.reason` | 給使用者看的判定理由，請照原文顯示 |
| `route` | 公車方案；查不到時是 `null`（看 `checks.transit.reason`）。預算或營業已確定不符的店**不會去查公車**（省時間），`route` 是 `null`、`checks.transit.reason` 是「未查（其他條件已不符）」 |
| `route.sections` | 依序的每一段：`walk` 走路、`bus` 公車（`bus` 路線號、`headsign` 往哪個方向）。要畫地圖就用 `from_location` → `to_location` 連線 |
| `sources` | 資料來源影片，可以做成「看原影片」連結 |

時間都是台灣時間、不帶時區，格式 `YYYY-MM-DDTHH:MM:SS`。

### 錯誤

| 狀態碼 | 何時 | 內容 |
|---|---|---|
| 400 | 欄位缺漏或格式錯 | `{"error": "budget（每人預算，元）要是正整數"}`，可以直接顯示給使用者 |
| 404 | 路徑錯誤 | `{"error": "…"}` |
| 500 | 伺服器錯誤 | `{"error": "伺服器錯誤：…"}` |

## 直接複製的範例

```js
async function recommend({ context, budget, depart, origin, offline = true }) {
  const res = await fetch("http://127.0.0.1:8000/recommend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ context, budget, depart, origin, offline }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error);   // 400 的訊息可以直接給使用者看
  return data;                                // { recommended, uncertain, rejected, notes, ... }
}

// 用法
const data = await recommend({ context: "慶生", budget: 600, depart: "2026-11-20T19:00", origin: [24.1372, 120.6869] });
console.log(data.recommended.map(r => `${r.name}：${r.route?.summary}`));
```

## 目前限制

- **出發地只吃經緯度，不要讓使用者自己打**。用瀏覽器的 `navigator.geolocation` 取得目前位置；使用者拒絕定位時，改讓他從常用地點選。寫法照 `demo.html` 的 `myLocation()`。定位只在 **https 或 localhost** 能用。需要輸入地址的話跟後端說。
- **情境是字面比對**：`context` 用語料裡的說法比較容易對到，例如 `慶生`、`約會`、`聚餐`、`水餃`。
- 伺服器一次只處理一個請求，因為 TDX 免費額度的限制，所以不適合多人同時測。
