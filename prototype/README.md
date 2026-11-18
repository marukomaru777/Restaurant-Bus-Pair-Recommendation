# 本機最小原型

驗證核心流程能不能跑通：**情境召回 → TDX 公車方案 → 時間線 → T／F／U 查核 → 排序（最多 3 間）**。
只用 Python 標準函式庫，不需要安裝套件。

> 餐廳資料 `restaurants.json` 是**示意資料**（店名、價格、營業時間、評論都是虛構的，只有座標是臺中真實區域）。

## 設定 TDX 金鑰（只做一次）

在 `tdx/` 底下建立 `.tdx_key`，寫兩行：

```
你的 Client ID
你的 Client Secret
```

這個檔案已列入 `tdx/.gitignore`，不會被 commit。

> 舊的設定方式（環境變數 `TDX_CLIENT_ID` 加 `.tdx_secret` 檔）已改掉。兩個環境變數都有設時仍可用，否則請改建 `.tdx_key`。

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

其他參數：`--meal`（用餐分鐘，預設 90，為假設值）、`--walk`（單段步行上限分鐘，預設 10）、`--k`（召回幾家）。

## 目前跳過的部分

| 跳過 | 現在的替代 | 對應 |
|---|---|---|
| LLM 解析需求 | 命令列參數 | 模組 4 |
| BM25／向量／混合檢索 | 字元二元組重疊比例 | 模組 5、RQ1 |
| 知識圖譜 | JSON 檔 | 模組 3 |
| 跨午夜營業、公休日 | 不處理 | O012 |

已知限制：字面比對看不懂否定句。例如查「約會」時，評論「人多很吵，**不太適合**約會」也會被召回。這正是 RQ1 要用語意檢索比較的理由。

## 實測發現

TDX 會回傳**早於指定出發時間**的方案（`depart=19:00` 卻回 18:53 出發），所以程式會檢查每個方案的 `start_time`。詳見 `tdx/TDX實測紀錄.md` 4.2。
