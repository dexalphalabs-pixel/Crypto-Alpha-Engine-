
from __future__ import annotations

from statistics import pstdev
from utils.http_client import build_session, get_json
from utils.validators import safe_float, clamp

BINANCE_24H_URL = "https://api.binance.com/api/v3/ticker/24hr"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"


class MarketContextEngine:
    """Adds BTC/ETH market-regime context to every candidate.

    This does not predict the market. It prevents altcoin signals from being treated the same during
    calm risk-on markets and violent BTC selloffs.
    """

    def __init__(self, settings):
        self.settings = settings
        self.session = build_session()
        self.health = {"source": "MarketContext/Binance", "status": "NOT_RUN", "errors": [], "regime": None}

    def enrich(self, candidates):
        if not self.settings.market_context_enabled:
            self.health["status"] = "DISABLED"
            return candidates
        context = self._fetch_context()
        self.health.update(context)
        self.health["status"] = "OK" if not self.health["errors"] else "DEGRADED"
        regime = context.get("regime") or "UNKNOWN"
        for c in candidates:
            c.market_regime = regime
            c.btc_change_24h_pct = context.get("btc_change_24h_pct")
            c.eth_change_24h_pct = context.get("eth_change_24h_pct")
            c.btc_volatility_24h_pct = context.get("btc_volatility_24h_pct")
            adjustment = 0.0
            if regime == "RISK_OFF":
                adjustment -= self.settings.market_context_penalty
                c.risks.append("market regime risk-off: BTC pressure")
                if c.source == "CEX" and c.relative_strength_btc_24h is not None and c.relative_strength_btc_24h < 0:
                    adjustment -= 3
                    c.risks.append("alt słabszy od BTC podczas risk-off")
            elif regime == "HIGH_VOLATILITY":
                adjustment -= self.settings.market_context_penalty * 0.75
                c.risks.append("wysoka zmienność BTC — niższa wiarygodność momentum")
            elif regime == "RISK_ON":
                adjustment += self.settings.market_context_bonus
                c.reasons.append("market regime risk-on")
            c.market_context_score = adjustment
            c.final_score = clamp(c.final_score + adjustment)
            if adjustment < 0:
                c.risk_score = clamp(c.risk_score + abs(adjustment) * 0.75)
        return candidates

    def _fetch_context(self) -> dict:
        out = {"btc_change_24h_pct": None, "eth_change_24h_pct": None, "btc_volatility_24h_pct": None, "regime": "UNKNOWN"}
        try:
            tickers = get_json(self.session, BINANCE_24H_URL, timeout=(5, 12))
            if isinstance(tickers, list):
                for t in tickers:
                    if t.get("symbol") == "BTCUSDT":
                        out["btc_change_24h_pct"] = safe_float(t.get("priceChangePercent"))
                    elif t.get("symbol") == "ETHUSDT":
                        out["eth_change_24h_pct"] = safe_float(t.get("priceChangePercent"))
        except Exception as exc:
            self.health["errors"].append(f"24h context: {exc}")
        try:
            klines = get_json(self.session, BINANCE_KLINES_URL, params={"symbol": "BTCUSDT", "interval": "1h", "limit": 25}, timeout=(5, 12))
            returns = []
            if isinstance(klines, list) and len(klines) >= 10:
                closes = [safe_float(k[4]) for k in klines]
                for prev, cur in zip(closes[:-1], closes[1:]):
                    if prev:
                        returns.append(((cur - prev) / prev) * 100)
            if returns:
                out["btc_volatility_24h_pct"] = pstdev(returns) * (24 ** 0.5)
        except Exception as exc:
            self.health["errors"].append(f"BTC volatility: {exc}")
        btc = out.get("btc_change_24h_pct")
        eth = out.get("eth_change_24h_pct")
        vol = out.get("btc_volatility_24h_pct")
        if btc is not None and btc <= self.settings.market_context_btc_caution_24h_pct:
            out["regime"] = "RISK_OFF"
        elif vol is not None and vol >= self.settings.market_context_high_volatility_pct:
            out["regime"] = "HIGH_VOLATILITY"
        elif btc is not None and eth is not None and btc >= self.settings.market_context_btc_risk_on_24h_pct and eth >= 0:
            out["regime"] = "RISK_ON"
        elif btc is not None:
            out["regime"] = "NEUTRAL"
        return out
