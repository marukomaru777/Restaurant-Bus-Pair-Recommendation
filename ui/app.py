"""臺中餐廳＋公車推薦：Streamlit 介面。

執行（在 repo 根目錄）：
    streamlit run ui/app.py
資料來源可在側邊欄切換：mock（ui/mock_result.json）或 API（api/server.py）。
轉換規則與 relevance 分級見 ui/README.md。
"""
import html
from datetime import datetime, time, timedelta

import streamlit as st

import backend
from backend import ApiError

st.set_page_config(page_title="臺中餐廳＋公車推薦", page_icon="🚌", layout="wide")

CONTEXTS = ["約會", "慶生", "朋友聚餐", "家庭聚餐", "商務", "一個人"]  # DESIGN §9.1
PRESET_ORIGINS = {
    "臺中車站": (24.1372, 120.6869),
    "勤美誠品": (24.1510, 120.6635),
    "逢甲夜市": (24.1797, 120.6462),
}
STATE_STYLE = {  # 顏色 + 字母，不只靠顏色
    "T": ("#1a7f37", "rgba(26,127,55,.15)"),
    "F": ("#cf222e", "rgba(207,34,46,.15)"),
    "U": ("#9a6700", "rgba(212,167,44,.22)"),
}
SKIP_STYLE = ("#6e7781", "rgba(110,119,129,.15)")

st.markdown(
    """
<style>
.badge{display:inline-block;padding:2px 10px;margin:0 6px 4px 0;border-radius:12px;
  font-size:.85rem;font-weight:600;border:1px solid}
.quote{border-left:3px solid #8884;padding:2px 12px;margin:6px 0}
.quote.neg{border-left-color:#cf222e}
.tag{display:inline-block;padding:0 8px;margin-right:6px;border-radius:8px;font-size:.75rem;
  background:#8882;border:1px solid #8884}
.meta{font-size:.8rem;opacity:.7}
.tl{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:6px 0}
.chip{padding:3px 10px;border-radius:8px;background:#8881;border:1px solid #8883;font-size:.9rem}
.chip.bus{background:rgba(9,105,218,.12);border-color:rgba(9,105,218,.4)}
.arrow{opacity:.5}
</style>
""",
    unsafe_allow_html=True,
)


def esc(x):
    return html.escape(str(x))


def badge(state, text, skipped=False):
    if skipped:
        fg, bg = SKIP_STYLE
        return f'<span class="badge" style="color:{fg};background:{bg};border-color:{fg}">{esc(text)} 未查</span>'
    fg, bg = STATE_STYLE.get(state, STATE_STYLE["U"])
    return f'<span class="badge" style="color:{fg};background:{bg};border-color:{fg}">{esc(text)} {esc(state)}</span>'


def badges(checks):
    return "".join(badge(c["state"], c["label"], c["skipped"]) for c in checks)


def safe_url(url):
    """只允許 http(s) 連結，避免 javascript: 之類的網址。"""
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        return url.replace(" ", "%20").replace(")", "%29").replace("(", "%28")
    return None


# ---------------- 結果卡片 ----------------
def timeline_html(route):
    parts = []
    for s in route["sections"]:
        if s["type"] == "bus":
            parts.append(f'<span class="chip bus">🚌 {esc(s["bus"] or "公車")} · {s["minutes"]} 分</span>')
        else:
            parts.append(f'<span class="chip">🚶 {s["minutes"]} 分</span>')
    parts.append('<span class="chip">🍽 用餐</span>')
    return '<div class="tl">' + '<span class="arrow">▶</span>'.join(parts) + "</div>"


def render_route(route):
    if not route:
        st.caption("🚌 未取得公車方案")
        return
    leave = f" → {route['leave']} 離店" if route["leave"] else ""
    st.markdown(f"**🚌 {route['start']} 出發 → {route['arrive']} 到店{leave}**")
    st.markdown(timeline_html(route), unsafe_allow_html=True)
    for s in route["sections"]:
        if s["type"] == "bus":
            where = f"，往{s['headsign']}" if s["headsign"] else ""
            st.caption(f"{s['start']} 搭 {s['bus']}{where}：{s['from']} → {s['to']}")
    fare = f"票價 {route['fare']} 元" if route.get("fare") is not None else "票價未知"
    st.caption(f"{route['transfers']} 次轉乘 · {fare} · 全程 {route['travel_min']} 分")


