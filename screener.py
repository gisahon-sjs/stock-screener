"""Main orchestrator: Nasdaq sub-$1 small-cap merger/catalyst screener.

Pipeline:
  1. Pull the full Nasdaq universe, filter to price < $1 and market cap < $2B.
  2. Bulk-fetch volume/price history for all candidates (spike detection).
  3. Scan SEC EDGAR full-text search for recent merger-related filings.
  4. Scan Google News headlines for M&A keywords (shortlist only, to limit requests).
  5. Fetch float shares for the shortlist (low float = bigger catalyst reaction).
  6. Score and rank; write data/results.json and data/results.csv.
"""
import json
import datetime
import pandas as pd

import universe
import sec_signals
import news_signals
import market_signals

MAX_PRICE = 1.0
MAX_MARKET_CAP = 2_000_000_000
SEC_LOOKBACK_DAYS = 30
NEWS_WINDOW_DAYS = 14

# Thresholds for deciding which tickers are "interesting enough" to spend
# News RSS / float-shares API calls on.
SHORTLIST_VOLUME_RATIO = 2.0
SHORTLIST_DAY_CHANGE_PCT = 15.0

KEYWORD_KR = {
    "reverse merger": "리버스 머저(우회상장)",
    "agreement and plan of merger": "합병계획계약",
    "business combination agreement": "사업결합계약",
    "definitive merger agreement": "확정 합병계약",
}


def kr_count(n):
    """Format a large count using Korean 억/만 units, e.g. 142_000_000 -> '1억 4,200만'."""
    n = int(round(abs(n)))
    eok, rem = divmod(n, 100_000_000)
    man, rest = divmod(rem, 10_000)
    parts = []
    if eok:
        parts.append(f"{eok}억")
    if man:
        parts.append(f"{man:,}만")
    if not parts:
        parts.append(f"{rest:,}")
    return " ".join(parts)


def build_shortlist(df: pd.DataFrame, sec_hits: dict) -> list:
    cond = (
        df["symbol"].isin(sec_hits.keys())
        | (df["volume_ratio"].fillna(0) >= SHORTLIST_VOLUME_RATIO)
        | (df["day_change_pct"].abs().fillna(0) >= SHORTLIST_DAY_CHANGE_PCT)
        | (df["pct_change"].abs().fillna(0) >= SHORTLIST_DAY_CHANGE_PCT)
    )
    return df.loc[cond, "symbol"].tolist()


def score_row(row, sec_hits, news_hits, float_info) -> tuple:
    score = 0.0
    reasons = []

    sec_records = sec_hits.get(row["symbol"])
    if sec_records:
        score += 40 + min(15, 5 * (len(sec_records) - 1))
        kws = sorted(set(r["keyword"] for r in sec_records))
        kws_kr = [KEYWORD_KR.get(k, k) for k in kws]

        all_items = sorted({it for r in sec_records for it in (r.get("items") or [])})
        best_item = max((it for it in all_items if it in sec_signals.ITEM_WEIGHTS),
                         key=lambda it: sec_signals.ITEM_WEIGHTS[it], default=None)
        item_note = ""
        if best_item:
            item_add = sec_signals.ITEM_WEIGHTS[best_item]
            score += item_add
            item_note = f" [Item {best_item} - {sec_signals.ITEM_LABELS_KR.get(best_item, '')}]"

        reasons.append(
            f"SEC 공시: {', '.join(kws_kr)} ({sec_records[0]['form']}, {sec_records[0]['file_date']}){item_note}")

    news_articles = news_hits.get(row["symbol"])
    if news_articles:
        best_prob = max(a["catalyst_prob"] for a in news_articles)
        add = (best_prob - 50) * 0.7
        if best_prob >= 55:
            add += min(8, 2 * (len(news_articles) - 1))
        score += add
        for a in news_articles[:2]:
            reasons.append(f"뉴스 ({a['catalyst_label']} {a['catalyst_prob']}%): \"{a['title']}\"")

    ratio = row.get("volume_ratio")
    if pd.notna(ratio) and ratio and ratio >= 1.5:
        add = min(25, (ratio - 1) * 10)
        score += add
        reasons.append(f"거래량 20일 평균 대비 {ratio:.1f}배")

    day_chg = row.get("day_change_pct")
    if pd.notna(day_chg) and abs(day_chg) >= 8:
        add = min(20, abs(day_chg) / 2)
        score += add
        reasons.append(f"당일 변동률 {day_chg:+.1f}%")

    reversal = row.get("bottom_reversal")
    if isinstance(reversal, dict):
        add = min(30, 10 + reversal["breakout_pct"] * 0.5)
        score += add
        reasons.append(
            f"26주 바닥권({reversal['range_pos_pct']:.0f}% 지점) 횡보 후 상승 전환 "
            f"(저점 대비 +{reversal['breakout_pct']:.1f}%, {reversal['days_since_trough']}일 전 저점)")

    finfo = float_info.get(row["symbol"])
    float_shares = finfo.get("float_shares") if finfo else None
    if float_shares:
        if float_shares < 5_000_000:
            score += 15
            reasons.append(f"매우 낮은 유통주식수 ({kr_count(float_shares)}주)")
        elif float_shares < 20_000_000:
            score += 8
            reasons.append(f"낮은 유통주식수 ({kr_count(float_shares)}주)")

    mcap = row.get("market_cap")
    if score > 0 and pd.notna(mcap) and mcap and mcap < 50_000_000:
        score += 5
        reasons.append("초소형주 (시가총액 5,000만 달러 미만)")

    return round(max(0.0, score), 1), reasons


