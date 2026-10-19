# 情境感知餐廳推薦與臺中公車分析

## Proposal 階段繳交檔案

- **① [Proposal Document](<Proposal doc/Proposal Document.pdf>)**：Abstract、Introduction、Related Work、Deep Research、Proposed Scheme、References。
- **② [Proposal PPT](<Proposal doc/Proposal PPT.pdf>)**：完整呈現研究動機、文獻、Research Gap、Agent Design、Architecture、Flowchart、Pseudocode。
- **③ [GitHub Repository](./)**：正式專題 Repository：`marukomaru777/Restaurant-Bus-Pair-Recommendation`。
- **④ [DESIGN.md](DESIGN.md)**：從 Proposal 階段開始建立並持續維護系統設計文件。

## 專案簡介

Restaurant-Bus-Pair-Recommendation 是物聯網應用與資料分析課程專題。系統先將約會、慶生、朋友聚餐等需求與餐廳評論語意對齊，找出候選餐廳，再分析臺中公車的步行、候車、乘車與轉乘條件，選出情境合適且方便前往的餐廳。

最終推薦單位是餐廳。交通方案參與餐廳的篩選與排序，每間餐廳附上評論依據、建議公車方案、判定結果及未知項。

## 核心流程

1. 理解需求並確認情境、出發地、時間與必要條件。
2. 從評論與有來源的描述召回餐廳，按餐廳去重。
3. 為候選餐廳取得公車方案，建立交通與用餐時間線。
4. 以通過、不通過、不確定三值查核預算、營業與搭乘條件。
5. 每間餐廳保留合適路線，再對不同餐廳排序，輸出最多三間。
6. 依來源與判定紀錄說明推薦理由，未知項另列。

初版聚焦單次查詢。行程中監控、延誤重規劃及回程檢查為後續擴充。

## 論文連結

