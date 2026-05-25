
from __future__ import annotations

from utils.validators import clamp


class DataQualityEngine:
    """Scores whether a candidate has enough trustworthy data to justify an alert."""

    def __init__(self, settings):
        self.settings = settings
        self.health = {"source": "DataQuality", "status": "OK", "errors": []}

    def enrich(self, candidates, source_health=None):
        source_health = source_health or []
        failed_market = {h.get("source") for h in source_health if h.get("status") == "FAILED" and h.get("source") in {"DEX/DexScreener", "CEX/Binance"}}
        for c in candidates:
            score = 100.0
            flags = []
            if c.source == "DEX":
                if not c.security_verified:
                    score -= 28
                    flags.append("DEX security missing")
                if c.security_score is None:
                    score -= 12
                    flags.append("no security_score")
                if c.holder_count is None:
                    score -= 8
                    flags.append("holder_count missing")
                if c.chain == "solana" and c.security_source != "solana_security":
                    score -= 10
                    flags.append("Solana security unsupported/fallback")
                if "DEX/DexScreener" in failed_market:
                    score -= 40
                    flags.append("DEX source failed")
            else:
                if not getattr(c, "klines_available", False):
                    score -= 10
                    flags.append("klines data unavailable")
                if c.spread_pct is None:
                    score -= 8
                    flags.append("spread missing")
                if not c.derivatives_available:
                    score -= 4
                    flags.append("futures metrics unavailable")
                if "CEX/Binance" in failed_market:
                    score -= 40
                    flags.append("CEX source failed")
            if c.price_usd is None or c.price_usd <= 0:
                score -= 25
                flags.append("invalid price")
            if c.volume_24h_usd <= 0:
                score -= 18
                flags.append("invalid volume")
            c.data_quality_score = clamp(score)
            c.data_quality_flags = flags
            if c.data_quality_score < self.settings.min_data_quality_for_alert:
                c.risks.append(f"niska jakość danych: {c.data_quality_score:.0f}/100")
        return candidates