def render_evidence(item):
    if not item["evidence"]:
        st.caption("沒有評論依據（店名符合情境）")
        return
    tag = f'<span class="tag">{esc(item["evidence_aspect"])}｜{esc(item["evidence_tag"])}</span>' if item["evidence_tag"] else ""
    st.markdown(f'<div class="quote">{tag}「{esc(item["evidence"])}」</div>', unsafe_allow_html=True)
    if item["counter_evidence"]:
        with st.expander(f"反證（{len(item['counter_evidence'])}）"):
            for c in item["counter_evidence"]:
                st.markdown(f'<div class="quote neg">「{esc(c)}」</div>', unsafe_allow_html=True)


def render_sources(sources):
    for i, s in enumerate(sources, 1):
        url = safe_url(s.get("video"))
        how = s.get("transcript_source") or "來源未標示"
        when = s.get("published_at") or "發布時間未知"
        link = f"[看原影片 {i}]({url})" if url else f"影片 {i}"
        st.caption(f"{link} · {how} · {when}")


def render_item(item, rank=None, compact=False):
    with st.container(border=True):
        head, level = st.columns([4, 1])
        head.markdown(f"#### {str(rank) + '　' if rank else ''}{item['name']}")
        if item["address"]:
            head.caption(item["address"])
        level.markdown(f"<div style='text-align:right' class='meta'>情境符合度<br><b>{item['level']}</b></div>",
                       unsafe_allow_html=True)
        if item["explanation"]:
            st.markdown(item["explanation"])
            st.caption("AI 撰寫，數字、時間與引文已由程式核對")
        render_evidence(item)
        if compact:
            rt = item["route"]
            if rt:
                st.caption(f"🚌 {rt['start']} 出發 → {rt['arrive']} 到店（{rt['transfers']} 次轉乘）")
            else:
                st.caption("🚌 未取得公車方案")
        else:
            render_route(item["route"])
        # checks 用迴圈渲染，不寫死項目
        st.markdown(badges(item["checks"]), unsafe_allow_html=True)
        render_sources(item["sources"])
        # 有未知項時，警示框已經把原因講完；再放「看原因」會重複同一件事
        if item["unknowns"]:
            for u in item["unknowns"]:
                st.warning(f"未知：{u}", icon="⚠️")
        else:
            with st.expander("看原因"):
                for c in item["checks"]:
                    st.markdown(badge(c["state"], c["label"], c["skipped"]) + f" {esc(c['reason'])}", unsafe_allow_html=True)


def render_rejected(item):
    with st.container(border=True):
        st.markdown(f"**{item['name']}**")
        for c in item["checks"]:
            if c["state"] == "F":
                st.markdown(badge(c["state"], c["label"]) + f" {esc(c['reason'])}", unsafe_allow_html=True)
        # 被淘汰的店，其餘項目多半只是沒必要再查；不當成「不確定」顯示
        skipped = [c["label"] for c in item["checks"] if c["skipped"]]
        if skipped:
            st.caption("未查：" + "、".join(skipped) + "（已有條件不符，不再查詢）")


# ---------------- 左欄：輸入 ----------------
def _pick_preset():
    name = st.session_state["preset"]
    if PRESET_ORIGINS.get(name):
        st.session_state["origin"] = PRESET_ORIGINS[name]
        st.session_state["origin_label"] = name
        st.session_state["view"] = {"center": list(PRESET_ORIGINS[name]), "zoom": 15}  # 選地點時視角跟過去
        st.session_state["map_ver"] = st.session_state.get("map_ver", 0) + 1  # 換 key，丟掉舊地圖回報的視角
        st.session_state["last_click"] = None


def _center_on_fullscreen_cls():
    from branca.element import MacroElement
    from jinja2 import Template

    class CenterOnFullscreen(MacroElement):
        """進入與離開全螢幕時都把地圖中心移到出發地標記。
        標記位置在執行時才從圖層讀取，因此地圖的 HTML 不隨標記改變，不會觸發重建。"""
        _template = Template("""
        {% macro script(this, kwargs) %}
        (function () {
          var map = {{ this._parent.get_name() }};
          map.on('enterFullscreen exitFullscreen', function () {
            setTimeout(function () {
              map.invalidateSize();
              map.eachLayer(function (l) {
                if (l instanceof L.Marker) { map.setView(l.getLatLng(), map.getZoom(), {animate: false}); }
              });
            }, 200);
          });
        })();
        {% endmacro %}
        """)

    return CenterOnFullscreen


