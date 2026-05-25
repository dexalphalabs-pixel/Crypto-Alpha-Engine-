# Crypto Alpha Engine v0.7.2 Stability Hotfix

SAFE_MODE-only analytical engine for crypto market scanning. It combines:

- DEX early radar via DexScreener
- DEX security screening via GoPlus for EVM chains
- Binance CEX momentum scanner with 1h/4h klines
- BTC/ETH relative strength and market regime context
- Funding and Open Interest proxy for Binance USD-M perpetuals
- Event/news and unlock-risk layers
- Watchlist, cooldown and performance database
- Diagnostics: rejected reasons, watchlist upgrades, missed opportunities
- HTML/CSV/JSON reports
- Telegram alerts/digest in Polish
- GitHub Actions hourly execution with cached SQLite persistence

The project **does not trade** and does not connect to exchange accounts.

## v0.7.2 hotfix changes

- Recalculates candidate status after `MarketContextEngine` changes score/risk, preventing stale `HIGH_CONVICTION` alerts.
- Fixes Telegram “Daily Digest” so it is daily by default, not hourly.
- Adds `DIGEST_MODE=daily/hourly/off` and `DIGEST_HOUR_UTC`.
- Adds fast-fail behavior: if all enabled market-data sources fail, secondary enrichment layers are skipped.
- Adds `klines_available` so Data Quality does not confuse a flat 0% move with missing klines.
- Adds cleanup for `tracked_non_alerts` via `TRACKED_NON_ALERT_RETENTION_DAYS`.
- Keeps Solana DEX candidates watchlist-only unless a Solana security provider is explicitly available.
- Adds optional GitHub Actions run URL in Telegram summary through `GITHUB_RUN_URL`.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python main.py
```

## Run modes

```text
RUN_MODE=full         DEX + CEX + security/news/context + performance
RUN_MODE=dex          DEX only + security/news/context
RUN_MODE=cex          CEX only + news/futures/context
RUN_MODE=performance  only update due performance windows and reports
```

## Important Telegram settings

```text
SEND_TELEGRAM_ALERTS=true
SEND_TELEGRAM_SUMMARY=true
SEND_TELEGRAM_DAILY_DIGEST=true
DIGEST_MODE=daily       # daily, hourly, off
DIGEST_HOUR_UTC=18
INSTANT_ALERT_STATUSES=HIGH_CONVICTION
```

By default only high-conviction alerts are immediate. Other alerts are grouped into the daily digest.

## GitHub Actions persistence

The workflow restores `outputs/crypto_alpha.db` from GitHub cache and saves a new cache entry after each run. This keeps:

- alert cooldown
- watchlist state
- performance windows
- watchlist improving/degrading history
- tracked non-alert candidates

Artifacts contain the latest reports and database snapshot.

## Remaining limitations

- GitHub cache is acceptable for MVP tests, but it is not a guaranteed production database.
- GoPlus screening is not a full contract audit.
- Solana DEX security is not supported by default and remains conservative/watchlist-only.
- Funding/OI still need deeper historical trend modelling.
- News/event layer is still keyword/rule based.
