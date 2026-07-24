"""Fetch the full Nasdaq-listed universe and filter to sub-$1 small-caps."""
import re
import requests
import pandas as pd

NASDAQ_SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

SECURITY_TYPE_PATTERNS = [
    ("Warrant", re.compile(r"\bWarrant", re.I)),
    ("Right", re.compile(r"\bRight", re.I)),
    ("Unit", re.compile(r"\bUnit", re.I)),
    ("Preferred", re.compile(r"\bPreferred", re.I)),
    ("ADS/ADR", re.compile(r"American Depositary", re.I)),
]


def classify_security(name: str) -> str:
    for label, pat in SECURITY_TYPE_PATTERNS:
        if pat.search(name):
            return label
    return "Common"


def _to_float(x):
    if x is None:
        return None
    s = str(x).replace("$", "").replace(",", "").strip()
    if s in ("", "--", "N/A", "UNCH"):
        return None if s != "UNCH" else 0.0
    try:
        return float(s)
    except ValueError:
        return None


def fetch_nasdaq_universe(timeout=30) -> pd.DataFrame:
    """Pull every symbol currently listed on Nasdaq via the public screener API."""
    params = {"tableonly": "true", "limit": 10000, "exchange": "NASDAQ"}
    resp = requests.get(NASDAQ_SCREENER_URL, headers=HEADERS, params=params, timeout=timeout)
    resp.raise_for_status()
    rows = resp.json()["data"]["table"]["rows"]
    df = pd.DataFrame(rows)
    df["price"] = df["lastsale"].apply(_to_float)
    df["pct_change"] = df["pctchange"].astype(str).str.replace("%", "").apply(_to_float)
    df["market_cap"] = df["marketCap"].apply(_to_float)
    df["security_type"] = df["name"].apply(classify_security)
    return df[["symbol", "name", "price", "pct_change", "market_cap", "security_type"]]


def filter_sub_dollar_smallcap(df: pd.DataFrame, max_price=1.0, max_market_cap=2_000_000_000) -> pd.DataFrame:
    out = df[(df["price"].notna()) & (df["price"] > 0) & (df["price"] < max_price)]
    out = out[(out["market_cap"].isna()) | (out["market_cap"] < max_market_cap)]
    return out.reset_index(drop=True)


if __name__ == "__main__":
    universe = fetch_nasdaq_universe()
    print(f"Total Nasdaq symbols: {len(universe)}")
    candidates = filter_sub_dollar_smallcap(universe)
    print(f"Sub-$1 small-cap candidates: {len(candidates)}")
    print(candidates.head(10))
