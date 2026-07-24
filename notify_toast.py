"""Zero-setup local Windows desktop notification -- no config needed, works out
of the box (reuses notify_failure.ps1's balloon-tip mechanism). Fires only when
something crosses min-score, to avoid a popup every single run.

Usage: python notify_toast.py [--prefix results] [--min-score 55]
"""
import argparse
import json
import os
import subprocess

HERE = os.path.dirname(__file__)


def main(prefix="results", min_score=55, out_dir="data"):
    path = f"{out_dir}/{prefix}.json"
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    hits = [r for r in payload["results"] if r["score"] >= min_score]
    if not hits:
        print(f"[toast] no candidates scored >= {min_score} -- skipping.")
        return

    top = hits[0]
    new_count = sum(1 for r in hits if r.get("is_new"))
    title = f"Stock Screener: {len(hits)}개 신호 (>={min_score:.0f}점)"
    body = f"{top['symbol']} {top['score']}점 ${top['price']:.4f}"
    if new_count:
        body += f" | 신규 {new_count}개"
    subprocess.Popen([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        os.path.join(HERE, "notify_failure.ps1"), "-Title", title, "-Body", body,
    ])
    print(f"[toast] shown: {title} / {body}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default="results")
    parser.add_argument("--min-score", type=float, default=55)
    args = parser.parse_args()
    main(prefix=args.prefix, min_score=args.min_score)