def origin_picker():
    """地圖點選出發地。選取結果存在 session_state，不放進 form（地圖元件不適合在 form 內）。"""
    import folium
    from folium.plugins import Fullscreen
    from streamlit_folium import st_folium

    ss = st.session_state
    ss.setdefault("origin", PRESET_ORIGINS["臺中車站"])
    ss.setdefault("origin_label", "臺中車站")
    ss.setdefault("last_click", None)

    st.selectbox("快速選擇", list(PRESET_ORIGINS), key="preset", on_change=_pick_preset, index=0)
    lat, lng = ss["origin"]
    # 每次重跑都會重建地圖：視角（中心、縮放）要自己記住，否則點擊後會跳回初始大小
    view = ss.setdefault("view", {"center": [lat, lng], "zoom": 15})
    # Esri World Street Map：近 Google 的街道風格，免金鑰（Carto 已改為需金鑰）；須標示來源
    m = folium.Map(location=view["center"], zoom_start=view["zoom"], control_scale=True, tiles=None)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ, HERE, OpenStreetMap contributors",
        max_zoom=19,
    ).add_to(m)
    Fullscreen(position="topright").add_to(m)
    _center_on_fullscreen_cls()().add_to(m)
    # 標記放在 feature group：換出發地時只更新標記，不重建地圖，使用者的縮放／拖曳才不會被重設。
    # 只回報 last_clicked：若連 zoom／center 也回報，每次縮放都會觸發重跑再重建地圖，造成抖動。
    marker = folium.FeatureGroup(name="origin")
    folium.Marker([lat, lng], tooltip="出發地", icon=folium.Icon(color="red", icon="map-pin", prefix="fa")).add_to(marker)
    out = st_folium(m, feature_group_to_add=marker, height=380, use_container_width=True,
                    key=f"map{ss.get('map_ver', 0)}", returned_objects=["last_clicked"])
    click = out.get("last_clicked") if out else None
    # 只處理「新的」點擊，避免舊點擊蓋掉快速選擇
    if click and click != ss["last_click"]:
        ss["last_click"] = click
        ss["origin"] = (round(click["lat"], 5), round(click["lng"], 5))
        ss["origin_label"] = "地圖選取"
        st.rerun()
    st.caption(f"📍 {ss['origin_label']}：{ss['origin'][0]}, {ss['origin'][1]}（點地圖可更換）")
    return ss["origin"][0], ss["origin"][1], ss["origin_label"]


def build_query():
    d = backend.default_query()
    errors = []
    st.subheader("① 你想怎麼吃？")
    context = st.pills("情境", CONTEXTS, default=d["context"], selection_mode="single")
    note = st.text_input("補充偏好（選填）", placeholder="例如：想要有包廂")
    if note:
        st.caption("目前後端只用上面的情境標籤，補充偏好尚未送出。")

    st.subheader("② 從哪裡出發？")
    lat, lng, place = origin_picker()
    c1, c2 = st.columns(2)
    day = c1.date_input("出發日期", value=(datetime.now() + timedelta(days=1)).date())
    tm = c2.time_input("出發時間", value=time(19, 0), step=300)

    st.subheader("③ 預算")
    c1, c2 = st.columns([1, 1])
    amount = c1.number_input("金額（元）", min_value=0, value=d["budget"], step=50)
    unit_label = c2.radio("單位", ["每人", "整團"], horizontal=True)
    party = None
    if unit_label == "整團":
        party = st.number_input("人數", min_value=1, value=2, step=1)
        st.caption("後端只收每人預算，會換算後送出。")

    with st.expander("進階設定"):
        walk = st.number_input("單段步行上限（分）", min_value=1, max_value=30, value=10)
        meal_given = st.checkbox("自己指定用餐時長", value=False)
        meal = st.number_input("用餐時長（分）", min_value=10, max_value=300, value=90, step=15, disabled=not meal_given)
        k = st.number_input("召回家數", min_value=1, max_value=10, value=5,
                            help="先依情境挑幾家再查交通；真的查 TDX 時每家約 13 秒")

    if not context:
        errors.append("請選擇情境")
    if amount <= 0:
        errors.append("預算需大於 0")

    query = {
        "context": context,
        "context_note": note or None,
        "origin": {"lat": lat, "lng": lng, "label": place},
        "depart": datetime.combine(day, tm).strftime("%Y-%m-%dT%H:%M"),
        "budget": {"amount": amount, "unit": "per_person" if unit_label == "每人" else "group",
                   **({"party_size": party} if party else {})},
        "walk_max_min": walk,
        "meal_min": meal if meal_given else None,
        "k": k,
    }
    return query, errors


