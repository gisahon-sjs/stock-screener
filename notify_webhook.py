"""Send a top-N digest to Slack and/or Discord via incoming webhooks.
No-ops silently if unconfigured -- safe to always call from the batch scripts.

Setup (one-time, done by the user -- never commit the config file):
  Slack:   Workspace -> Apps -> "Incoming Webhooks" -> Add to Slack -> copy the
           webhook URL (https://hooks.slack.com/services/...)
  Discord: Server -> Channel settings -> Integrations -> Webhooks -> New Webhook
           -> copy URL (https://discord.com/api/webhooks/...)

  Create webhook_config.json next to this file:
    {"slack_webhook_url": "https://hooks.slack.com/services/...",
     "discord_webhook_url": "https://discord.com/api/webhooks/..."}
  Either key can be omitted/blank to skip that channel.

Usage: python notify_webhook.py [--prefix results] [--top 10] [--min-score 40]
"""
import argparse
import json
import os

import requests

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "webhook_config.json")


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def build_digest(payload, top_n, min_score, bold="*"):
    rows = [r for r in payload["results"] if r["score"] >= min_score][:top_n]
    if not rows:
        return None
    b = bold
    lines = [f"{b}Nasdaq 저가주 스크리너{b} ({payload['generated_at'][:16]} UTC)",
             f"{payload['total_candidates']}종목 중 상위 {len(rows)}개:\n"]
    for r in rows:
        tag = " 🆕" if r.get("is_new") else ""
        top_reason = (r.get("reasons") or [""])[0]
        lines.append(f"{b}{r['symbol']}{b} ${r['price']:.4f} | {r['score']}점{tag}\n  {top_reason}")
    return "\n".join(lines)


def send_slack(url, text):
    resp = requests.post(url, json={"text": text}, timeout=15)
    return resp.status_code == 200, resp.text


def send_discord(url, text):
    # Discord caps message content at 2000 chars.
    resp = requests.post(url, json={"content": text[:2000]}, timeout=15)
    return resp.status_code in (200, 204), resp.text


def main(prefix="results", top_n=10, min_score=40, out_dir="data"):
    cfg = load_config()
    slack_url = cfg.get("slack_webhook_url")
    discord_url = cfg.get("discord_webhook_url")
    if not slack_url and not discord_url:
        print(f"[webhook] {CONFIG_PATH} not found / no URLs set -- skipping.")
        return

    path = f"{out_dir}/{prefix}.json"
    if not os.path.exists(path):
        print(f"[webhook] {path} not found -- skipping.")
        return
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if slack_url:
        text = build_digest(payload, top_n, min_score, bold="*")
        if text:
            ok, detail = send_slack(slack_url, text)
            print(f"[webhook] slack sent: {ok}" + ("" if ok else f" ({detail[:200]})"))
        else:
            print(f"[webhook] slack: no candidates scored >= {min_score} -- skipping.")

    if discord_url:
        text = build_digest(payload, top_n, min_score, bold="**")
        if text:
            ok, detail = send_discord(discord_url, text)
            print(f"[webhook] discord sent: {ok}" + ("" if ok else f" ({detail[:200]})"))
        else:
            print(f"[webhook] discord: no candidates scored >= {min_score} -- skipping.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default="results")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--min-score", type=float, default=40)
    args = parser.parse_args()
    main(prefix=args.prefix, top_n=args.top, min_score=args.min_score)
