import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def _csv(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    safe_mode: bool = field(default_factory=lambda: _bool("SAFE_MODE", True))
    run_mode: str = field(default_factory=lambda: os.getenv("RUN_MODE", "full").strip().lower())
    output_dir: str = field(default_factory=lambda: os.getenv("OUTPUT_DIR", "outputs"))
    database_path: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", "outputs/crypto_alpha.db"))
    persistent_storage_mode: str = field(default_factory=lambda: os.getenv("PERSISTENT_STORAGE_MODE", "github_cache").strip().lower())
    dry_run_verbose: bool = field(default_factory=lambda: _bool("DRY_RUN_VERBOSE", False))
    scoring_profile: str = field(default_factory=lambda: os.getenv("SCORING_PROFILE", "balanced").strip().lower())
    api_circuit_breaker_failures: int = field(default_factory=lambda: _int("API_CIRCUIT_BREAKER_FAILURES", 2))
    global_api_failure_fast_mode: bool = field(default_factory=lambda: _bool("GLOBAL_API_FAILURE_FAST_MODE", True))
    skip_secondary_sources_if_market_data_failed: bool = field(default_factory=lambda: _bool("SKIP_SECONDARY_SOURCES_IF_MARKET_DATA_FAILED", True))

    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    send_telegram_summary: bool = field(default_factory=lambda: _bool("SEND_TELEGRAM_SUMMARY", True))
    send_telegram_alerts: bool = field(default_factory=lambda: _bool("SEND_TELEGRAM_ALERTS", True))
    send_telegram_daily_digest: bool = field(default_factory=lambda: _bool("SEND_TELEGRAM_DAILY_DIGEST", True))
    digest_mode: str = field(default_factory=lambda: os.getenv("DIGEST_MODE", "daily").strip().lower())
    digest_hour_utc: int = field(default_factory=lambda: _int("DIGEST_HOUR_UTC", 18))
    digest_min_interval_hours: int = field(default_factory=lambda: _int("DIGEST_MIN_INTERVAL_HOURS", 20))
    github_run_url: str = field(default_factory=lambda: os.getenv("GITHUB_RUN_URL", ""))
    instant_alert_statuses: list[str] = field(default_factory=lambda: _csv("INSTANT_ALERT_STATUSES", "HIGH_CONVICTION"))

    dex_enabled: bool = field(default_factory=lambda: _bool("DEX_ENABLED", True))
    dex_chains: list[str] = field(default_factory=lambda: _csv("DEX_CHAINS", "ethereum,bsc,base,solana,arbitrum,polygon"))
    dex_trending_queries: list[str] = field(default_factory=lambda: _csv("DEX_TRENDING_QUERIES", "AI,RWA,DePIN,Layer2,gaming,defi"))
    dex_min_liquidity_usd: float = field(default_factory=lambda: _float("DEX_MIN_LIQUIDITY_USD", 25000))
    dex_strong_liquidity_usd: float = field(default_factory=lambda: _float("DEX_STRONG_LIQUIDITY_USD", 250000))
    dex_min_volume_24h_usd: float = field(default_factory=lambda: _float("DEX_MIN_VOLUME_24H_USD", 15000))
    dex_strong_volume_24h_usd: float = field(default_factory=lambda: _float("DEX_STRONG_VOLUME_24H_USD", 250000))
    dex_max_age_hours: int = field(default_factory=lambda: _int("DEX_MAX_AGE_HOURS", 168))
    dex_max_risk_score: float = field(default_factory=lambda: _float("DEX_MAX_RISK_SCORE", 65))

    security_enabled: bool = field(default_factory=lambda: _bool("SECURITY_ENABLED", True))
    security_max_dex_checks: int = field(default_factory=lambda: _int("SECURITY_MAX_DEX_CHECKS", 80))
    security_conservative_missing_data: bool = field(default_factory=lambda: _bool("SECURITY_CONSERVATIVE_MISSING_DATA", True))
    max_buy_tax_pct: float = field(default_factory=lambda: _float("MAX_BUY_TAX_PCT", 8.0))
    max_sell_tax_pct: float = field(default_factory=lambda: _float("MAX_SELL_TAX_PCT", 8.0))
    min_holder_count: int = field(default_factory=lambda: _int("MIN_HOLDER_COUNT", 80))

    cex_enabled: bool = field(default_factory=lambda: _bool("CEX_ENABLED", True))
    cex_quotes: list[str] = field(default_factory=lambda: _csv("CEX_QUOTES", "USDT"))
    cex_min_quote_volume_usd: float = field(default_factory=lambda: _float("CEX_MIN_QUOTE_VOLUME_USD", 5_000_000))
    cex_strong_quote_volume_usd: float = field(default_factory=lambda: _float("CEX_STRONG_QUOTE_VOLUME_USD", 100_000_000))
    cex_max_spread_pct: float = field(default_factory=lambda: _float("CEX_MAX_SPREAD_PCT", 0.35))
    cex_top_limit: int = field(default_factory=lambda: _int("CEX_TOP_LIMIT", 150))
    cex_klines_limit: int = field(default_factory=lambda: _int("CEX_KLINES_LIMIT", 80))
    cex_klines_prefilter_limit: int = field(default_factory=lambda: _int("CEX_KLINES_PREFILTER_LIMIT", 80))
    cex_futures_prefilter_limit: int = field(default_factory=lambda: _int("CEX_FUTURES_PREFILTER_LIMIT", 30))

    futures_enabled: bool = field(default_factory=lambda: _bool("FUTURES_ENABLED", True))
    futures_metrics_limit: int = field(default_factory=lambda: _int("FUTURES_METRICS_LIMIT", 60))
    max_abs_funding_rate_pct: float = field(default_factory=lambda: _float("MAX_ABS_FUNDING_RATE_PCT", 0.08))
    min_open_interest_usd_for_bonus: float = field(default_factory=lambda: _float("MIN_OPEN_INTEREST_USD_FOR_BONUS", 10_000_000))

    news_risk_enabled: bool = field(default_factory=lambda: _bool("NEWS_RISK_ENABLED", True))
    news_risk_keywords: list[str] = field(default_factory=lambda: _csv("NEWS_RISK_KEYWORDS", "hack,exploit,delist,delisting,lawsuit,sec,investigation,unlock,token unlock,bridge exploit,security incident"))
    news_positive_keywords: list[str] = field(default_factory=lambda: _csv("NEWS_POSITIVE_KEYWORDS", "listing,launch,partnership,integrates,integration,airdrop,mainnet,upgrade"))
    binance_announcements_enabled: bool = field(default_factory=lambda: _bool("BINANCE_ANNOUNCEMENTS_ENABLED", True))

    alert_min_final_score: float = field(default_factory=lambda: _float("ALERT_MIN_FINAL_SCORE", 70))
    watchlist_min_score: float = field(default_factory=lambda: _float("WATCHLIST_MIN_SCORE", 50))
    alert_cooldown_hours: int = field(default_factory=lambda: _int("ALERT_COOLDOWN_HOURS", 12))
    performance_windows: list[int] = field(default_factory=lambda: [int(x) for x in _csv("PERFORMANCE_WINDOWS", "1,4,24,168")])
    performance_use_cex_historical_klines: bool = field(default_factory=lambda: _bool("PERFORMANCE_USE_CEX_HISTORICAL_KLINES", True))
    top_rejected_track_limit: int = field(default_factory=lambda: _int("TOP_REJECTED_TRACK_LIMIT", 50))
    missed_opportunity_gain_pct: float = field(default_factory=lambda: _float("MISSED_OPPORTUNITY_GAIN_PCT", 12.0))
    missed_opportunity_window_hours: int = field(default_factory=lambda: _int("MISSED_OPPORTUNITY_WINDOW_HOURS", 24))
    missed_opportunity_price_check_enabled: bool = field(default_factory=lambda: _bool("MISSED_OPPORTUNITY_PRICE_CHECK_ENABLED", True))
    missed_opportunity_price_check_limit: int = field(default_factory=lambda: _int("MISSED_OPPORTUNITY_PRICE_CHECK_LIMIT", 25))
    tracked_non_alert_retention_days: int = field(default_factory=lambda: _int("TRACKED_NON_ALERT_RETENTION_DAYS", 30))

    market_context_enabled: bool = field(default_factory=lambda: _bool("MARKET_CONTEXT_ENABLED", True))
    market_context_btc_caution_24h_pct: float = field(default_factory=lambda: _float("MARKET_CONTEXT_BTC_CAUTION_24H_PCT", -3.0))
    market_context_btc_risk_on_24h_pct: float = field(default_factory=lambda: _float("MARKET_CONTEXT_BTC_RISK_ON_24H_PCT", 0.5))
    market_context_high_volatility_pct: float = field(default_factory=lambda: _float("MARKET_CONTEXT_HIGH_VOLATILITY_PCT", 5.0))
    market_context_penalty: float = field(default_factory=lambda: _float("MARKET_CONTEXT_PENALTY", 6.0))
    market_context_bonus: float = field(default_factory=lambda: _float("MARKET_CONTEXT_BONUS", 3.0))
    late_pump_1h_pct: float = field(default_factory=lambda: _float("LATE_PUMP_1H_PCT", 10.0))
    late_pump_4h_pct: float = field(default_factory=lambda: _float("LATE_PUMP_4H_PCT", 25.0))
    late_pump_24h_pct: float = field(default_factory=lambda: _float("LATE_PUMP_24H_PCT", 60.0))

    data_quality_enabled: bool = field(default_factory=lambda: _bool("DATA_QUALITY_ENABLED", True))
    min_data_quality_for_alert: float = field(default_factory=lambda: _float("MIN_DATA_QUALITY_FOR_ALERT", 55.0))
    unlock_risk_enabled: bool = field(default_factory=lambda: _bool("UNLOCK_RISK_ENABLED", True))
    token_unlocks_csv: str = field(default_factory=lambda: os.getenv("TOKEN_UNLOCKS_CSV", "data/token_unlocks.csv"))
    unlock_risk_lookahead_days: int = field(default_factory=lambda: _int("UNLOCK_RISK_LOOKAHEAD_DAYS", 14))
    dashboard_enabled: bool = field(default_factory=lambda: _bool("DASHBOARD_ENABLED", True))

    def validate(self) -> None:
        if not self.safe_mode:
            raise RuntimeError("SAFE_MODE musi być zawsze true. Ten projekt nie wykonuje transakcji.")
        if self.scoring_profile not in {"conservative", "balanced", "exploratory"}:
            raise RuntimeError("SCORING_PROFILE musi być jednym z: conservative, balanced, exploratory.")
        if self.run_mode not in {"full", "dex", "cex", "performance"}:
            raise RuntimeError("RUN_MODE musi być jednym z: full, dex, cex, performance.")
        if not self.performance_windows:
            raise RuntimeError("PERFORMANCE_WINDOWS nie może być puste.")
        if self.persistent_storage_mode not in {"github_cache", "local", "external"}:
            raise RuntimeError("PERSISTENT_STORAGE_MODE musi być jednym z: github_cache, local, external.")
        if self.digest_mode not in {"daily", "hourly", "off"}:
            raise RuntimeError("DIGEST_MODE musi być jednym z: daily, hourly, off.")
        if not 0 <= self.digest_hour_utc <= 23:
            raise RuntimeError("DIGEST_HOUR_UTC musi być w zakresie 0-23.")
        if self.digest_min_interval_hours < 1:
            raise RuntimeError("DIGEST_MIN_INTERVAL_HOURS musi być >= 1.")
