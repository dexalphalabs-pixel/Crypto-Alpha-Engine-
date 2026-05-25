# Crypto Alpha Engine v0.7.3 — Telegram & Binance Fallback Fix

## Added

- GitHub Actions step `Test Telegram connection` before the engine run.
- `tools/test_telegram.py` for direct verification of `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
- Explicit Telegram environment flags in workflow:
  - `SEND_TELEGRAM_SUMMARY=true`
  - `SEND_TELEGRAM_ALERTS=true`
  - `SEND_TELEGRAM_DAILY_DIGEST=true`
- OKX public market API fallback for CEX scanning when Binance Spot API returns errors such as HTTP 451.
- CoinGecko fallback for BTC/ETH market context when Binance market context is blocked.
- `fallback_used` field in CEX and MarketContext health.

## Fixed

- GitHub run now fails early with clear logs if Telegram secrets are missing or invalid.
- Binance HTTP 451 no longer disables the entire CEX layer immediately when OKX fallback works.
- Market regime can still be inferred from CoinGecko BTC/ETH 24h changes when Binance context is unavailable.
- Workflow creates `outputs/` explicitly before the scan.
- HTTP User-Agent updated to v0.7.3.

## Notes

- OKX fallback does not provide Binance futures funding/OI metrics. Futures fields may be empty when fallback is used.
- CoinGecko fallback does not provide BTC hourly volatility, so `btc_volatility_24h_pct` may remain empty.
- Telegram test requires valid repository secrets and that the user/group has already started the bot.
