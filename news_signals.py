"""Scan Google News RSS headlines per ticker for M&A / merger keywords."""
import re
import time
import feedparser
import requests

RSS_URL = "https://news.google.com/rss/search"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

NEWS_KEYWORDS = [
    "merger", "acquisition", "acquire", "reverse merger",
    "business combination", "going private", "buyout", "definitive agreement",
]

# Heuristic, keyword-based headline classifier. This is NOT a trained model or a
# real statistical probability -- it's a rough confidence score for "does this
# headline read like a live/positive M&A catalyst" vs "this deal is dead/at risk".
POSITIVE_PATTERNS = [
    r"\bto acquire\b", r"\bacquisition of\b", r"\bagrees? to (be )?acquir",
    r"\bdefinitive (merger )?agreement\b", r"\bmerger agreement\b",
    r"\ball-cash\b", r"\bpremium\b", r"\bcompletes? (its )?acquisition\b",
    r"\bto merge with\b", r"\bplans? merger\b", r"\bbusiness combination\b",
    r"\btakes? private\b", r"\btender offer\b", r"\bbuyout\b", r"\bacquired by\b",
    r"\bclose(s|d)? (the )?(merger|acquisition|deal)\b", r"\bstock-for-stock\b",
]
NEGATIVE_PATTERNS = [
    r"\bterminat", r"\bno longer advisable\b", r"\bcalls? off\b", r"\bscraps?\b",
    r"\breject", r"\bwalks? away\b", r"\bcollapse", r"\bends? talks\b",
    r"\bfails?\b", r"\bblock(ed|s)?\b", r"\bopposes?\b", r"\blawsuit\b",
    r"\bsues?\b", r"\bdrops? (the )?(merger|acquisition|deal)\b",
    r"\bwithdraws?\b", r"\bcalled off\b",
]
_POS_RE = re.compile("|".join(POSITIVE_PATTERNS), re.I)
_NEG_RE = re.compile("|".join(NEGATIVE_PATTERNS), re.I)


def score_headline(title):
    """Return (probability_pct, label) -- a heuristic 'positive M&A catalyst' confidence."""
    if not title:
        return 50, "중립"
    pos_hits = len(_POS_RE.findall(title))
    neg_hits = len(_NEG_RE.findall(title))
    score = 50 + min(30, pos_hits * 15) - min(45, neg_hits * 25)
    score = max(5, min(95, score))
    if neg_hits and neg_hits >= pos_hits:
        label = "악재 가능성"
    elif score >= 70:
        label = "호재 가능성 높음"
    elif score >= 55:
        label = "호재 가능성"
    else:
        label = "중립/불확실"
    return score, label


def scan_news_for_ticker(ticker, company_hint=None, window_days=14, timeout=15, retries=1):
    """Return a list of matching headlines for this ticker, most recent first."""
    query = f'"{ticker}" (merger OR acquisition OR acquire OR buyout) when:{window_days}d'
    params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    resp = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(RSS_URL, headers=HEADERS, params=params, timeout=timeout)
            if resp.status_code == 503:
                # Google's bot-detection page; back off and retry once.
                time.sleep(3 * (attempt + 1))
                continue
            resp.raise_for_status()
            break
        except requests.RequestException:
            return []
    else:
        return []  # exhausted retries, still 503'd
    if resp is None or resp.status_code != 200:
        return []

    feed = feedparser.parse(resp.content)
    results = []
    for entry in feed.entries[:5]:
        title = entry.get("title", "")
        prob, label = score_headline(title)
        results.append({
            "title": title,
            "link": entry.get("link"),
            "published": entry.get("published"),
            "catalyst_prob": prob,
            "catalyst_label": label,
        })
    results.sort(key=lambda a: a["catalyst_prob"], reverse=True)
    return results


def scan_news_for_tickers(tickers, pause=0.6, progress=True):
    """Batch-scan a list of tickers; returns {ticker: [headline, ...]} for tickers with hits."""
    hits = {}
    for i, t in enumerate(tickers):
        articles = scan_news_for_ticker(t)
        if articles:
            hits[t] = articles
        if progress and (i + 1) % 25 == 0:
            print(f"  [news] scanned {i + 1}/{len(tickers)} tickers, {len(hits)} with hits")
        time.sleep(pause)
    return hits


if __name__ == "__main__":
    for t in ["CYCN", "VYNE", "AAPL"]:
        arts = scan_news_for_ticker(t)
        print(t, len(arts), arts[:1])