# ---------------- 右欄：結果 ----------------
def render_result(res):
    for n in res["notes"]:
        st.info(n, icon="ℹ️")
    if res["derived"]:
        st.caption(f"（開發提醒：此為推導樣本，非實測。{res['derived']}）")

    if res["status"] == "no_candidates":
        st.warning(res["empty_reason"] or "沒有情境相符的餐廳。")
        return

    g = res["groups"]
    rec, unc, rej = g["recommended"], g["uncertain"], g["rejected"]
    st.markdown(f"**{len(rec)} 間推薦 · {len(unc)} 間不確定 · {len(rej)} 間不通過**")
    if not rec:
        st.warning("沒有全部條件通過的餐廳，系統不會自行放寬條件。")

    for i, item in enumerate(rec, 1):
        render_item(item, rank=i)
    if unc:
        with st.expander(f"不確定：請自行確認（{len(unc)}）", expanded=not rec):
            for item in unc:
                render_item(item, compact=True)
    if rej:
        with st.expander(f"不通過（{len(rej)}）"):
            for item in rej:
                render_rejected(item)


def main():
    st.title("🚌 臺中餐廳＋公車推薦")
    st.caption("研究原型：店家資料目前是示意資料，路線在離線模式下也不是真的。")

    with st.sidebar:
        st.markdown("**開發用**")
        source_label = st.radio("資料來源", ["Mock 資料", "API"])
        source = "mock" if source_label == "Mock 資料" else "api"
        scenario, base_url, offline = "all_kinds", backend.DEFAULT_API, True
        if source == "mock":
            scenario = st.selectbox("Mock 情境", backend.scenario_names(),
                                    help="all_kinds／budget_low／no_candidates 為實測；tdx_429／rich 為推導")
        else:
            base_url = st.text_input("API 位址", value=backend.DEFAULT_API)
            offline = st.checkbox("離線模式（不查 TDX）", value=True,
                                  help="關閉會真的查 TDX：每家候選約 13 秒，且出發時間必須晚於現在")
            if not offline:
                st.warning("真的查 TDX，請耐心等候；免費額度每分鐘 5 次。")

    left, right = st.columns([1, 2], gap="large")
    with left:
        query, errors = build_query()
        submitted = st.button("開始推薦", use_container_width=True, type="primary")
    with right:
        if submitted:
            if source == "api" and not offline and datetime.fromisoformat(query["depart"]) <= datetime.now():
                errors.append("出發時間要晚於現在（TDX 不收過去的時間）")
            if errors:
                st.session_state.pop("result", None)
                st.session_state.pop("error", None)
                for e in errors:
                    st.error(e)
            else:
                st.session_state.pop("error", None)
                try:
                    with st.spinner("正在查詢…（真的查 TDX 時每家店約 13 秒）"):
                        st.session_state["result"] = backend.get_recommendations(
                            query, source=source, scenario=scenario, base_url=base_url, offline=offline)
                except ApiError as e:
                    st.session_state.pop("result", None)
                    st.session_state["error"] = e
        if st.session_state.get("error"):
            e = st.session_state["error"]
            st.error(e.message, icon="🚫")
            if e.status == 429:
                st.caption("超過每分鐘 5 次，稍後重試。")
        elif st.session_state.get("result"):
            render_result(st.session_state["result"])
        elif not submitted:
            st.info("在左側填寫需求後按「開始推薦」。")


main()
