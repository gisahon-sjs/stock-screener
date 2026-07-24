"""Scan SEC EDGAR full-text search for recent merger / business-combination filings."""
import re
import time
import requests

EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
HEADERS = {"User-Agent": "gisahon-research gisahon@gmail.com"}

MERGER_KEYWORDS = [
    "reverse merger",
    "agreement and plan of merger",
    "business combination agreement",
    "definitive merger agreement",
]
MERGER_FORMS = "8-K,S-4,425,DEFM14A,PREM14A"

TICKER_RE = re.compile(r"\(([A-Z][A-Z.\-]{0,6})\)")

# 8-K item codes, ranked by how directly they signal an active/completed M&A
# event (vs. generic/administrative items). Used to sharpen scoring precision
# beyond plain keyword matches.
ITEM_LABELS_KR = {
    "2.01": "인수/자산취득 완료",
    "1.01": "중요 계약 체결",
    "5.01": "지배권 변경",
    "3.01": "상장폐지/요건미달 통지",
    "8.01": "기타 사항",
}
ITEM_WEIGHTS = {
    "2.01": 15,
    "1.01": 10,
    "5.01": 8,
    "3.01": 3,
    "8.01": 2,
}


def _extract_ticker(display_names):
    for name in display_names:
        m = TICKER_RE.search(name)
        if m:
            return m.group(1)
    return None


def search_merger_filings(days_back=30, keywords=None, forms=MERGER_FORMS, pause=0.3):
    """Return {ticker: [ {keyword, form, file_date, cik, adsh, company, url}, ... ]}"""
    import datetime
    keywords = keywords or MERGER_KEYWORDS
    enddt = datetime.date.today()
    startdt = enddt - datetime.timedelta(days=days_back)
    hits_by_ticker = {}

    for kw in keywords:
        params = {
            "q": f'"{kw}"',
            "forms": forms,
            "startdt": startdt.isoformat(),
            "enddt": enddt.isoformat(),
        }
        try:
            resp = requests.get(EFTS_URL, headers=HEADERS, params=params, timeout=25)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            print(f"  [sec] query failed for '{kw}': {e}")
            continue

        for hit in data.get("hits", {}).get("hits", []):
            src = hit["_source"]
            display_names = src.get("display_names", [])
            ticker = _extract_ticker(display_names)
            if not ticker:
                continue
            cik = src.get("ciks", [None])[0]
            adsh = src.get("adsh", "").replace("-", "")
            cik_int = str(int(cik)) if cik else ""
            url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{adsh}/" if cik_int and adsh else None
            hits_by_ticker.setdefault(ticker, []).append({
                "keyword": kw,
                "form": src.get("form"),
                "file_date": src.get("file_date"),
                "company": display_names[0] if display_names else None,
                "url": url,
                "items": src.get("items", []),
            })
        time.sleep(pause)

    return hits_by_ticker


if __name__ == "__main__":
    hits = search_merger_filings(days_back=30)
    print(f"Tickers with recent merger-related filings: {len(hits)}")
    for t, records in list(hits.items())[:10]:
        print(t, records[0])
