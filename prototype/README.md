# 本機最小原型

驗證核心流程能不能跑通：**情境召回 → TDX 公車方案 → 時間線 → T／F／U 查核 → 排序（最多 3 間）**。
只用 Python 標準函式庫，不需要安裝套件。

> 餐廳資料 `restaurants.json` 是**示意資料**（店名、價格、營業時間、評論都是虛構的，只有座標是臺中真實區域）。

## 設定（只做一次）

所有設定都從 repo 根目錄的 `settings.py` 取得，來源依優先順序為：

| 來源 | 放什麼 | 進 git |
|---|---|---|
| 環境變數 | 部署（例如 AWS）時在平台上設定，蓋過下面兩者 | — |
| `.env` | 機密，例如 TDX 金鑰 | **不進** |
| `config.toml` | 一般設定與預設值（API 網址、用餐 90 分、步行 10 分…） | 進 |

把根目錄的 `.env.example` 複製成 `.env`，填入：

```
TDX_CLIENT_ID=你的 Client ID
TDX_CLIENT_SECRET=你的 Client Secret
```

> 舊的 `tdx/.tdx_key`、`tdx/.tdx_secret` 已不再讀取，請改用 `.env`。

## 執行

```bash
cd prototype
python proto.py selftest
python proto.py --context 慶生 --budget 600 --depart 2026-11-20T19:00 --origin 24.1372,120.6869
python proto.py --context 慶生 --budget 600 --depart 2026-11-20T19:00 --origin 24.1372,120.6869 --offline
```

- `selftest`：依 OpenSpec `constraint-checking` 的情境檢查判定規則，不呼叫 TDX。
- `--depart` 必須晚於現在，否則 TDX 回 400。
- 免費方案每分鐘 5 次，每查一家店等 13 秒。同一把金鑰兩個人同時跑會出現 HTTP 429。
- `--offline`：不呼叫 TDX，所有店套用同一份實測路線樣本，只用來測流程。

其他參數：`--meal`（用餐分鐘）、`--walk`（單段步行上限分鐘）、`--k`（召回幾家），預設值都在 `config.toml`。
`--data ../corpus/restaurants.json` 改用真實影片資料（產生方式見 `corpus/README.md`）。

營業時間格式：`"hours": [["11:30","14:00"],["17:30","21:00"]]`、`"closed_weekdays": [0]`（0＝週一）；打烊早於開店視為跨午夜。

## 目前跳過的部分

| 跳過 | 現在的替代 | 對應 |
|---|---|---|
| LLM 解析需求 | 命令列參數 | 模組 4 |
| BM25／向量／混合檢索 | 字元二元組重疊比例 | 模組 5、RQ1 |
| 知識圖譜 | JSON 檔 | 模組 3 |
| 凌晨到店算前一天時段 | 不處理 | O012 |

已知限制：字面比對看不懂否定句。例如查「約會」時，評論「人多很吵，**不太適合**約會」也會被召回。這正是 RQ1 要用語意檢索比較的理由。

## 實測發現

TDX 會回傳**早於指定出發時間**的方案（`depart=19:00` 卻回 18:53 出發），所以程式會檢查每個方案的 `start_time`。詳見 `tdx/TDX實測紀錄.md` 4.2。
