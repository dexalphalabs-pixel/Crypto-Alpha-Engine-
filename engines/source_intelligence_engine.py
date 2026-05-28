from __future__ import annotations

from collections import Counter
from typing import Iterable


class SourceIntelligenceEngine:
    """Assess data-source coverage and signal confidence.

    This layer is deliberately separate from alpha/risk scoring. A token may look
    attractive while the evidence is weak. Strong alert statuses should require
    both good score and good source confidence.
    """

    MARKET_SOURCES = {
        "DEX/DexScreener",
        "CEX/Binance",
        "CEX/OKXFallback",
        "CEX/BybitFallback",
        "CEX/Fallbacks",
        "MarketContext/Binance",
        "MarketContext/CoinGeckoFallback",
        "MarketContext/BybitFallback",
    }

    def __init__(self, settings):
        self.settings = settings
        self.health = {
            "source": "SourceIntelligence",
            "status": "OK",
            "errors": [],
            "coverage_score": 0,
            "active_sources": 0,
            "failed_sources": 0,
            "degraded_sources": 0,
        }
        self.provider_matrix: list[dict] = []
        self.coverage_summary: dict = {}

    def enrich(self, candidates: list, health: list[dict]) -> list:
        matrix = self._provider_matrix(health)
        self.provider_matrix = matrix
        self.coverage_summary = self._coverage_summary(matrix)
        for c in candidates:
            self._assign_candidate_confidence(c, matrix)
        self.health.update({
            "coverage_score": self.coverage_summary.get("coverage_score", 0),
            "active_sources": self.coverage_summary.get("active_sources", 0),
            "failed_sources": self.coverage_summary.get("failed_sources", 0),
            "degraded_sources": self.coverage_summary.get("degraded_sources", 0),
        })
        if self.coverage_summary.get("coverage_score", 0) < self.settings.min_source_coverage_score:
            self.health["status"] = "DEGRADED"
        return candidates

    def diagnostics(self) -> dict:
        return {
            "provider_matrix": self.provider_matrix,
            "source_coverage_summary": self.coverage_summary,
            "source_confidence_distribution": self.coverage_summary.get("confidence_distribution", {}),
        }

    def _provider_matrix(self, health: Iterable[dict]) -> list[dict]:
        rows = []
        for h in health:
            source = h.get("source", "UNKNOWN")
            status = h.get("status", "UNKNOWN")
            errors = h.get("errors") or []
            blocked = any("451" in str(e) for e in errors)
            rows.append({
                "source": source,
                "status": "BLOCKED_451" if blocked and status == "FAILED" else status,
                "raw_status": status,
                "available": status in {"OK", "DEGRADED"},
                "reliability_score": self._reliability_score(status, blocked),
                "blocked_451": blocked,
                "errors_count": len(errors),
                "note": self._short_note(h, blocked),
            })
        return rows

    def _coverage_summary(self, matrix: list[dict]) -> dict:
        active = [r for r in matrix if r["available"]]
        failed = [r for r in matrix if r["raw_status"] == "FAILED"]
        degraded = [r for r in matrix if r["raw_status"] == "DEGRADED"]
        score = 0
        # Coverage dimensions. Keep it simple and auditable.
        if any(r["source"] == "DEX/DexScreener" and r["available"] for r in matrix):
            score += 25
        if any(r["source"].startswith("CEX/") and r["available"] for r in matrix):
            score += 25
        if any(r["source"].startswith("MarketContext/") and r["available"] for r in matrix):
            score += 20
        if any(r["source"].startswith("Security/") and r["available"] for r in matrix):
            score += 20
        if any(r["source"].startswith("News/") and r["available"] for r in matrix):
            score += 5
        if any(r["source"].startswith("UnlockCalendar/") and r["available"] for r in matrix):
            score += 5
        score = min(100, score)
        return {
            "coverage_score": score,
            "active_sources": len(active),
            "failed_sources": len(failed),
            "degraded_sources": len(degraded),
            "active_source_names": [r["source"] for r in active],
            "failed_source_names": [r["source"] for r in failed],
            "degraded_source_names": [r["source"] for r in degraded],
            "blocked_451_sources": [r["source"] for r in matrix if r.get("blocked_451")],
        }

    def _assign_candidate_confidence(self, c, matrix: list[dict]) -> None:
        score = 0
        reasons = []
        missing = []
        active = []

        dex_ok = self._available(matrix, "DEX/DexScreener")
        cex_ok = any(r["source"].startswith("CEX/") and r["available"] for r in matrix)
        context_ok = any(r["source"].startswith("MarketContext/") and r["available"] for r in matrix)
        security_ok = any(r["source"].startswith("Security/") and r["available"] for r in matrix)
        news_ok = any(r["source"].startswith("News/") and r["available"] for r in matrix)

        if c.source == "DEX":
            if dex_ok:
                score += 28; reasons.append("DEX market data OK"); active.append("DexScreener")
            else:
                missing.append("DEX market data")
            if c.security_verified and (c.security_score or 0) >= self.settings.min_security_score_for_high_confidence:
                score += 30; reasons.append("contract security confirmed"); active.append(c.security_source or "security")
            elif security_ok and c.security_score is not None:
                score += 15; reasons.append("partial contract security")
            else:
                missing.append("contract security confirmation")
            if context_ok:
                score += 13; reasons.append("market context available"); active.append("market context")
            else:
                missing.append("market context")
            if c.data_quality_score >= 80:
                score += 14; reasons.append("high data quality")
            else:
                missing.append("high data quality")
            if c.volume_24h_usd >= self.settings.dex_min_volume_24h_usd and c.txns_24h >= 100:
                score += 10; reasons.append("DEX volume/transactions sufficient")
            if news_ok and c.news_hits:
                score += 5; reasons.append("news/event context matched")
        else:
            if cex_ok:
                score += 32; reasons.append("CEX market data OK"); active.append(c.exchange or "CEX")
            else:
                missing.append("CEX market data")
            if context_ok:
                score += 20; reasons.append("BTC/ETH market context available"); active.append("market context")
            else:
                missing.append("BTC/ETH market context")
            if c.klines_available:
                score += 17; reasons.append("1h/4h klines available")
            else:
                missing.append("1h/4h klines")
            if c.relative_strength_btc_24h is not None or c.relative_strength_eth_24h is not None:
                score += 11; reasons.append("relative strength available")
            else:
                missing.append("relative strength")
            if c.data_quality_score >= 80:
                score += 10; reasons.append("high data quality")
            if c.derivatives_available:
                score += 10; reasons.append("derivatives context available")

        score = max(0, min(100, score))
        if score >= self.settings.source_confidence_high_score:
            level = "HIGH"
        elif score >= self.settings.source_confidence_medium_score:
            level = "MEDIUM"
        elif score >= self.settings.source_confidence_low_score:
            level = "LOW"
        else:
            level = "NO_CONFIDENCE"

        # Hard downgrades for critical evidence gaps.
        if c.source == "DEX" and not c.security_verified:
            if level == "HIGH":
                level = "MEDIUM"
            elif level == "MEDIUM" and self.settings.source_confidence_security_required_for_medium:
                level = "LOW"
        if c.source == "CEX" and not cex_ok:
            level = "NO_CONFIDENCE"

        c.source_confidence = level
        c.source_confidence_score = score
        c.source_confidence_reasons = sorted(set(reasons))
        c.source_missing = sorted(set(missing))
        c.active_sources = sorted(set(active))
        c.source_coverage_score = self.coverage_summary.get("coverage_score", 0)
        c.source_agreement_score = self._agreement_score(c)
        if level in {"LOW", "NO_CONFIDENCE"}:
            c.risks = sorted(set(c.risks + [f"niska wiarygodność źródeł: {level}"]))
        else:
            c.reasons = sorted(set(c.reasons + [f"source confidence: {level} ({score:.0f}/100)"]))

    def _agreement_score(self, c) -> float:
        # A lightweight consistency proxy: positive when relative strength and 24h trend agree.
        if c.relative_strength_btc_24h is None:
            return 50.0 if c.source == "DEX" else 40.0
        same_direction = (c.price_change_24h_pct >= 0 and c.relative_strength_btc_24h >= -2) or (c.price_change_24h_pct < 0 and c.relative_strength_btc_24h < 0)
        return 80.0 if same_direction else 45.0

    def _available(self, matrix: list[dict], source: str) -> bool:
        return any(r["source"] == source and r["available"] for r in matrix)

    def _reliability_score(self, status: str, blocked: bool) -> int:
        if blocked:
            return 0
        if status == "OK":
            return 100
        if status == "DEGRADED":
            return 55
        if status == "FAILED":
            return 0
        if status in {"DISABLED", "NOT_RUN"}:
            return 0
        return 25

    def _short_note(self, h: dict, blocked: bool) -> str:
        if blocked:
            return "blocked/legal/IP 451"
        errors = h.get("errors") or []
        if errors:
            return str(errors[0])[:120]
        return ""
