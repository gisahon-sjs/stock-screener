"""Scan Google News RSS headlines per ticker for M&A / merger keywords."""
import time
import feedparser
import requests

RSS_URL = "https://news.google.com/rss/search"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

NEWS_KEYWORDS = [
    "merger", "acquisition", "acquire", "reverse merger",
    "business combination", "going private", "buyout", "definitive agreement",
]


def scan_news_for_ticker(ticker, company_hint=None, window_days=14, timeout=15):
    """Return a list of matching headlines for this ticker, most recent first."""
    query = f'"{ticker}" (merger OR acquisition OR acquire OR buyout) when:{window_days}d'
    params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    try:
        resp = requests.get(RSS_URL, headers=HEADERS, params=params, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException:
        return []

    feed = feedparser.parse(resp.content)
    results = []
    for entry in feed.entries[:5]:
        title = entry.get("title", "")
        results.append({
            "title": title,
            "link": entry.get("link"),
            "published": entry.get("published"),
        })
    return results


def scan_news_for_tickers(tickers, pause=0.25, progress=True):
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
