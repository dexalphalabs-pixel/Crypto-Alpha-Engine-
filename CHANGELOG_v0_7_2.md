# Crypto Alpha Engine v0.7.2 — GitHub Ready Fix

## Fixed
- Fixed invalid GitHub Actions YAML indentation that blocked workflow parsing.
- Improved GitHub cache key/restore strategy for SQLite persistence.
- Added runtime_state table for durable run state.
- Added daily digest de-duplication using `last_digest_sent_at`.
- Added `DIGEST_MIN_INTERVAL_HOURS` so daily digest cannot be resent repeatedly during manual/scheduled runs in the same hour.
- Added direct price lookup for tracked non-alert missed opportunities when a token does not reappear in the current scanner prefilter.
- Updated version labels and docs to v0.7.2.

## Notes
- GitHub Actions cache remains MVP-grade persistence. Reports and DB are also uploaded as artifacts.
- Missed-opportunity direct lookup is capped by `MISSED_OPPORTUNITY_PRICE_CHECK_LIMIT` to avoid excessive API calls.