def find_base_symbol(symbol, security_type, all_symbols):
    """Heuristically strip the Nasdaq security-class suffix (W/WW/R/U) to find
    the underlying common-stock ticker, verified against the known universe."""
    if security_type == "Common" or not symbol:
        return symbol
    for strip_len in (1, 2):
        candidate = symbol[:-strip_len]
        if candidate and candidate in all_symbols:
            return candidate
    return symbol


def update_score_history(out_dir, prefix, candidates, now_iso, retention_days=60):
    """Append this run's scores to a rolling per-symbol history file and return
    a trimmed {symbol: [{t, s}, ...]} map for symbols in this run (dashboard sparklines)."""
    import os
    path = f"{out_dir}/history_{prefix}.json"
    history = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except (json.JSONDecodeError, OSError):
            history = {}

    for _, row in candidates.iterrows():
        if row["score"] > 0:
            history.setdefault(row["symbol"], []).append(
                {"t": now_iso, "s": row["score"], "p": row.get("price")})

    cutoff = datetime.datetime.fromisoformat(now_iso.rstrip("Z")) - datetime.timedelta(days=retention_days)
    trimmed = {}
    for sym, points in history.items():
        kept = [p for p in points if datetime.datetime.fromisoformat(p["t"].rstrip("Z")) >= cutoff]
        if kept:
            trimmed[sym] = kept

    os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False)

    return trimmed


def _load_previous_scored_symbols(out_dir, prefix):
    """Read the previous run's output (if any) to detect newly-appeared candidates."""
    import os
    path = f"{out_dir}/{prefix}.json"
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            prev = json.load(f)
        return {r["symbol"] for r in prev.get("results", []) if r.get("score", 0) > 0}
    except (json.JSONDecodeError, KeyError, OSError):
        return set()


