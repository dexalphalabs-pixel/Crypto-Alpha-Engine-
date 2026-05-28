"""GitHub Actions Telegram connectivity test.

This script intentionally fails when Telegram secrets are missing or invalid.
It is used before the scanner run so configuration problems are visible immediately.
"""
from __future__ import annotations

import os
import sys
import requests


def main() -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    run_url = os.getenv("GITHUB_RUN_URL", "").strip()

    if not token or not chat_id:
        print("ERROR: Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID repository secret.")
        print("Fix: GitHub repo → Settings → Secrets and variables → Actions → New repository secret.")
        return 2

    message = "✅ Crypto Alpha Engine: Telegram z GitHub Actions działa."
    if run_url:
        message += f"\nRun: {run_url}"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "disable_web_page_preview": True}
    try:
        response = requests.post(url, json=payload, timeout=20)
        print("Telegram status:", response.status_code)
        print(response.text[:1000])
        response.raise_for_status()
    except requests.HTTPError:
        print("ERROR: Telegram API rejected the request.")
        print("Common fixes:")
        print("- 401 Unauthorized: token from BotFather is wrong.")
        print("- 400 chat not found: send /start to the bot, then verify TELEGRAM_CHAT_ID via getUpdates.")
        print("- 403 forbidden: unblock the bot and send /start.")
        return 3
    except Exception as exc:
        print("ERROR: Telegram test failed:", exc)
        return 4

    print("Telegram test OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
