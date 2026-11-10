"""分析 collect 蒐集的到站預估：資料延遲，以及「預估 vs 實際」到站誤差。

用法：
    python analyze.py data/eta_*.jsonl      # 印出統計表，並輸出 errors.csv
    python analyze.py selftest              # 用假資料檢查計算邏輯

方法：
- 預估到站時刻 = SrcUpdateTime + EstimateTime（倒數秒數）
- 依 (車牌, 路線, 方向, 站) 追蹤同一台車對同一站的一連串預估
- 實際到站時刻 ≈ 這台車最後一次出現在該站時的預估到站時刻，
  而且只採用最後一次預估 <= 90 秒的（代表確實快到了，不是資料中斷）
- 誤差 = 預估到站 − 實際到站（正值：預估比實際晚，也就是車早到）
ponytail: 實際到站用「最後一筆預估」近似，解析度約 ±1 分鐘（受 1 分鐘抓取間隔限制）；
要更準需改用公車即時位置 (RealTimeNearStop) 的到站事件。
"""
import csv
import glob
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta

ARRIVE_MAX = 90                      # 最後一次預估要 <= 90 秒才算「確實到站」
BINS = [(0, 5), (5, 10), (10, 20), (20, 30), (30, 60)]   # 預估提前量（分鐘）


def ts(s):
    return datetime.fromisoformat(s).replace(tzinfo=None)


def load(paths):
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r["status"] == 200:
                    yield r


def observations(records):
    """展開成 (key, 觀測時刻, 預估秒數)；key = (車牌, 路線, 方向, 站)。"""
    for r in records:
        for row in r["data"]:
            src = ts(row["SrcUpdateTime"])
            for e in row.get("Estimates") or []:
                if e.get("EstimateTime") is None or not e.get("PlateNumb"):
                    continue
                key = (e["PlateNumb"], r["route"], row["Direction"], row["StopUID"])
                yield key, src, e["EstimateTime"]


def errors(obs):
    """回傳 [(提前量分鐘, 誤差秒, key)]。"""
    series = defaultdict(dict)
    for key, src, est in obs:
        series[key][src] = est          # 同一個 SrcUpdateTime 重複抓到只算一次
    out = []
    for key, s in series.items():
        pts = sorted(s.items())
        last_t, last_est = pts[-1]
        if last_est > ARRIVE_MAX:
            continue                    # 沒看到快到站就消失，可能是資料中斷，不採用
        actual = last_t + timedelta(seconds=last_est)
        for t, est in pts[:-1]:
            out.append((est / 60, (t + timedelta(seconds=est) - actual).total_seconds(), key))
    return out


def latency(records):
    """每次抓取時，資料距離業者更新、TDX 更新各多久（秒）。"""
    src, upd = [], []
    for r in records:
        f = ts(r["fetched_at"])
        src.append((f - max(ts(x["SrcUpdateTime"]) for x in r["data"])).total_seconds())
        upd.append((f - max(ts(x["UpdateTime"]) for x in r["data"])).total_seconds())
    return src, upd


def q(xs, p):
    return statistics.quantiles(xs, n=100)[p - 1] if len(xs) > 1 else xs[0]


def report(paths):
    records = list(load(paths))
    if not records:
        sys.exit("沒有可用的資料")
    print(f"抓取次數 {len(records)}：{records[0]['fetched_at']} → {records[-1]['fetched_at']}")
    src, upd = latency(records)
    print(f"資料延遲（中位數）：業者更新→抓取 {statistics.median(src):.0f} 秒，"
          f"TDX 更新→抓取 {statistics.median(upd):.0f} 秒")

    errs = errors(observations(records))
    print(f"\n到站誤差（預估 − 實際，秒；正值 = 車比預估早到），樣本 {len(errs)} 筆")
    print(f"{'提前量':>10} {'樣本':>6} {'中位數':>7} {'平均絕對誤差':>10} {'P10':>6} {'P90':>6}")
    for lo, hi in BINS:
        xs = [e for h, e, _ in errs if lo <= h < hi]
        if len(xs) < 2:
            print(f"{lo:>3}–{hi:<3}分鐘 {len(xs):>6}   （樣本不足）")
            continue
        mae = statistics.fmean(abs(x) for x in xs)
        print(f"{lo:>3}–{hi:<3}分鐘 {len(xs):>6} {statistics.median(xs):>7.0f} {mae:>10.0f} "
              f"{q(xs, 10):>6.0f} {q(xs, 90):>6.0f}")

    with open("errors.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["horizon_min", "error_sec", "plate", "route", "direction", "stop_uid"])
        for h, e, key in errs:
            w.writerow([round(h, 1), e, *key])
    print("\n明細已輸出 errors.csv")


def selftest():
    t0 = datetime(2026, 10, 22, 18, 0)

    def rec(minute, est, plate="AAA-1"):
        t = (t0 + timedelta(minutes=minute)).isoformat()
        return {"status": 200, "route": "300", "fetched_at": t,
                "data": [{"Direction": 0, "StopUID": "S1", "SrcUpdateTime": t, "UpdateTime": t,
                          "Estimates": [{"PlateNumb": plate, "EstimateTime": est}]}]}

    # 車子實際 18:10 到站；第 0 分鐘預估 8 分鐘（說早 2 分鐘），第 5 分鐘預估 5 分鐘（準），
    # 第 9 分鐘預估 60 秒（最後一筆，當作實際到站基準）
    data = [rec(0, 480), rec(5, 300), rec(9, 60)]
    errs = sorted(errors(observations(data)))
    assert [(round(h), e) for h, e, _ in errs] == [(5, 0.0), (8, -120.0)], errs
    # 最後一筆預估還很遠就消失 → 不採用
    assert errors(observations([rec(0, 600, "BBB-2"), rec(1, 540, "BBB-2")])) == []
    src, upd = latency(data)
    assert src == [0.0, 0.0, 0.0]
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        selftest()
    elif len(sys.argv) > 1:
        report([p for a in sys.argv[1:] for p in glob.glob(a)])
    else:
        sys.exit(__doc__)
