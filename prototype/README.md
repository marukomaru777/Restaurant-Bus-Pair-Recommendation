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
| LLM 解析需求 | 命令列參數（`parse.py` 已有，API `/parse` 用；命令列還沒接） | 模組 4 |
| 知識圖譜 | JSON 檔 | 模組 3 |
| 凌晨到店算前一天時段 | 不處理 | O012 |

## 情境召回（`retrieve.py`，RQ1）

`config.toml` 的 `[retrieval] method` 切換四種方法，也可用環境變數，例如 `RETRIEVAL_METHOD=hybrid`：

| method | 做法 | 要 Gemini |
|---|---|---|
| `bigram` | 字元二元組重疊比例（原本的基準） | |
| `bm25` | BM25，以字元二元組為詞（**預設**） | |
| `vector` | `gemini-embedding-001` 餘弦相似度，門檻 `min_cos` | ✅ |
| `hybrid` | `w·bm25 + (1−w)·vector` | ✅ |

```bash
python retrieve.py compare 慶生 甜點 下午茶   # 同一批情境詞，印出四種方法在真實語料上的排名
```

- 文件 = 每則評論 + 店名；店分數取最高分。BM25 除以該查詢的理論上限，餘弦夾到 0–1，都不依候選集縮放（DESIGN §9）。
- 評論向量快取在 `corpus/raw/embeddings.json`（不進 git）。Gemini 失敗或沒金鑰時退回 bm25，並在 notes 說明。
- 2026-11-19 在 12 家、17 則評論上試：字面方法查「甜點」「下午茶」「小吃」都是零筆，向量排序合理（甜點 → 蛋糕、肉桂捲、湯圓）；但無關的店餘弦也有 0.60–0.68，**門檻 0.70 是看這批資料定的，語料擴充後要重調**（O005）。`gemini-embedding-2` 分數拉得較開但排序較差，沒採用。
- 語料只有一支影片，還不足以回答 RQ1；要比較得先擴充語料、建標註集（O013）。

### RQ1 評估

```bash
python retrieve.py evaluate                  # 用 rq1_labels.json
python retrieve.py evaluate 其他標註.json
```

標註檔每個查詢列出「應該找到的店名」，空的表示語料裡沒有相符的店，用來量誤召回。輸出每種方法的 Recall@k、Precision@k、MRR（k＝`recall_k`）。召回零家的查詢 Precision 算 0。vector／hybrid 若因 Gemini 失敗退回 bm25，該方法直接記為失敗，不會把 bm25 的分數算給它。

2026-11-19 第一次跑（12 家店、10 個查詢、k＝5）：

| method | Recall@5 | Prec@5 | MRR | 誤召回 |
|---|---|---|---|---|
| bigram | 0.32 | 0.40 | 0.41 | 0 |
| bm25 | 0.32 | 0.40 | 0.41 | 0 |
| vector | 0.67 | 0.59 | 0.75 | 0 |
| hybrid | 0.57 | 0.52 | 0.69 | 0 |

**只能當工具能跑的示範，不能當 RQ1 結論**：
- 標註是開發者一人標的，而且看過 `compare` 的結果才選查詢詞，有偏差。
- 只有 8 個查詢有相關店。
- 語料只有一支影片，bigram 和 bm25 在這麼少的資料上排名幾乎一樣。

正式評估前要由組員獨立標註，並在擴充後的語料上重跑（O013）。

已知限制：字面方法看不懂否定句。例如查「約會」時，評論「人多很吵，**不太適合**約會」也會被召回。向量也不保證分得出來，評估時要放這類例子。

## 實測發現

TDX 會回傳**早於指定出發時間**的方案（`depart=19:00` 卻回 18:53 出發），所以程式會檢查每個方案的 `start_time`。詳見 `tdx/TDX實測紀錄.md` 4.2。
