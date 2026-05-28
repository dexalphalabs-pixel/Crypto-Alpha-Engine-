from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Candidate:
    source: str
    symbol: str
    name: str
    chain: str | None
    address: str | None
    pair_address: str | None
    exchange: str | None
    url: str | None
    price_usd: float
    liquidity_usd: float
    volume_24h_usd: float
    price_change_1h_pct: float
    price_change_4h_pct: float
    price_change_24h_pct: float
    txns_24h: int
    age_hours: float | None
    spread_pct: float | None = None
    quote_asset: str | None = None
    relative_strength_btc_24h: float | None = None
    relative_strength_eth_24h: float | None = None
    volume_change_1h_pct: float | None = None
    volume_change_4h_pct: float | None = None
    klines_available: bool = False

    # Security layer. For CEX, this is normally treated as externally listed/verified.
    security_verified: bool = False
    security_score: float | None = None
    security_source: str | None = None
    security_flags: list[str] = field(default_factory=list)
    buy_tax_pct: float | None = None
    sell_tax_pct: float | None = None
    holder_count: int | None = None
    owner_renounced: bool | None = None
    lp_locked: bool | None = None

    # Futures / derivatives momentum layer, mainly for Binance USDT perpetuals.
    funding_rate_pct: float | None = None
    open_interest_usd: float | None = None
    open_interest_contracts: float | None = None
    open_interest_change_4h_pct: float | None = None
    funding_rate_change_hint: str | None = None
    derivatives_available: bool = False

    # News/event risk layer.
    event_risk_score: float = 0.0
    event_risk_flags: list[str] = field(default_factory=list)
    news_hits: list[str] = field(default_factory=list)

    # Market regime/context layer.
    market_regime: str | None = None
    market_context_score: float = 0.0
    btc_change_24h_pct: float | None = None
    eth_change_24h_pct: float | None = None
    btc_volatility_24h_pct: float | None = None

    # Data quality and scheduled event layer.
    data_quality_score: float = 100.0
    data_quality_flags: list[str] = field(default_factory=list)
    unlock_risk_score: float = 0.0
    unlock_flags: list[str] = field(default_factory=list)

    raw: dict[str, Any] = field(default_factory=dict)

    alpha_score: float = 0.0
    risk_score: float = 0.0
    tradability_score: float = 0.0
    final_score: float = 0.0
    status: str = "UNSCORED"
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    narrative_tags: list[str] = field(default_factory=list)

    # Source intelligence layer. Kept separate from alpha/risk scoring.
    source_confidence: str = "UNKNOWN"
    source_confidence_score: float = 0.0
    source_confidence_reasons: list[str] = field(default_factory=list)
    source_missing: list[str] = field(default_factory=list)
    active_sources: list[str] = field(default_factory=list)
    source_coverage_score: float = 0.0
    source_agreement_score: float = 0.0

    def key(self) -> str:
        if self.address:
            return f"{self.source}:{self.chain}:{self.address}".lower()
        return f"{self.source}:{self.exchange}:{self.symbol}".lower()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
