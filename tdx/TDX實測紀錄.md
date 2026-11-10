# TDX API 實測紀錄（回應 DESIGN.md O002）

- 實測日期：2026-10-21 晚上約 20:00–20:25（週三）
- 帳號方案：TDX 基礎會員（免費，3 點/月，5 次/分/金鑰）
- 程式：`tdx.py probe`，回應樣本存在 `samples/`
- 測試對象：台中路線 300；路線規劃起訖點為台中車站 (24.1372, 120.6869) → 勤美誠品 (24.1510, 120.6635)

## 1. 結果總覽

| API | 端點 | 結果 |
|---|---|---|
| 公車到站預估 (N1) | `/api/basic/v2/Bus/EstimatedTimeOfArrival/City/Taichung/{路線}` | ✅ 200 |
| 路線站序 | `/api/basic/v2/Bus/StopOfRoute/City/Taichung/{路線}` | ✅ 200 |
| 班表 | `/api/basic/v2/Bus/Schedule/City/Taichung/{路線}` | ✅ 200 |
| 公共運輸路線規劃 | `/api/maas/routing` | ✅ 200（修正兩個參數問題後） |

## 2. 公車到站預估 (N1)

主要欄位：`StopUID`、`StopName`、`Direction`、`StopSequence`、`EstimateTime`、`StopStatus`、`NextBusTime`、`PlateNumb`、`Estimates[]`、`SrcUpdateTime`、`UpdateTime`

| 發現 | 對設計的影響 |
|---|---|
| `EstimateTime` 是**倒數秒數**（如 600 = 10 分鐘後），不是絕對時間 | 必須搭配可信的參考時間換算，印證 DESIGN.md「ETA 需要可信參考時間」 |
| 有兩個時間戳：`SrcUpdateTime`（業者端）與 `UpdateTime`（TDX 端），樣本相差約 19 秒 | 可量測資料延遲，作為 O007 TTL 的依據（待蒐集資料後統計） |
| `NextBusTime` 與 `EstimateTime` **對不起來**：同一站倒數 600 秒（約 20:05），`NextBusTime` 為 20:45 | 兩欄位語意不同，不可混用；`NextBusTime` 的確切語意待確認 |
| `Estimates[]` 附接下來 2–8 班車的車牌與各自倒數秒數 | 可依車牌追蹤同一台車，計算「預估 vs 實際」到站誤差（O008 緩衝時間的依據） |

## 3. 班表

- 路線 300 共 41 筆班次（`Timetables`），每筆有 `ServiceDay`（星期幾行駛）。
- **每個班次只有起點站的發車時間**（`StopTimes` 只有 1 筆），沒有中途各站的表定到站時間。
- 影響：中途站的表定時間要自己推估（例如起站時間加站間行駛時間）。這是 O002「班次識別能力」的限制。

## 4. 公共運輸路線規劃（MaaS routing）

參數實測：
- **不接受 `$format` 參數**（回 400：`"$format" is not allowed`），與 basic API 不同。
- **`depart` 不可早於送出當下**（回 400：`The depart time before now!`）。
- 本次使用：`origin`、`destination`、`gc=1.0`、`top=1`、`transit=5`、`depart`。

回應結構：`routes[]` → `travel_time`（秒）、`start_time`、`end_time`、`transfers`、`total_price`、`sections[]`。每段 `section` 有 `type`（`drive` / `transit`）、出發與抵達的時間地點、`transport`（路線名稱、票價等）、`intermediateStops[]`（中途站時間）。

| 發現 | 對設計的影響 |
|---|---|
| ⚠️ **沒帶接駁參數時，第一哩與最後一哩實際給「YOXI 計程車」**，與官方文件「預設走路」不符。本次樣本最後一段是搭計程車 1.1 公里（87 秒） | 直接用預設參數的話，「步行上限」這個硬限制會被繞過。必須明確帶步行參數，見 4.1 |
| 中途站時間都是整分鐘（20:30、20:31…） | 看起來是依班表推算，不是即時資料；是否參考即時車況待確認 |
| 回傳票價（`fare`、`total_price`，本次 18 元） | 可直接作為交通費用欄位 |

### 4.1 指定步行接駁（2026-11-06 實測，`tdx.py probe walk`）

官方 OAS 文件列出的接駁參數：`first_mile_mode`／`last_mile_mode`（0 走路、1 腳踏車、2 開車、3 共享單車）、`first_mile_time`／`last_mile_time`（可接受分鐘數，預設 10，上限 60）、`transfer_time`（轉乘時間範圍 `{min},{max}`，預設 15,60）。

同一起訖點、同一時段對照：

| 設定 | 第一哩 | 公車 | 最後一哩 | 總時間 |
|---|---|---|---|---|
| 不帶接駁參數 | YOXI 219 m／17 秒 | 11 分 | YOXI 1.66 km／132 秒 | 13.5 分 |
| `first_mile_mode=0, last_mile_mode=0`、各 10 分，`gc=1.0` | 步行 107 m／77 秒 | 14 分 | 步行 688 m／8 分 15 秒 | 23.5 分 |
| 同上，`gc=0.0` | 結果與上一列相同 | | | |

- 結論：**一定要明確帶 `first_mile_mode=0`、`last_mile_mode=0`**，回傳的 section `type` 才會是 `pedestrian`。計程車跟 `gc` 無關。
- `first_mile_time`、`last_mile_time` 可以直接對應使用者的步行上限。
- 系統仍應檢查每個 section 的 `type`，出現 `drive` 就判步行條件不通過，不要只信任參數。

### 4.2 計費

官方 OAS 文件寫路線規劃「計次：不計入、計量：不計入」，也就是呼叫不扣點，只受每分鐘 5 次的頻率限制。

## 5. 待確認

1. ~~路線規劃指定步行的參數~~ → 已解決，見 4.1。
2. ~~路線規劃的服務級別與扣點~~ → 文件寫不計入，見 4.2（可再到會員中心「使用統計」對照確認）。
3. `NextBusTime` 的確切語意。
4. 資料延遲的分布（需用 `tdx.py collect` 蒐集數晚資料後統計）。
