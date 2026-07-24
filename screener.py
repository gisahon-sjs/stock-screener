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
        reasons.append(f"SEC 공시: {', '.join(kws_kr)} ({sec_records[0]['form']}, {sec_records[0]['file_date']})")

    news_articles = news_hits.get(row["symbol"])
    if news_articles:
        score += 25 + min(10, 3 * (len(news_articles) - 1))
        reasons.append(f"뉴스: \"{news_articles[0]['title']}\"")

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

    finfo = float_info.get(row["symbol"])
    float_shares = finfo.get("float_shares") if finfo else None
    if float_shares:
        if float_shares < 5_000_000:
            score += 15
            reasons.append(f"매우 낮은 유통주식수 ({float_shares/1e6:.1f}M주)")
        elif float_shares < 20_000_000:
            score += 8
            reasons.append(f"낮은 유통주식수 ({float_shares/1e6:.1f}M주)")

    mcap = row.get("market_cap")
    if score > 0 and pd.notna(mcap) and mcap and mcap < 50_000_000:
        score += 5
        reasons.append("초소형주 (시가총액 $50M 미만)")

    return round(score, 1), reasons


def run(max_price=MAX_PRICE, max_market_cap=MAX_MARKET_CAP, out_dir="data", prefix="results"):
    print("[1/6] Fetching Nasdaq universe ...")
    uni = universe.fetch_nasdaq_universe()
    candidates = universe.filter_sub_dollar_smallcap(uni, max_price, max_market_cap)
    print(f"      {len(uni)} total symbols -> {len(candidates)} sub-${max_price} small-cap candidates")

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
    candidates = candidates.sort_values("score", ascending=False).reset_index(drop=True)

    import os
    os.makedirs(out_dir, exist_ok=True)
    candidates.to_csv(f"{out_dir}/{prefix}.csv", index=False)

    payload = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
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
