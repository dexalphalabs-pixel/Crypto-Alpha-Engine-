
from __future__ import annotations

import json
from collections import Counter
from utils.http_client import build_session, get_json

BINANCE_PRICE_URL = "https://api.binance.com/api/v3/ticker/price"
DEX_PAIR_URL = "https://api.dexscreener.com/latest/dex/pairs/{chain}/{pair}"


class DiagnosticsEngine:
    """Build calibration diagnostics for rejected candidates, watchlist upgrades and missed opportunities."""

    def __init__(self, settings, db):
        self.settings = settings
        self.db = db
        self.session = build_session()

    def rejected_reasons_summary(self, candidates) -> list[dict]:
        counter: Counter[str] = Counter()
        for c in candidates:
            if not str(c.status).startswith("REJECTED"):
                continue
            if c.risks:
                for risk in c.risks:
                    counter[risk] += 1
            else:
                counter[c.status] += 1
        return [{"reason": reason, "count": count} for reason, count in counter.most_common(25)]

    def watchlist_upgrades(self, candidates) -> list[dict]:
        rows = []
        for c in candidates:
            upgrade_reason = next((r for r in c.reasons if "watchlist improving" in r.lower() or "nowy najlepszy" in r.lower()), None)
            if c.status == "WATCHLIST_IMPROVING" or upgrade_reason:
                rows.append({
                    "symbol": c.symbol,
                    "source": c.source,
                    "status": c.status,
                    "final_score": round(c.final_score, 2),
                    "risk_score": round(c.risk_score, 2),
                    "price_usd": c.price_usd,
                    "volume_24h_usd": round(c.volume_24h_usd, 2),
                    "reason": upgrade_reason or "watchlist improving",
                    "url": c.url,
                })
        return sorted(rows, key=lambda x: x["final_score"], reverse=True)[:50]

    def dry_run_verbose_summary(self, candidates, health) -> dict:
        by_status = Counter(c.status for c in candidates)
        by_source = Counter(c.source for c in candidates)
        return {
            "total_candidates": len(candidates),
            "by_status": dict(by_status),
            "by_source": dict(by_source),
            "health": health,
            "rejected_reasons_top": self.rejected_reasons_summary(candidates)[:15],
        }

    def build(self, candidates, alerts, health) -> dict:
        # Track best non-alerted candidates so later runs can reveal false negatives / missed opportunities.
        self.db.cleanup_tracked_non_alerts(self.settings.tracked_non_alert_retention_days)
        alert_keys = {c.key() for c in alerts}
        self.db.track_top_non_alert_candidates(candidates, alert_keys, self.settings.top_rejected_track_limit)
        if self.settings.missed_opportunity_price_check_enabled:
            missed = self.missed_opportunities_with_price_lookup(candidates)
        else:
            missed = self.db.missed_opportunities(candidates, self.settings.missed_opportunity_gain_pct, self.settings.missed_opportunity_window_hours)
        diagnostics = {
            "scoring_profile": self.settings.scoring_profile,
            "dry_run_verbose": self.settings.dry_run_verbose,
            "rejected_reasons_summary": self.rejected_reasons_summary(candidates),
            "watchlist_upgrades": self.watchlist_upgrades(candidates),
            "missed_opportunities": missed,
            "data_quality_summary": self.data_quality_summary(candidates),
            "unlock_risk_summary": self.unlock_risk_summary(candidates),
        }
        if self.settings.dry_run_verbose:
            diagnostics["verbose"] = self.dry_run_verbose_summary(candidates, health)
        return diagnostics

    def missed_opportunities_with_price_lookup(self, current_candidates) -> list[dict]:
        """Check tracked non-alerts using current scan first, then direct price APIs.

        This avoids missing false negatives simply because the token did not reappear
        in the current scanner prefilter. The method is intentionally capped to avoid
        excessive requests on GitHub Actions.
        """
        current = {c.key(): c for c in current_candidates if c.price_usd and c.price_usd > 0}
        rows = self.db.conn.execute("""
            SELECT * FROM tracked_non_alerts
            WHERE datetime(created_at, '+' || ? || ' hours') <= datetime('now')
            ORDER BY datetime(created_at) ASC
            LIMIT ?
        """, (int(self.settings.missed_opportunity_window_hours), int(self.settings.missed_opportunity_price_check_limit))).fetchall()
        missed = []
        for row in rows:
            if not row["price_at_track"]:
                continue
            payload = {}
            try:
                payload = json.loads(row["payload"] or "{}")
            except Exception:
                payload = {}

            current_candidate = current.get(row["candidate_key"])
            current_price = current_candidate.price_usd if current_candidate else None
            current_status = current_candidate.status if current_candidate else "not_in_current_scan"
            current_score = round(current_candidate.final_score, 2) if current_candidate else None
            url = current_candidate.url if current_candidate else payload.get("url")
            price_source = "current_scan" if current_candidate else "direct_lookup"

            if not current_price:
                current_price = self._lookup_current_price(payload)

            self.db.conn.execute("UPDATE tracked_non_alerts SET last_checked_at=datetime('now') WHERE candidate_key=?", (row["candidate_key"],))
            if not current_price:
                continue

            change = ((float(current_price) - float(row["price_at_track"])) / float(row["price_at_track"])) * 100
            if change >= self.settings.missed_opportunity_gain_pct:
                missed.append({
                    "symbol": row["symbol"],
                    "source": row["source"],
                    "status_at_track": row["status_at_track"],
                    "current_status": current_status,
                    "price_at_track": row["price_at_track"],
                    "current_price": current_price,
                    "change_pct": round(change, 2),
                    "score_at_track": row["best_score_at_track"],
                    "current_score": current_score,
                    "price_source": price_source,
                    "url": url,
                })
        self.db.conn.commit()
        missed.sort(key=lambda x: x["change_pct"], reverse=True)
        return missed[:50]

    def _lookup_current_price(self, payload: dict) -> float | None:
        try:
            if payload.get("source") == "CEX" and payload.get("symbol"):
                data = get_json(self.session, BINANCE_PRICE_URL, params={"symbol": payload.get("symbol")}, timeout=(3, 8))
                return float(data.get("price"))
            if payload.get("source") == "DEX" and payload.get("chain") and payload.get("pair_address"):
                url = DEX_PAIR_URL.format(chain=payload.get("chain"), pair=payload.get("pair_address"))
                data = get_json(self.session, url, timeout=(3, 8))
                pair = (data.get("pair") or {}) if isinstance(data, dict) else {}
                price = pair.get("priceUsd")
                return float(price) if price else None
        except Exception:
            return None
        return None


    def data_quality_summary(self, candidates) -> dict:
        if not candidates:
            return {"avg": None, "low_quality_count": 0}
        avg = sum(c.data_quality_score for c in candidates) / len(candidates)
        low = len([c for c in candidates if c.data_quality_score < self.settings.min_data_quality_for_alert])
        return {"avg": round(avg, 2), "low_quality_count": low, "min_required_for_alert": self.settings.min_data_quality_for_alert}

    def unlock_risk_summary(self, candidates) -> list[dict]:
        rows = []
        for c in candidates:
            if c.unlock_risk_score:
                rows.append({"symbol": c.symbol, "source": c.source, "unlock_risk_score": c.unlock_risk_score, "flags": c.unlock_flags[:5]})
        return sorted(rows, key=lambda x: x["unlock_risk_score"], reverse=True)[:25]
