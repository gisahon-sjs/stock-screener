"""Send a top-N digest to Telegram after a scan. No-ops silently if unconfigured.

Setup (one-time, done by the user -- never commit the config file):
  1. Message @BotFather on Telegram -> /newbot -> get a bot token
  2. Message your new bot anything, then visit
     https://api.telegram.org/bot<TOKEN>/getUpdates to find your chat id
  3. Create telegram_config.json next to this file:
     {"bot_token": "123:ABC...", "chat_id": "123456789"}

Usage: python notify_telegram.py [--prefix results] [--top 10] [--min-score 40]
"""
import argparse
import json
import os

import requests

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "telegram_config.json")


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if cfg.get("bot_token") and cfg.get("chat_id"):
            return cfg
    except (json.JSONDecodeError, OSError):
        pass
    return None


def build_digest(payload, top_n, min_score):
    rows = [r for r in payload["results"] if r["score"] >= min_score][:top_n]
    if not rows:
        return None
    lines = [f"*Nasdaq 저가주 스크리너* ({payload['generated_at'][:16]} UTC)",
             f"{payload['total_candidates']}종목 중 상위 {len(rows)}개:\n"]
    for r in rows:
        tag = " 🆕" if r.get("is_new") else ""
        top_reason = (r.get("reasons") or [""])[0]
        lines.append(f"*{r['symbol']}* ${r['price']:.4f} | {r['score']}점{tag}\n  _{top_reason}_")
    return "\n".join(lines)


def send(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    resp = requests.post(url, data={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=15)
    return resp.status_code == 200, resp.text


def main(prefix="results", top_n=10, min_score=40, out_dir="data"):
    cfg = load_config()
    if not cfg:
        print(f"[telegram] {CONFIG_PATH} not found or incomplete -- skipping notification.")
        return

    path = f"{out_dir}/{prefix}.json"
    if not os.path.exists(path):
        print(f"[telegram] {path} not found -- skipping.")
        return
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    text = build_digest(payload, top_n, min_score)
    if not text:
        print(f"[telegram] no candidates scored >= {min_score} -- skipping.")
        return

    ok, detail = send(cfg["bot_token"], cfg["chat_id"], text)
    print(f"[telegram] sent: {ok}" + ("" if ok else f" ({detail[:200]})"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default="results")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--min-score", type=float, default=40)
    args = parser.parse_args()
    main(prefix=args.prefix, top_n=args.top, min_score=args.min_score)
