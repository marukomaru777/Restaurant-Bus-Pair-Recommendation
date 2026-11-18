# 語料：臺中美食影片 → 餐廳資料

改自組員的台北版爬蟲與經驗抽取 notebook，對應 DESIGN.md 模組 1–2、§9.1 標籤表、§9.2 抽取規則。

| 順序 | 檔案 | 做什麼 | 需要 |
|---|---|---|---|
| 1 | `1_youtube爬蟲.ipynb` | 搜尋影片、抓字幕與說明欄；沒字幕的用 Whisper 轉 | yt-dlp（Whisper 選用） |
| 2 | `2_餐廳抽取.ipynb` | Gemini 抽餐廳／情境片段／價格 → 程式查核 → 人工審核 → `restaurants.json` | `GEMINI_API_KEY`、TDX 金鑰 |
| — | `places.py` | 說明欄解析營業時間與地址、TDX 地址轉座標（給步驟 2 用） | |

金鑰放 repo 根目錄 `.env`（範本 `.env.example`），模型名稱在 `config.toml` 的 `[llm]`。

產出接到原型：

```bash
cd ../prototype
python proto.py --data ../corpus/restaurants.json --context 慶生 --budget 600 --depart 2026-11-20T19:00 --origin 24.1372,120.6869
```

**`raw/` 與 `restaurants.json` 不進 git**：含逐字稿原文，依 D017 只供研究原型內部使用、不公開散布，而群組 repo 是公開的。要分享資料給組員請私下傳。

## 已知限制

- 挑選標準（關鍵字、年份 2023–2026）是暫定值，待全組確認（O001）。
- 營業時間與地址只取自說明欄；說明欄沒列地址的店拿不到座標，先排除（之後依 §9.2-5 用 Places）。
- 價格多半抽不到 → 預算判 U（O012）。
- 同一間店只用字面比對合併；§9.2-5 的向量候選＋LLM 判定之後再做。
