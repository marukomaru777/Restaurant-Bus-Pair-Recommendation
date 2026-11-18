"""說明欄解析與地址轉座標，給 2_餐廳抽取.ipynb 的最後一步用。

    python places.py selftest     # 說明欄解析檢查，不連網

多數美食頻道會在說明欄列「店名／📍地址／⏰營業時間」，比逐字稿可靠，
所以營業時間與地址以說明欄為準（觀測時間＝影片發布日）。
地址轉座標用 TDX GeoCode（金鑰同樣在 repo 根目錄 .env）。
ponytail: 說明欄沒列地址的店拿不到座標，之後依 DESIGN.md §9.2-5 改用 Places。
"""
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "tdx")]

WEEK = "一二三四五六日"
ADDR_MARK = ("📍", "🏠")
RANGE = re.compile(r"(\d{1,2}:\d{2})\s*[~～–—\-－]\s*(\d{1,2}:\d{2})")


def parse_description(desc):
    """找「店名行 + 📍/🏠 地址行 + 營業時間」的區塊。要用爬蟲的原始說明（清洗版會刪掉 #店名）。"""
    lines = [l.strip() for l in (desc or "").splitlines()]
    shops = []
    for i, line in enumerate(lines):
        if not line.startswith(ADDR_MARK) or i == 0:
            continue
        name = re.sub(r"[^\w ]", "", lines[i - 1]).strip()  # 去掉 emoji、#、｜
        block = []
        for l in lines[i + 1:]:
            if not l or l.startswith(ADDR_MARK) or set(l) <= set("-—"):
                break
            block.append(l)
        text = " ".join(block)
        closed = set()
        for m in re.finditer(rf"(?:星期)?([{WEEK}.、]+)公?休", text):
            closed |= {WEEK.index(c) for c in m.group(1) if c in WEEK}
        shops.append({"name": name, "address": line.lstrip("".join(ADDR_MARK)).strip(),
                      "hours": [list(r) for r in RANGE.findall(text)] or None,
                      "closed_weekdays": sorted(closed)})
    return shops


def geocode(address, cache_file):
    """TDX 地址轉座標，結果快取在 cache_file（同一地址不重查）。失敗回傳 None。"""
    cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    if address not in cache:
        import tdx
        status, text = tdx.call("/advanced/V3/Map/GeoCode/Coordinate/Address/" + urllib.parse.quote(address), format="JSON")
        time.sleep(tdx.INTERVAL)  # 免費方案每分鐘 5 次
        m = re.search(r"POINT \(([\d.]+) ([\d.]+)\)", text) if status == 200 else None
        cache[address] = [float(m.group(2)), float(m.group(1))] if m else None
        cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return cache[address]


def selftest():
    desc = ("｜#天津苟不理湯包 ｜\n🏠台中市東區信義街63號\n⌚️05:30~11:30\n🚫星期一公休 \n-\n"
            "🍳TAKU 牛丼專賣\n📍台中市西區民生北路105號\n⏰11:30 - 14:00\n      17:30 - 21:00 \n      日一休\n☎️0423058199\n\n"
            "🍳卷卷卷-肉桂捲專賣店\n📍台中市西區樂群街49號\n⏰07:30–12:00一.二休\n\n"
            "🍳向上水餃\n📍台中市西區中美街183號\n⏰10:30–22:00無休\n")
    s = parse_description(desc)
    assert [x["name"] for x in s] == ["天津苟不理湯包", "TAKU 牛丼專賣", "卷卷卷肉桂捲專賣店", "向上水餃"], s
    assert s[0]["hours"] == [["05:30", "11:30"]] and s[0]["closed_weekdays"] == [0]
    assert s[1]["hours"] == [["11:30", "14:00"], ["17:30", "21:00"]] and s[1]["closed_weekdays"] == [0, 6]
    assert s[2]["closed_weekdays"] == [0, 1] and s[3]["closed_weekdays"] == []
    assert parse_description(None) == []
    print("selftest ok")


if __name__ == "__main__":
    selftest()
