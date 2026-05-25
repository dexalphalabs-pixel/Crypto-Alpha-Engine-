import math
from utils.validators import clamp


def threshold_log_score(value: float, minimum: float, strong: float, cap: float) -> float:
    """Score starts near 0 at minimum and reaches cap near strong threshold."""
    if value < minimum or minimum <= 0 or strong <= minimum:
        return 0.0
    ratio = value / minimum
    strong_ratio = strong / minimum
    return clamp((math.log10(ratio + 1) / math.log10(strong_ratio + 1)) * cap, 0, cap)


def positive(value: float | None, factor: float, low: float, high: float) -> float:
    if value is None:
        return 0.0
    return clamp(value * factor, low, high)


class ScoringEngine:
    def __init__(self, settings):
        self.settings = settings

    def score(self, candidate):
        if candidate.source == "DEX":
            return self._score_dex(candidate)
        return self._score_cex(candidate)

    def _score_dex(self, c):
        reasons = []
        risks = list(c.risks)

        liquidity_points = threshold_log_score(c.liquidity_usd, self.settings.dex_min_liquidity_usd, self.settings.dex_strong_liquidity_usd, 24)
        volume_points = threshold_log_score(c.volume_24h_usd, self.settings.dex_min_volume_24h_usd, self.settings.dex_strong_volume_24h_usd, 23)
        txn_points = threshold_log_score(c.txns_24h, 100, 3000, 14)
        momentum_points = clamp(c.price_change_24h_pct / 2, -20, 17) + clamp(c.price_change_1h_pct, -8, 8)
        freshness_points = 9 if c.age_hours is not None and c.age_hours <= self.settings.dex_max_age_hours else 0
        narrative_points = min(7, len(c.narrative_tags) * 3.5)
        security_bonus = 0
        if c.security_score is not None:
            security_bonus = clamp((c.security_score - 55) / 5, -8, 9)

        c.alpha_score = clamp(liquidity_points + volume_points + txn_points + momentum_points + freshness_points + narrative_points + security_bonus)

        risk = 0.0
        if c.liquidity_usd < self.settings.dex_min_liquidity_usd:
            risk += 35
            risks.append("zbyt niska płynność DEX")
        if c.volume_24h_usd < self.settings.dex_min_volume_24h_usd:
            risk += 25
            risks.append("zbyt niski wolumen DEX")
        if not c.security_verified:
            missing_penalty = 28 if self.settings.security_conservative_missing_data else 18
            risk += missing_penalty
            risks.append("security niezweryfikowane lub niepełne")
        if c.security_score is not None and c.security_score < 55:
            risk += 35
            risks.append(f"niski security_score: {c.security_score:.0f}/100")
        if c.security_flags:
            risk += min(35, len(c.security_flags) * 8)
            risks.extend(c.security_flags[:6])
        if c.buy_tax_pct is not None and c.buy_tax_pct > self.settings.max_buy_tax_pct:
            risk += 16
            risks.append(f"wysoki buy tax: {c.buy_tax_pct:.2f}%")
        if c.sell_tax_pct is not None and c.sell_tax_pct > self.settings.max_sell_tax_pct:
            risk += 20
            risks.append(f"wysoki sell tax: {c.sell_tax_pct:.2f}%")
        if c.holder_count is not None and c.holder_count < self.settings.min_holder_count:
            risk += 12
            risks.append(f"mało holderów: {c.holder_count}")
        if c.age_hours is not None and c.age_hours < 2:
            risk += 15
            risks.append("bardzo świeży token")
        if c.price_change_24h_pct > self.settings.late_pump_24h_pct or c.price_change_4h_pct > self.settings.late_pump_4h_pct or c.price_change_1h_pct > self.settings.late_pump_1h_pct:
            risk += 25
            risks.append("możliwy late pump / pogoń za ruchem")
        if c.price_change_24h_pct < -35:
            risk += 22
            risks.append("silny spadek w 24h")
        if c.txns_24h < 100:
            risk += 15
            risks.append("mała liczba transakcji")
        if any(tag == "Meme" for tag in c.narrative_tags):
            risk += 8
            risks.append("narracja meme podwyższa ryzyko")
        if c.event_risk_score:
            risk += c.event_risk_score
            risks.extend(c.event_risk_flags[:5])
        if c.unlock_risk_score:
            risk += c.unlock_risk_score
            risks.extend(c.unlock_flags[:5])
        if c.data_quality_score < self.settings.min_data_quality_for_alert:
            risk += 12
            risks.extend(c.data_quality_flags[:5])

        c.risk_score = clamp(risk)
        c.tradability_score = clamp((liquidity_points * 1.45) + (volume_points * 1.25) + txn_points + max(0, security_bonus) - risk * 0.50)
        c.final_score = clamp(c.alpha_score * 0.55 + c.tradability_score * 0.35 - c.risk_score * 0.48 + 18)

        if c.liquidity_usd >= self.settings.dex_min_liquidity_usd:
            reasons.append("płynność powyżej minimum")
        if c.volume_24h_usd >= self.settings.dex_min_volume_24h_usd:
            reasons.append("wolumen powyżej minimum")
        if c.price_change_1h_pct > 3 or c.price_change_24h_pct > 10:
            reasons.append("dodatnie momentum")
        if c.security_verified:
            reasons.append(f"security layer pozytywny ({c.security_source}, score {c.security_score:.0f}/100)" if c.security_score is not None else "security layer pozytywny")
        if c.lp_locked:
            reasons.append("LP lock/burn wykryty proxy")
        if c.narrative_tags:
            reasons.append("wykryto narrację: " + ", ".join(c.narrative_tags))
        if c.news_hits:
            reasons.append("news/catalyst hits: " + " | ".join(c.news_hits[:2]))
        if c.data_quality_score >= 80:
            reasons.append(f"data quality OK: {c.data_quality_score:.0f}/100")
        if c.unlock_flags:
            risks.extend(c.unlock_flags[:5])

        c.reasons = sorted(set(reasons + c.reasons))
        c.risks = sorted(set(risks))
        c.status = self._status(c)
        return c

    def _score_cex(self, c):
        reasons = []
        risks = list(c.risks)

        volume_points = threshold_log_score(c.volume_24h_usd, self.settings.cex_min_quote_volume_usd, self.settings.cex_strong_quote_volume_usd, 31)
        activity_points = threshold_log_score(c.txns_24h, 10_000, 1_500_000, 12)
        momentum_1h = positive(c.price_change_1h_pct, 2.0, -10, 15)
        momentum_4h = positive(c.price_change_4h_pct, 1.6, -15, 22)
        momentum_24h = positive(c.price_change_24h_pct, 0.7, -15, 18)
        rs_btc_points = positive(c.relative_strength_btc_24h, 0.8, -8, 12)
        rs_eth_points = positive(c.relative_strength_eth_24h, 0.4, -5, 8)
        spread_points = 15
        if c.spread_pct is not None:
            spread_points = clamp(15 - c.spread_pct * 25, 0, 15)
        narrative_points = min(7, len(c.narrative_tags) * 3.5)
        volume_accel_points = 0
        if c.volume_change_1h_pct is not None and c.volume_change_1h_pct > 25:
            volume_accel_points += min(6, c.volume_change_1h_pct / 25)
        if c.volume_change_4h_pct is not None and c.volume_change_4h_pct > 25:
            volume_accel_points += min(6, c.volume_change_4h_pct / 25)
        derivatives_points = 0
        if c.derivatives_available and c.open_interest_usd and c.open_interest_usd >= self.settings.min_open_interest_usd_for_bonus:
            derivatives_points += min(8, math.log10(c.open_interest_usd / self.settings.min_open_interest_usd_for_bonus + 1) * 5)
        if c.funding_rate_pct is not None and abs(c.funding_rate_pct) <= self.settings.max_abs_funding_rate_pct:
            derivatives_points += 3
        if c.open_interest_change_4h_pct is not None and 3 <= c.open_interest_change_4h_pct <= 40:
            derivatives_points += min(7, c.open_interest_change_4h_pct / 5)

        c.alpha_score = clamp(volume_points + activity_points + momentum_1h + momentum_4h + momentum_24h + rs_btc_points + rs_eth_points + narrative_points + volume_accel_points + derivatives_points)

        risk = 0.0
        if c.volume_24h_usd < self.settings.cex_min_quote_volume_usd:
            risk += 28
            risks.append("niski wolumen CEX")
        if c.spread_pct is not None and c.spread_pct > self.settings.cex_max_spread_pct:
            risk += 25
            risks.append("wysoki spread")
        if c.price_change_24h_pct > self.settings.late_pump_24h_pct or c.price_change_4h_pct > self.settings.late_pump_4h_pct or c.price_change_1h_pct > self.settings.late_pump_1h_pct:
            risk += 25
            risks.append("late pump / chase risk")
        if c.price_change_24h_pct < -20 or c.price_change_4h_pct < -12:
            risk += 20
            risks.append("silny spadek")
        if c.relative_strength_btc_24h is not None and c.relative_strength_btc_24h < -5:
            risk += 10
            risks.append("słabszy niż BTC w 24h")
        if c.funding_rate_pct is not None and abs(c.funding_rate_pct) > self.settings.max_abs_funding_rate_pct:
            risk += 12
            risks.append(f"ekstremalny funding: {c.funding_rate_pct:.4f}%")
        if c.open_interest_change_4h_pct is not None and c.open_interest_change_4h_pct > 75:
            risk += 10
            risks.append(f"bardzo gwałtowny wzrost OI 4h: {c.open_interest_change_4h_pct:.1f}%")
        if any(tag == "Meme" for tag in c.narrative_tags):
            risk += 5
            risks.append("narracja meme podwyższa ryzyko")
        if c.event_risk_score:
            risk += c.event_risk_score
            risks.extend(c.event_risk_flags[:5])
        if c.unlock_risk_score:
            risk += c.unlock_risk_score
            risks.extend(c.unlock_flags[:5])
        if c.data_quality_score < self.settings.min_data_quality_for_alert:
            risk += 12
            risks.extend(c.data_quality_flags[:5])

        c.risk_score = clamp(risk)
        c.tradability_score = clamp(volume_points * 1.45 + spread_points * 2 + activity_points + derivatives_points - risk * 0.28)
        c.final_score = clamp(c.alpha_score * 0.62 + c.tradability_score * 0.33 - c.risk_score * 0.42 + 10)

        if c.volume_24h_usd >= self.settings.cex_min_quote_volume_usd:
            reasons.append("wolumen CEX powyżej minimum")
        if c.price_change_1h_pct > 1.5 or c.price_change_4h_pct > 4:
            reasons.append("momentum 1h/4h")
        if c.relative_strength_btc_24h is not None and c.relative_strength_btc_24h > 3:
            reasons.append(f"silniejszy od BTC o {c.relative_strength_btc_24h:.1f} pp w 24h")
        if c.spread_pct is not None and c.spread_pct <= self.settings.cex_max_spread_pct:
            reasons.append("akceptowalny spread")
        if c.volume_change_1h_pct is not None and c.volume_change_1h_pct > 25:
            reasons.append("przyspieszenie wolumenu 1h")
        if c.derivatives_available:
            oi = "brak" if c.open_interest_usd is None else f"${c.open_interest_usd:,.0f}"
            fr = "brak" if c.funding_rate_pct is None else f"{c.funding_rate_pct:.4f}%"
            oi_trend = "brak" if c.open_interest_change_4h_pct is None else f"{c.open_interest_change_4h_pct:.1f}% 4h"
            reasons.append(f"futures: OI {oi}, OI trend {oi_trend}, funding {fr}")
        if c.narrative_tags:
            reasons.append("wykryto narrację: " + ", ".join(c.narrative_tags))
        if c.news_hits:
            reasons.append("news/catalyst hits: " + " | ".join(c.news_hits[:2]))

        c.reasons = sorted(set(reasons + c.reasons))
        c.risks = sorted(set(risks))
        c.status = self._status(c)
        return c

    def refresh_status(self, candidate):
        """Recalculate status after downstream engines adjust score/risk.

        Used after market-context or other post-scoring layers so alerts cannot keep
        stale HIGH_CONVICTION/MOMENTUM status after a risk penalty.
        """
        candidate.status = self._status(candidate)
        return candidate

    def _profile_thresholds(self):
        alert = self.settings.alert_min_final_score
        watch = self.settings.watchlist_min_score
        risk_cap = 55
        high_conviction = 82
        if self.settings.scoring_profile == "conservative":
            return alert + 5, watch + 5, risk_cap - 5, high_conviction + 4
        if self.settings.scoring_profile == "exploratory":
            return alert - 8, watch - 10, risk_cap + 5, high_conviction
        return alert, watch, risk_cap, high_conviction

    def _status(self, c):
        alert_threshold, watch_threshold, alert_risk_cap, high_conviction_threshold = self._profile_thresholds()
        if c.source == "DEX" and c.risk_score > self.settings.dex_max_risk_score:
            return "REJECTED_HIGH_RISK"
        if c.risk_score >= 75:
            return "REJECTED_HIGH_RISK"
        if c.event_risk_score >= 40:
            return "REJECTED_EVENT_RISK"
        if c.data_quality_score < self.settings.min_data_quality_for_alert and c.final_score >= alert_threshold:
            return "WATCHLIST"
        if c.final_score >= alert_threshold and c.risk_score <= alert_risk_cap:
            # DEX cannot be high conviction without stronger external contract security.
            # Solana currently has only fallback security in this MVP, so keep it watchlist-only.
            if c.source == "DEX" and c.chain == "solana" and c.security_source != "solana_security":
                return "WATCHLIST"
            if c.source == "DEX":
                return "MOMENTUM_ALERT" if c.security_verified and (c.security_score or 0) >= 75 else "WATCHLIST"
            return "HIGH_CONVICTION" if c.final_score >= high_conviction_threshold and c.risk_score <= 35 else "MOMENTUM_ALERT"
        if c.final_score >= watch_threshold:
            return "WATCHLIST"
        return "REJECTED_LOW_SCORE"
