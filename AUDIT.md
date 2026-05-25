# Crypto Alpha Engine v0.7.2 Audit / Hotfix Notes

## Fixed from v0.7 audit

1. **Stale status after Market Context**
   - `ScoringEngine.refresh_status()` recalculates status after market-context score/risk adjustments.
   - This prevents candidates from keeping `HIGH_CONVICTION` after a risk-off penalty.

2. **Daily Digest spam**
   - Added `DIGEST_MODE=daily/hourly/off` and `DIGEST_HOUR_UTC`.
   - Default mode is daily, so hourly GitHub runs no longer send a digest every hour.

3. **Fast-fail during market API failure**
   - If all enabled market data sources fail, secondary layers such as security/news/unlock/context are skipped.
   - A health report is still generated.

4. **Data Quality false penalty**
   - Added `klines_available` on CEX candidates.
   - Data Quality now penalizes missing klines, not a legitimate 0% momentum move.

5. **Tracked non-alert cleanup**
   - Added cleanup for `tracked_non_alerts` with `TRACKED_NON_ALERT_RETENTION_DAYS`.
   - This prevents GitHub-cached SQLite from growing indefinitely.

6. **Solana DEX safety limit**
   - Solana DEX candidates remain watchlist-only unless a dedicated Solana security provider is available.

7. **GitHub run URL in Telegram summary**
   - `GITHUB_RUN_URL` can be passed by workflow so Telegram points to the current Actions run.

## Current readiness

```text
Technical 24h test: yes
7d quality test: yes, with GitHub cache enabled
Production readiness: MVP/staging, not institutional-grade
```

## Known limitations

- Missed opportunities are still limited by current-candidate visibility; a future version should independently refresh tracked non-alert prices.
- DEX historical performance is approximate unless prices are stored or fetched from a historical source.
- GitHub cache can expire or be evicted; external storage is better for production.
- News and unlock data are simple/rule-based and should not be treated as exhaustive.

## Suggested next version

v0.8 should focus on a true DEX → CEX bridge:

- token identity table
- cautious symbol/name matching
- independent price refresh for tracked non-alerts
- OI/funding trend history
- better external news/unlock sources