- [Overleaf 線上檢視](https://www.overleaf.com/read/dvdycnsdfbhd#adf99d)

## 專案內容

| 路徑                                                                             | 說明                                     |
| ------------------------------------------------------------------------------ | -------------------------------------- |
| [DESIGN.md](DESIGN.md)                                                         | 自 Proposal 階段開始維護的系統設計、資料模型、規則、決策與未決事項 |
| [latex_doc/](latex_doc/)                                                       | 已同步修訂的正式提案 LaTeX，主文件載入摘要與第一至四章         |
| [Proposal doc/Proposal Document.pdf](<Proposal doc/Proposal Document.pdf>) | Proposal 正式文件 |
| [Proposal doc/Proposal PPT.pdf](<Proposal doc/Proposal PPT.pdf>) | 19 頁簡報 PDF，含頂端章節標籤、文獻、架構、流程與具行號演算法 |
| [Proposal doc/Proposal Revision.md](<Proposal doc/Proposal Revision.md>)       | 前期修訂文稿，保留作為修訂過程的參考；本輪後續勘誤已直接同步正式 LaTeX |
| [latex_doc/abs/](latex_doc/abs/)                                               | 中文與英文摘要；英文摘要是否顯示依主檔設定                  |
| [latex_doc/chapters/](latex_doc/chapters/)                                     | 各章正文與共用欄位、書目順序設定                       |
| [latex_doc/tables/](latex_doc/tables/)                                         | 文獻、資料來源、三值及領域推理問題等表格                   |
| [latex_doc/figures/](latex_doc/figures/)                                       | 原生 TikZ 架構與流程圖，及架構 PNG                 |
| [latex_doc/alg/](latex_doc/alg/)                                               | 具行號的核心演算法                              |
| [latex_doc/bib/](latex_doc/bib/)                                               | 書目資料與原模板書目設定                           |

尚未建立獨立的 `specs/spec.md`。`latex_doc/README.md` 是原論文模板的使用說明。

## 文件分工

| 文件 | 回答什麼 | 維護原則 |
|---|---|---|
| 論文 | 為什麼做、相關研究、研究問題與方法 | 研究內容大幅修訂先確認文稿，再同步 LaTeX；本輪已授權的勘誤直接修正 |
| `DESIGN.md` | 系統怎麼設計、理由、判定規則、決策與未決項 | 系統行為與設計決策以此為主要依據；矛盾時回報並釐清 |
| 簡報 | 用非本科生也能理解的方式呈現研究故事與設計 | 與論文、設計文件同步，保留示例與研究結果的區別 |
| README | 文件入口、專案範圍、使用方式與實際進度 | 文件或階段改變時更新 |
| 未來開發規格 | 技術棧、欄位、模組介面與實作驗收 | 建立後須與 `DESIGN.md` 一致，不把尚未決定事項寫成定案 |

## 資料來源

| 用途 | 預計來源與狀態 |
|---|---|
| 評論與情境語意 | 正式來源與可使用範圍待確認；YouTube 逐字稿與留言可作補充，須區分文字類型 |
| 價格、營業、分店 | 店家官方資訊與必要人工核對 |
| 餐廳座標 | 可追溯的位置資料或現場核對，Place ID 本身不能代替座標 |
| 地點對應 | Places API，現階段規劃只持久保存 Place ID |
| 公車方案 | TDX 公共運輸旅運規劃 |
| 即時到站與狀態 | TDX 公車預估到站 N1 |
| 站位、方向、服務日、班表與站間時間 | TDX 公車資料，實際欄位及版本待介接驗證 |

來源與時間欄位的要求見 [DESIGN.md §4](DESIGN.md#4-資料來源與使用邊界) 及 §11。來源入口：[TDX 旅運規劃](https://tdx.transportdata.tw/api-service/swagger/maas/4513f9d6-caae-4cf7-a50c-e7887bec804e)、[TDX 公車](https://tdx.transportdata.tw/api-service/swagger/basic/2998e851-81d0-40f5-b26d-77e2f5ac4118)、[Places API 政策](https://developers.google.com/maps/documentation/places/web-service/policies)。

Google 評論不預設為可大量保存的向量語料。影片發布時間、來源更新或觀測時間與系統取得時間分開保存。上述來源為設計規劃，尚非已完成介接。

## 修改時要一起更新的地方

以下論文路徑均位於 `latex_doc/`。

| 改了什麼 | 一併檢查 |
|---|---|
| 目標、範圍與排名單位 | `DESIGN.md` §1–2、README、`abs/`、第一／四章、簡報 |
| 資料來源、API 與時間欄位 | `DESIGN.md` §4、§6、§11；第四章、`ch4_data_model_entities.tex`、書目及簡報來源頁 |
| 預算、營業、步行與搭乘規則 | `DESIGN.md` §7–8、§15；第四章式 4.1–4.3、三值表、演算法、流程及示例 |
| 排序、尺度與權重 | `DESIGN.md` §9、§15–16；第四章式 4.4、演算法及簡報排序頁 |
| 模組與架構 | `DESIGN.md` §5、§10；第四章、架構 TikZ／PNG、流程圖及簡報 |
| 文獻資料或研究限制 | 第二／三章、`ch2_article_summary.tex`、`thesis.bib`、簡報文獻與講者備註 |
| 書目語言順序或引用 | `chapters/proposal_macros.tex` 的 `nocite`、正文 `[x]`、文獻表與簡報來源編號 |
| 未決事項定案 | `DESIGN.md` §15 新增決策，更新 §16 狀態，再同步受影響內容 |
| 設計文件內容 | 每次於 `DESIGN.md` §17 新增變更紀錄，註明論文及簡報是否需同步 |
| 階段、摘要或預期成果 | README 狀態、`abs/`、第一／四章與簡報 |

架構圖主流程統一由左至右。論文目前直接載入 TikZ，PNG 為同步預覽。主檔尚未載入的第五、六章及舊表格不得當成本次正式提案內容。

## 撰寫與引用規則

- 論文引用限 ACL、EMNLP／NAACL、NeurIPS、ICML、ICLR、AAAI、IJCAI 與 IEEE 期刊／會議；政府資料、新聞、資料集及適用官方技術文件可保留。正文不交代此篩選規則。
- 正文以 `[x]` 數字引用，文末中文文獻在前、英文文獻在後；透過引用鍵維持對應，不手寫固定編號。
- 文獻表 Limitation 描述原論文的方法、資料或驗證限制；本專題差異放在研究缺口。取得全文後更新先前「不足以判斷」的項目。
- 分析架構用於組織推理，正式正文採連貫文獻論證，不直接搬用「觀點 A／B、Evidence、Consensus」等寫作提示標籤。
- 年份採西元，圖、表與式使用 `4.1` 等點號格式。
- 不虛構數據、來源、作者或結果；資訊不足時如實說明。
- 實驗尚未執行，預期成果與示例不可寫成實驗結論；本輪不新增評估計畫及研究限制章節。
- 餐費中點只供顯示與評分，硬預算依區間查核；最後點餐未知時沿用用餐結束不晚於打烊並揭露未確認。變更前先於 `DESIGN.md` §15 新增決策。

## LaTeX 與編譯

主檔：[latex_doc/main.tex](latex_doc/main.tex)。使用者以 Overleaf 編譯；保留原主檔、模板與字型設定。

LaTeX 修改範圍限 `abs/`、`alg/`、`bib/`、`chapters/`、`figures/`、`tables/`，沿用原本風格。本次另依要求更新根目錄 README、建立 `DESIGN.md` 及簡報輸出。

## 狀態

目前處於 Proposal 階段。摘要及第一至四章已同步 LaTeX，文獻限制已核對，第三章改採正式論述，架構主流程已改為由左至右。簡報提供 19 頁 PDF，`DESIGN.md` 自本階段開始維護。

尚未實作系統、尚未執行實驗。正式評論來源、TDX 實際回應、技術棧、參數、權重、緩衝及部分輸入定義仍待確認，詳見 [DESIGN.md §16](DESIGN.md#16-待確認事項)。文件中的示例與計畫值均不代表實測成果。