def run(max_price=MAX_PRICE, max_market_cap=MAX_MARKET_CAP, out_dir="data", prefix="results"):
    previously_scored = _load_previous_scored_symbols(out_dir, prefix)
    print("[1/6] Fetching Nasdaq universe ...")
    uni = universe.fetch_nasdaq_universe()
    candidates = universe.filter_sub_dollar_smallcap(uni, max_price, max_market_cap)
    print(f"      {len(uni)} total symbols -> {len(candidates)} sub-${max_price} small-cap candidates")

    all_symbols = set(uni["symbol"])
    uni_lookup = uni.set_index("symbol")[["name", "price", "security_type"]].to_dict(orient="index")
    candidates["base_symbol"] = candidates.apply(
        lambda r: find_base_symbol(r["symbol"], r["security_type"], all_symbols), axis=1)

    print("[2/6] Fetching volume/price history (spike detection) ...")
    vol_signals = market_signals.bulk_volume_signals(candidates["symbol"].tolist())
    vol_df = pd.DataFrame.from_dict(vol_signals, orient="index").reset_index().rename(columns={"index": "symbol"})
    candidates = candidates.merge(vol_df, on="symbol", how="left")

    print("[3/6] Scanning SEC EDGAR for merger-related filings ...")
    sec_hits = sec_signals.search_merger_filings(days_back=SEC_LOOKBACK_DAYS)
    sec_hits = {t: v for t, v in sec_hits.items() if t in set(candidates["symbol"])}
    print(f"      {len(sec_hits)} candidates have recent merger-related SEC filings")

    shortlist = build_shortlist(candidates, sec_hits)
    print(f"[4/6] Scanning news headlines for {len(shortlist)} shortlisted tickers ...")
    news_hits = news_signals.scan_news_for_tickers(shortlist)
    print(f"      {len(news_hits)} shortlisted tickers have matching news")

    print(f"[5/6] Fetching float shares for {len(shortlist)} shortlisted tickers ...")
    float_info = market_signals.fetch_float_shares(shortlist)

    print("[6/6] Scoring and ranking ...")
    scores, reasons_list = [], []
    for _, row in candidates.iterrows():
        s, r = score_row(row, sec_hits, news_hits, float_info)
        scores.append(s)
        reasons_list.append(r)
    candidates["score"] = scores
    candidates["reasons"] = reasons_list
    candidates["float_shares"] = candidates["symbol"].map(lambda t: (float_info.get(t) or {}).get("float_shares"))
    candidates["news"] = candidates["symbol"].map(lambda t: news_hits.get(t, []))
    candidates["reversal_pct"] = candidates["bottom_reversal"].map(
        lambda r: r["breakout_pct"] if isinstance(r, dict) else None)
    candidates["is_new"] = candidates.apply(
        lambda r: bool(r["score"] > 0 and r["symbol"] not in previously_scored), axis=1)

    by_symbol = candidates.set_index("symbol")[["security_type", "price", "score", "base_symbol"]].to_dict(orient="index")

    def _related(sym):
        base = by_symbol[sym]["base_symbol"]
        siblings = [{"symbol": s, "security_type": v["security_type"], "price": v["price"], "score": v["score"]}
                    for s, v in by_symbol.items() if v["base_symbol"] == base and s != sym]
        return siblings

    def _underlying(row):
        if row["security_type"] == "Common" or row["base_symbol"] == row["symbol"]:
            return None
        info = uni_lookup.get(row["base_symbol"])
        if not info:
            return None
        return {"symbol": row["base_symbol"], "name": info["name"], "price": info["price"],
                "in_candidates": row["base_symbol"] in by_symbol}

    candidates["related"] = candidates["symbol"].map(_related)
    candidates["underlying"] = candidates.apply(_underlying, axis=1)

    generated_at = datetime.datetime.utcnow().isoformat() + "Z"
    history = update_score_history(out_dir, prefix, candidates, generated_at)
    candidates["score_history"] = candidates["symbol"].map(lambda t: history.get(t, []))

    candidates = candidates.sort_values("score", ascending=False).reset_index(drop=True)

    import os
    os.makedirs(out_dir, exist_ok=True)
    candidates.to_csv(f"{out_dir}/{prefix}.csv", index=False)

    payload = {
        "generated_at": generated_at,
        "filters": {"max_price": max_price, "max_market_cap": max_market_cap},
        "total_universe": len(uni),
        "total_candidates": len(candidates),
        "results": json.loads(candidates.to_json(orient="records")),
    }
    with open(f"{out_dir}/{prefix}.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Done. Wrote {out_dir}/{prefix}.json and {out_dir}/{prefix}.csv")
    print(candidates[["symbol", "name", "price", "score"]].head(20).to_string(index=False))
    return candidates


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default="results", help="Output filename prefix under data/ (e.g. 'live_results')")
    args = parser.parse_args()
    run(prefix=args.prefix)
