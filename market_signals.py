"""Volume/price-spike detection and float-shares lookup via yfinance."""
import time
import warnings
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")


def _chunk(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def detect_bottom_reversal(closes, near_low_pct=0.25, sideways_cv=0.20, breakout_pct=5.0,
                            min_base_days=15, max_trough_age_days=182):
    """Heuristic: 26-week-range low -> sideways base -> recent upward breakout.

    closes: pandas Series of daily closes, oldest first, ideally ~6mo of history.
    Returns a dict describing the pattern, or None if it doesn't apply / not enough data.
    """
    closes = closes.dropna()
    if len(closes) < min_base_days + 15:
        return None

    low_26w, high_26w = float(closes.min()), float(closes.max())
    current = float(closes.iloc[-1])
    if high_26w <= low_26w:
        return None
    range_pos = (current - low_26w) / (high_26w - low_26w)

    trough_idx = int(closes.values.argmin())
    days_since_trough = len(closes) - 1 - trough_idx
    # Trough must be recent-ish (so this is "basing", not ancient history) and
    # have had enough days since to actually form a base + reversal.
    if days_since_trough < min_base_days or days_since_trough > max_trough_age_days:
        return None

    post_trough = closes.iloc[trough_idx:]
    if len(post_trough) < min_base_days + 5:
        return None

    recent = post_trough.iloc[-5:]
    base = post_trough.iloc[:-5]
    if len(base) < min_base_days:
        return None

    base_mean = float(base.mean())
    base_cv = float((base.max() - base.min()) / base_mean) if base_mean else 1.0
    is_sideways = base_cv <= sideways_cv

    breakout = (current / base_mean - 1) * 100 if base_mean else 0.0
    is_breaking_out = breakout >= breakout_pct and current > float(recent.iloc[0])
    is_near_low = range_pos <= near_low_pct

    if not (is_near_low and is_sideways and is_breaking_out):
        return None

    return {
        "range_pos_pct": round(range_pos * 100, 1),
        "days_since_trough": days_since_trough,
        "base_days": len(base),
        "breakout_pct": round(breakout, 1),
        "low_26w": low_26w,
        "high_26w": high_26w,
    }


def bulk_volume_signals(tickers, chunk_size=100, period="6mo", pause=1.0, progress=True):
    """Return {ticker: {last_close, last_volume, avg_volume_20d, volume_ratio, day_change_pct, bottom_reversal}}"""
    results = {}
    chunks = list(_chunk(sorted(set(tickers)), chunk_size))
    for i, batch in enumerate(chunks):
        try:
            data = yf.download(batch, period=period, group_by="ticker",
                                threads=True, progress=False, auto_adjust=False)
        except Exception as e:
            print(f"  [market] batch {i+1}/{len(chunks)} failed: {e}")
            continue

        for t in batch:
            try:
                df = data[t] if len(batch) > 1 else data
                df = df.dropna(subset=["Volume", "Close"])
                if len(df) < 2:
                    continue
                last_volume = float(df["Volume"].iloc[-1])
                last_close = float(df["Close"].iloc[-1])
                prev_close = float(df["Close"].iloc[-2])
                hist_vol = df["Volume"].iloc[:-1]
                avg_volume = float(hist_vol.tail(20).mean()) if len(hist_vol) else None
                ratio = (last_volume / avg_volume) if avg_volume and avg_volume > 0 else None
                day_change_pct = ((last_close - prev_close) / prev_close * 100) if prev_close else None
                results[t] = {
                    "last_close": last_close,
                    "last_volume": last_volume,
                    "avg_volume_20d": avg_volume,
                    "volume_ratio": ratio,
                    "day_change_pct": day_change_pct,
                    "bottom_reversal": detect_bottom_reversal(df["Close"]),
                }
            except (KeyError, IndexError, ValueError):
                continue
        if progress:
            print(f"  [market] volume batch {i+1}/{len(chunks)} done ({len(results)} total so far)")
        time.sleep(pause)
    return results


def _fetch_float_one(ticker):
    try:
        info = yf.Ticker(ticker).get_info()
        return ticker, {
            "float_shares": info.get("floatShares"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "short_name": info.get("shortName") or info.get("longName"),
        }
    except Exception:
        return ticker, None


def fetch_float_shares(tickers, max_workers=8, progress=True):
    """Fetch float/shares-outstanding for a (typically short-listed) set of tickers."""
    out = {}
    tickers = list(dict.fromkeys(tickers))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_float_one, t): t for t in tickers}
        done = 0
        for fut in as_completed(futures):
            t, info = fut.result()
            if info:
                out[t] = info
            done += 1
            if progress and done % 20 == 0:
                print(f"  [float] {done}/{len(tickers)} done")
    return out


if __name__ == "__main__":
    sample = ["CYCN", "VYNE", "AAPL", "CGC", "PLX"]
    vs = bulk_volume_signals(sample)
    for t, v in vs.items():
        print(t, v)
    fl = fetch_float_shares(sample)
    for t, v in fl.items():
        print(t, v)
