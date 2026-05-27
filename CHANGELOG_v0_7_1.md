# v0.7.1 Stability Hotfix

## Fixed

- Recalculate candidate status after Market Context modifies score/risk.
- Daily digest is now actually daily by default via `DIGEST_MODE=daily` and `DIGEST_HOUR_UTC`.
- Fast-fail path skips secondary enrichment when all market data sources fail.
- Data Quality uses `klines_available` instead of treating 0% 1h/4h move as missing data.
- Cleanup for stale `tracked_non_alerts` rows.
- Solana DEX remains watchlist-only unless a dedicated Solana security source is available.
- Telegram summary can include GitHub Actions run URL.

## Validation

- `python -m compileall -q .` passed.
- `RUN_MODE=performance` passed.
- Refresh-status regression check passed.
