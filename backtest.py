"""Backtest the screener's scoring: did high-scoring picks actually move up afterward?

Walks data/history_<prefix>.json (built up by screener.py on every run), takes one
scoring "event" per symbol per calendar day, and checks the actual forward return
via yfinance N trading days later. Reports hit-rate and average return by score
bucket, so the scoring weights can eventually be calibrated against real outcomes.

Usage: python backtest.py [--prefix results] [--horizon-days 5] [--min-days-old 5]
"""
import argparse
import datetime
import json
import time

import yfinance as yf

SCORE_BUCKETS = [(0, 30), (30, 60), (60, 1000)]


def load_events(history_path):
    """Return one (symbol, date, score, price_at_signal) per symbol per calendar day."""
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    events = []
    for symbol, points in history.items():
        seen_dates = {}
        for p in points:
            date = p["t"][:10]
            if date not in seen_dates:  # first point of the day = when the signal fired
                seen_dates[date] = p
        for date, p in seen_dates.items():
            if p.get("p"):
                events.append({"symbol": symbol, "date": date, "score": p["s"], "price": p["p"]})
    return events


def forward_return(symbol, signal_date, price_at_signal, horizon_days, pause=0.3):
    """Fetch the close price ~horizon_days trading days after signal_date; return pct change."""
    start = datetime.date.fromisoformat(signal_date)
    end = start + datetime.timedelta(days=int(horizon_days * 1.8) + 3)  # buffer for weekends/holidays
    try:
        hist = yf.Ticker(symbol).history(start=start.isoformat(), end=end.isoformat())
    except Exception:
        return None
    finally:
        time.sleep(pause)
    if hist.empty or len(hist) <= horizon_days:
        return None
    forward_price = float(hist["Close"].iloc[horizon_days])
    if not price_at_signal:
        return None
    return (forward_price - price_at_signal) / price_at_signal * 100


def run_backtest(prefix="results", horizon_days=5, min_days_old=5, out_dir="data"):
    events = load_events(f"{out_dir}/history_{prefix}.json")
    cutoff = datetime.date.today() - datetime.timedelta(days=min_days_old)
    eligible = [e for e in events if datetime.date.fromisoformat(e["date"]) <= cutoff]

    print(f"Loaded {len(events)} scoring events, {len(eligible)} old enough "
          f"(signal >= {min_days_old} days ago) to have a {horizon_days}-day forward price.")
    if len(eligible) < 5:
        print("데이터 부족: 아직 백테스트할 만큼 히스토리가 쌓이지 않았습니다. "
              "매일 스캔이 쌓이면 (특히 클라우드 정기 실행) 자동으로 채워집니다.")
        return []

    results = []
    for i, e in enumerate(eligible):
        ret = forward_return(e["symbol"], e["date"], e["price"], horizon_days)
        if ret is not None:
            results.append({**e, "forward_return_pct": round(ret, 2)})
        if (i + 1) % 20 == 0:
            print(f"  ...{i + 1}/{len(eligible)} evaluated")

    print(f"\nEvaluated {len(results)}/{len(eligible)} events (rest had no price data).\n")
    print(f"{'점수 구간':<12}{'표본수':>8}{'상승 비율':>10}{'평균 수익률':>12}")
    for lo, hi in SCORE_BUCKETS:
        bucket = [r for r in results if lo <= r["score"] < hi]
        if not bucket:
            continue
        hit_rate = sum(1 for r in bucket if r["forward_return_pct"] > 0) / len(bucket) * 100
        avg_ret = sum(r["forward_return_pct"] for r in bucket) / len(bucket)
        label = f"{lo}-{hi if hi < 1000 else '+'}"
        print(f"{label:<12}{len(bucket):>8}{hit_rate:>9.1f}%{avg_ret:>11.1f}%")

    with open(f"{out_dir}/backtest_{prefix}.json", "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "horizon_days": horizon_days,
            "events": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\nWrote {out_dir}/backtest_{prefix}.json")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default="results")
    parser.add_argument("--horizon-days", type=int, default=5)
    parser.add_argument("--min-days-old", type=int, default=5)
    args = parser.parse_args()
    run_backtest(prefix=args.prefix, horizon_days=args.horizon_days, min_days_old=args.min_days_old)
