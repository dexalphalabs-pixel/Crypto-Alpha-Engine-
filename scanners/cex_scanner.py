from __future__ import annotations

from data.models import Candidate
from utils.http_client import build_session, get_json, CircuitBreaker
from utils.logger import get_logger
from utils.validators import safe_float

log = get_logger(__name__)

BINANCE_24H_URL = "https://api.binance.com/api/v3/ticker/24hr"
BINANCE_BOOK_URL = "https://api.binance.com/api/v3/ticker/bookTicker"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
BINANCE_OI_URL = "https://fapi.binance.com/fapi/v1/openInterest"
BINANCE_OI_HIST_URL = "https://fapi.binance.com/futures/data/openInterestHist"


class CexScanner:
    def __init__(self, settings):
        self.settings = settings
        self.session = build_session()
        self.breaker = CircuitBreaker(settings.api_circuit_breaker_failures)
        self.health = {
            "source": "CEX/Binance",
            "status": "NOT_RUN",
            "errors": [],
            "tickers_raw": 0,
            "books_raw": 0,
            "candidates": 0,
            "prefiltered": 0,
            "klines_checked": 0,
            "futures_checked": 0,
            "futures_available": 0,
            "futures_missing": 0,
            "futures_errors": [],
            "circuit_open": False,
        }

    def scan(self) -> list[Candidate]:
        try:
            tickers = get_json(self.session, BINANCE_24H_URL, timeout=(5, 18))
            books = get_json(self.session, BINANCE_BOOK_URL, timeout=(5, 18))
        except Exception as exc:
            self.health["status"] = "FAILED"
            self.health["errors"].append(str(exc))
            log.warning("CEX scan failed while fetching Binance base data: %s", exc)
            return []

        if not isinstance(tickers, list):
            self.health["status"] = "FAILED"
            self.health["errors"].append(f"Unexpected ticker response type: {type(tickers).__name__}")
            return []

        if not isinstance(books, list):
            self.health["status"] = "DEGRADED"
            self.health["errors"].append(f"Unexpected book response type: {type(books).__name__}")
            books = []

        self.health["tickers_raw"] = len(tickers)
        self.health["books_raw"] = len(books)

        book_map = {b.get("symbol"): b for b in books if isinstance(b, dict) and b.get("symbol")}
        benchmarks = self._benchmark_changes(tickers)
        candidates: list[Candidate] = []

        prefiltered = self._prefilter(tickers)
        self.health["prefiltered"] = len(prefiltered)

        # Stage 1: klines only for a bounded, best prefilter group.
        for ticker in prefiltered[: self.settings.cex_klines_prefilter_limit]:
            if self.breaker.is_open:
                self.health["circuit_open"] = True
                self.health["errors"].append("circuit breaker open: skipped remaining Binance klines/futures checks")
                break
            symbol = ticker.get("symbol", "")
            quote = next((q for q in self.settings.cex_quotes if symbol.endswith(q)), None)
            book = book_map.get(symbol) or {}
            bid = safe_float(book.get("bidPrice"))
            ask = safe_float(book.get("askPrice"))
            spread_pct = None
            if bid > 0 and ask > 0:
                spread_pct = ((ask - bid) / ((ask + bid) / 2)) * 100
            if spread_pct is not None and spread_pct > self.settings.cex_max_spread_pct * 3:
                continue

            last_price = safe_float(ticker.get("lastPrice"))
            change_1h, change_4h, vol_change_1h, vol_change_4h, klines_available = self._klines_momentum(symbol)
            change_24h = safe_float(ticker.get("priceChangePercent"))

            candidate = Candidate(
                source="CEX",
                symbol=symbol,
                name=symbol,
                chain=None,
                address=None,
                pair_address=None,
                exchange="Binance",
                url=f"https://www.binance.com/en/trade/{symbol.replace(quote, '_' + quote)}" if quote else None,
                price_usd=last_price,
                liquidity_usd=safe_float(ticker.get("quoteVolume")),
                volume_24h_usd=safe_float(ticker.get("quoteVolume")),
                price_change_1h_pct=change_1h,
                price_change_4h_pct=change_4h,
                price_change_24h_pct=change_24h,
                txns_24h=int(safe_float(ticker.get("count"))),
                age_hours=None,
                spread_pct=spread_pct,
                quote_asset=quote,
                relative_strength_btc_24h=None if benchmarks["BTC"] is None else change_24h - benchmarks["BTC"],
                relative_strength_eth_24h=None if benchmarks["ETH"] is None else change_24h - benchmarks["ETH"],
                volume_change_1h_pct=vol_change_1h,
                volume_change_4h_pct=vol_change_4h,
                klines_available=klines_available,
                security_verified=True,
                security_score=85.0,
                security_source="cex_listing_proxy",
                raw=ticker,
            )
            candidates.append(candidate)

        # Stage 2: futures only for best candidates after klines proxy. Missing futures is not a source error.
        candidates.sort(key=lambda x: (x.volume_24h_usd, abs(x.price_change_4h_pct), abs(x.price_change_24h_pct)), reverse=True)
        for candidate in candidates[: self.settings.cex_futures_prefilter_limit]:
            funding_rate_pct, open_interest_contracts, open_interest_usd, oi_change_4h, derivatives_available = self._futures_metrics(candidate.symbol, candidate.price_usd)
            candidate.funding_rate_pct = funding_rate_pct
            candidate.open_interest_contracts = open_interest_contracts
            candidate.open_interest_usd = open_interest_usd
            candidate.open_interest_change_4h_pct = oi_change_4h
            candidate.derivatives_available = derivatives_available

        candidates.sort(key=lambda x: (x.volume_24h_usd, abs(x.price_change_4h_pct), abs(x.price_change_24h_pct)), reverse=True)
        candidates = candidates[: self.settings.cex_top_limit]
        self.health["candidates"] = len(candidates)
        core_errors = [e for e in self.health["errors"] if not str(e).startswith("klines ")]
        if not candidates and core_errors:
            self.health["status"] = "FAILED"
        elif core_errors or self.health["circuit_open"]:
            self.health["status"] = "DEGRADED"
        else:
            self.health["status"] = "OK"
        return candidates

    def _prefilter(self, tickers: list[dict]) -> list[dict]:
        out = []
        for ticker in tickers:
            if not isinstance(ticker, dict):
                continue
            symbol = ticker.get("symbol", "")
            quote = next((q for q in self.settings.cex_quotes if symbol.endswith(q)), None)
            if not quote or symbol in {"BTCUSDT", "ETHUSDT"}:
                continue
            quote_volume = safe_float(ticker.get("quoteVolume"))
            if quote_volume < self.settings.cex_min_quote_volume_usd:
                continue
            change_24h = abs(safe_float(ticker.get("priceChangePercent")))
            count = safe_float(ticker.get("count"))
            rough_score = quote_volume + change_24h * 2_000_000 + count * 2_000
            t = dict(ticker)
            t["_rough_score"] = rough_score
            out.append(t)
        out.sort(key=lambda t: safe_float(t.get("_rough_score")), reverse=True)
        max_n = max(self.settings.cex_top_limit, self.settings.cex_klines_prefilter_limit)
        return out[:max_n]

    def _benchmark_changes(self, tickers: list[dict]) -> dict[str, float | None]:
        out = {"BTC": None, "ETH": None}
        for ticker in tickers:
            if not isinstance(ticker, dict):
                continue
            symbol = ticker.get("symbol")
            if symbol == "BTCUSDT":
                out["BTC"] = safe_float(ticker.get("priceChangePercent"))
            elif symbol == "ETHUSDT":
                out["ETH"] = safe_float(ticker.get("priceChangePercent"))
        return out

    def _klines_momentum(self, symbol: str) -> tuple[float, float, float | None, float | None, bool]:
        if self.health["klines_checked"] >= self.settings.cex_klines_limit:
            return 0.0, 0.0, None, None, False
        self.health["klines_checked"] += 1
        try:
            klines = get_json(self.session, BINANCE_KLINES_URL, params={"symbol": symbol, "interval": "1h", "limit": 6}, timeout=(5, 12))
            self.breaker.record_success()
            if not isinstance(klines, list) or len(klines) < 5:
                return 0.0, 0.0, None, None, False
            closes = [safe_float(k[4]) for k in klines]
            volumes = [safe_float(k[7]) for k in klines]
            last = closes[-1]
            prev1 = closes[-2]
            prev4 = closes[-5]
            change_1h = ((last - prev1) / prev1) * 100 if prev1 else 0.0
            change_4h = ((last - prev4) / prev4) * 100 if prev4 else 0.0
            vol_change_1h = ((volumes[-1] - volumes[-2]) / volumes[-2]) * 100 if len(volumes) >= 2 and volumes[-2] else None
            base_4h = sum(volumes[-5:-1]) / 4 if len(volumes) >= 5 else 0
            vol_change_4h = ((volumes[-1] - base_4h) / base_4h) * 100 if base_4h else None
            return change_1h, change_4h, vol_change_1h, vol_change_4h, True
        except Exception as exc:
            self.breaker.record_failure()
            if len(self.health["errors"]) < 10:
                self.health["errors"].append(f"klines {symbol}: {exc}")
            return 0.0, 0.0, None, None, False

    def _futures_metrics(self, symbol: str, last_price: float) -> tuple[float | None, float | None, float | None, float | None, bool]:
        if not self.settings.futures_enabled:
            return None, None, None, None, False
        if self.health["futures_checked"] >= self.settings.futures_metrics_limit:
            return None, None, None, None, False
        self.health["futures_checked"] += 1
        try:
            premium = get_json(self.session, BINANCE_FUNDING_URL, params={"symbol": symbol}, timeout=(4, 10))
            oi = get_json(self.session, BINANCE_OI_URL, params={"symbol": symbol}, timeout=(4, 10))
            funding_rate_pct = safe_float(premium.get("lastFundingRate")) * 100
            open_interest_contracts = safe_float(oi.get("openInterest"))
            open_interest_usd = open_interest_contracts * last_price if last_price > 0 else None
            oi_change_4h = self._open_interest_change_4h(symbol)
            self.health["futures_available"] += 1
            return funding_rate_pct, open_interest_contracts, open_interest_usd, oi_change_4h, True
        except Exception as exc:
            # Many spot symbols have no USD-M perpetual. This is expected, not a CEX failure.
            self.health["futures_missing"] += 1
            if len(self.health["futures_errors"]) < 5:
                self.health["futures_errors"].append(f"{symbol}: {exc}")
            return None, None, None, None, False


    def _open_interest_change_4h(self, symbol: str) -> float | None:
        """Best-effort OI trend; if endpoint is unavailable, returns None without degrading spot health."""
        try:
            hist = get_json(
                self.session,
                BINANCE_OI_HIST_URL,
                params={"symbol": symbol, "period": "1h", "limit": 5},
                timeout=(4, 10),
            )
            if not isinstance(hist, list) or len(hist) < 2:
                return None
            first = safe_float(hist[0].get("sumOpenInterest"))
            last = safe_float(hist[-1].get("sumOpenInterest"))
            if not first:
                return None
            return ((last - first) / first) * 100
        except Exception:
            return None
