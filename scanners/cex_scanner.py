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

OKX_TICKERS_URL = "https://www.okx.com/api/v5/market/tickers"
OKX_CANDLES_URL = "https://www.okx.com/api/v5/market/candles"


class CexScanner:
    def __init__(self, settings):
        self.settings = settings
        self.session = build_session()
        self.breaker = CircuitBreaker(settings.api_circuit_breaker_failures)
        self.health = {
            "source": "CEX/Binance",
            "status": "NOT_RUN",
            "errors": [],
            "fallback_used": None,
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
            return self._scan_binance()
        except Exception as exc:
            msg = str(exc)
            self.health["errors"].append(f"Binance base data failed: {msg}")
            log.warning("Binance CEX scan failed; trying OKX fallback: %s", msg)
            try:
                return self._scan_okx_fallback()
            except Exception as fallback_exc:
                self.health["status"] = "FAILED"
                self.health["errors"].append(f"OKX fallback failed: {fallback_exc}")
                log.warning("CEX fallback failed: %s", fallback_exc)
                return []

    def _scan_binance(self) -> list[Candidate]:
        tickers = get_json(self.session, BINANCE_24H_URL, timeout=(5, 18))
        books = get_json(self.session, BINANCE_BOOK_URL, timeout=(5, 18))
        if not isinstance(tickers, list):
            raise RuntimeError(f"Unexpected Binance ticker response type: {type(tickers).__name__}")
        if not isinstance(books, list):
            self.health["status"] = "DEGRADED"
            self.health["errors"].append(f"Unexpected Binance book response type: {type(books).__name__}")
            books = []

        self.health["source"] = "CEX/Binance"
        self.health["tickers_raw"] = len(tickers)
        self.health["books_raw"] = len(books)
        book_map = {b.get("symbol"): b for b in books if isinstance(b, dict) and b.get("symbol")}
        benchmarks = self._benchmark_changes(tickers)
        prefiltered = self._prefilter_binance(tickers)
        self.health["prefiltered"] = len(prefiltered)
        candidates: list[Candidate] = []

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
            change_1h, change_4h, vol_change_1h, vol_change_4h, klines_available = self._binance_klines_momentum(symbol)
            change_24h = safe_float(ticker.get("priceChangePercent"))
            candidate = Candidate(
                source="CEX",
                symbol=symbol,
                name=symbol,
                exchange="Binance",
                url=f"https://www.binance.com/en/trade/{symbol.replace(quote, '_' + quote)}" if quote else None,
                price_usd=last_price,
                liquidity_usd=safe_float(ticker.get("quoteVolume")),
                volume_24h_usd=safe_float(ticker.get("quoteVolume")),
                price_change_1h_pct=change_1h,
                price_change_4h_pct=change_4h,
                price_change_24h_pct=change_24h,
                txns_24h=int(safe_float(ticker.get("count"))),
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

        candidates = self._enrich_binance_futures(candidates)
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

    def _scan_okx_fallback(self) -> list[Candidate]:
        self.health["source"] = "CEX/OKXFallback"
        self.health["fallback_used"] = "OKX"
        self.breaker = CircuitBreaker(self.settings.api_circuit_breaker_failures)
        response = get_json(self.session, OKX_TICKERS_URL, params={"instType": "SPOT"}, timeout=(5, 18))
        data = response.get("data", []) if isinstance(response, dict) else []
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected OKX ticker response type: {type(data).__name__}")
        self.health["tickers_raw"] = len(data)
        self.health["books_raw"] = len(data)
        benchmark = self._okx_benchmark_changes(data)
        rows = self._prefilter_okx(data)
        self.health["prefiltered"] = len(rows)
        candidates: list[Candidate] = []
        for row in rows[: self.settings.cex_klines_prefilter_limit]:
            if self.breaker.is_open:
                self.health["circuit_open"] = True
                break
            inst_id = row.get("instId", "")
            base = inst_id.split("-")[0] if "-" in inst_id else inst_id
            quote = inst_id.split("-")[1] if "-" in inst_id else "USDT"
            last = safe_float(row.get("last"))
            open_24h = safe_float(row.get("open24h"))
            change_24h = ((last - open_24h) / open_24h) * 100 if open_24h else 0.0
            bid = safe_float(row.get("bidPx"))
            ask = safe_float(row.get("askPx"))
            spread_pct = ((ask - bid) / ((ask + bid) / 2)) * 100 if bid > 0 and ask > 0 else None
            if spread_pct is not None and spread_pct > self.settings.cex_max_spread_pct * 3:
                continue
            change_1h, change_4h, vol_change_1h, vol_change_4h, klines_available = self._okx_klines_momentum(inst_id)
            symbol = base + quote
            c = Candidate(
                source="CEX",
                symbol=symbol,
                name=symbol,
                exchange="OKX",
                url=f"https://www.okx.com/trade-spot/{inst_id.lower()}",
                price_usd=last,
                liquidity_usd=safe_float(row.get("volCcy24h")) or safe_float(row.get("volCcyQuote")),
                volume_24h_usd=safe_float(row.get("volCcy24h")) or safe_float(row.get("volCcyQuote")),
                price_change_1h_pct=change_1h,
                price_change_4h_pct=change_4h,
                price_change_24h_pct=change_24h,
                txns_24h=0,
                spread_pct=spread_pct,
                quote_asset=quote,
                relative_strength_btc_24h=None if benchmark["BTC"] is None else change_24h - benchmark["BTC"],
                relative_strength_eth_24h=None if benchmark["ETH"] is None else change_24h - benchmark["ETH"],
                volume_change_1h_pct=vol_change_1h,
                volume_change_4h_pct=vol_change_4h,
                klines_available=klines_available,
                security_verified=True,
                security_score=82.0,
                security_source="okx_listing_proxy",
                raw=row,
            )
            c.reasons.append("CEX fallback source: OKX public market API")
            candidates.append(c)
        candidates.sort(key=lambda x: (x.volume_24h_usd, abs(x.price_change_4h_pct), abs(x.price_change_24h_pct)), reverse=True)
        candidates = candidates[: self.settings.cex_top_limit]
        self.health["candidates"] = len(candidates)
        self.health["status"] = "OK" if candidates else "DEGRADED"
        if self.health["errors"]:
            self.health["status"] = "DEGRADED"
        return candidates

    def _prefilter_binance(self, tickers: list[dict]) -> list[dict]:
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
            t = dict(ticker)
            t["_rough_score"] = quote_volume + change_24h * 2_000_000 + count * 2_000
            out.append(t)
        out.sort(key=lambda t: safe_float(t.get("_rough_score")), reverse=True)
        return out[: max(self.settings.cex_top_limit, self.settings.cex_klines_prefilter_limit)]

    def _prefilter_okx(self, rows: list[dict]) -> list[dict]:
        out = []
        for row in rows:
            inst_id = row.get("instId", "") if isinstance(row, dict) else ""
            if not inst_id.endswith("-USDT"):
                continue
            if inst_id in {"BTC-USDT", "ETH-USDT"}:
                continue
            vol = safe_float(row.get("volCcy24h")) or safe_float(row.get("volCcyQuote"))
            last = safe_float(row.get("last"))
            open_24h = safe_float(row.get("open24h"))
            change_24h = abs(((last - open_24h) / open_24h) * 100) if open_24h else 0.0
            if vol < self.settings.cex_min_quote_volume_usd:
                continue
            r = dict(row)
            r["_rough_score"] = vol + change_24h * 2_000_000
            out.append(r)
        out.sort(key=lambda r: safe_float(r.get("_rough_score")), reverse=True)
        return out[: max(self.settings.cex_top_limit, self.settings.cex_klines_prefilter_limit)]

    def _benchmark_changes(self, tickers: list[dict]) -> dict[str, float | None]:
        out = {"BTC": None, "ETH": None}
        for ticker in tickers:
            if not isinstance(ticker, dict):
                continue
            if ticker.get("symbol") == "BTCUSDT":
                out["BTC"] = safe_float(ticker.get("priceChangePercent"))
            elif ticker.get("symbol") == "ETHUSDT":
                out["ETH"] = safe_float(ticker.get("priceChangePercent"))
        return out

    def _okx_benchmark_changes(self, rows: list[dict]) -> dict[str, float | None]:
        out = {"BTC": None, "ETH": None}
        for row in rows:
            inst_id = row.get("instId") if isinstance(row, dict) else None
            if inst_id not in {"BTC-USDT", "ETH-USDT"}:
                continue
            last = safe_float(row.get("last"))
            open_24h = safe_float(row.get("open24h"))
            change = ((last - open_24h) / open_24h) * 100 if open_24h else None
            if inst_id == "BTC-USDT":
                out["BTC"] = change
            else:
                out["ETH"] = change
        return out

    def _binance_klines_momentum(self, symbol: str) -> tuple[float, float, float | None, float | None, bool]:
        if self.health["klines_checked"] >= self.settings.cex_klines_limit:
            return 0.0, 0.0, None, None, False
        self.health["klines_checked"] += 1
        try:
            klines = get_json(self.session, BINANCE_KLINES_URL, params={"symbol": symbol, "interval": "1h", "limit": 6}, timeout=(5, 12))
            self.breaker.record_success()
            return self._momentum_from_klines(klines, close_idx=4, vol_idx=7, reverse=False)
        except Exception as exc:
            self.breaker.record_failure()
            if len(self.health["errors"]) < 10:
                self.health["errors"].append(f"klines {symbol}: {exc}")
            return 0.0, 0.0, None, None, False

    def _okx_klines_momentum(self, inst_id: str) -> tuple[float, float, float | None, float | None, bool]:
        if self.health["klines_checked"] >= self.settings.cex_klines_limit:
            return 0.0, 0.0, None, None, False
        self.health["klines_checked"] += 1
        try:
            resp = get_json(self.session, OKX_CANDLES_URL, params={"instId": inst_id, "bar": "1H", "limit": 6}, timeout=(5, 12))
            data = resp.get("data", []) if isinstance(resp, dict) else []
            self.breaker.record_success()
            return self._momentum_from_klines(data, close_idx=4, vol_idx=7, reverse=True)
        except Exception as exc:
            self.breaker.record_failure()
            if len(self.health["errors"]) < 10:
                self.health["errors"].append(f"OKX candles {inst_id}: {exc}")
            return 0.0, 0.0, None, None, False

    def _momentum_from_klines(self, klines, *, close_idx: int, vol_idx: int, reverse: bool) -> tuple[float, float, float | None, float | None, bool]:
        if not isinstance(klines, list) or len(klines) < 5:
            return 0.0, 0.0, None, None, False
        rows = list(reversed(klines)) if reverse else klines
        closes = [safe_float(k[close_idx]) for k in rows]
        volumes = [safe_float(k[vol_idx]) if len(k) > vol_idx else safe_float(k[5]) for k in rows]
        last = closes[-1]
        prev1 = closes[-2]
        prev4 = closes[-5]
        change_1h = ((last - prev1) / prev1) * 100 if prev1 else 0.0
        change_4h = ((last - prev4) / prev4) * 100 if prev4 else 0.0
        vol_change_1h = ((volumes[-1] - volumes[-2]) / volumes[-2]) * 100 if len(volumes) >= 2 and volumes[-2] else None
        base_4h = sum(volumes[-5:-1]) / 4 if len(volumes) >= 5 else 0
        vol_change_4h = ((volumes[-1] - base_4h) / base_4h) * 100 if base_4h else None
        return change_1h, change_4h, vol_change_1h, vol_change_4h, True

    def _enrich_binance_futures(self, candidates: list[Candidate]) -> list[Candidate]:
        candidates.sort(key=lambda x: (x.volume_24h_usd, abs(x.price_change_4h_pct), abs(x.price_change_24h_pct)), reverse=True)
        for candidate in candidates[: self.settings.cex_futures_prefilter_limit]:
            funding_rate_pct, open_interest_contracts, open_interest_usd, oi_change_4h, derivatives_available = self._futures_metrics(candidate.symbol, candidate.price_usd)
            candidate.funding_rate_pct = funding_rate_pct
            candidate.open_interest_contracts = open_interest_contracts
            candidate.open_interest_usd = open_interest_usd
            candidate.open_interest_change_4h_pct = oi_change_4h
            candidate.derivatives_available = derivatives_available
        return candidates

    def _futures_metrics(self, symbol: str, last_price: float) -> tuple[float | None, float | None, float | None, float | None, bool]:
        if not self.settings.futures_enabled:
            return None, None, None, None, False
        if self.health["futures_checked"] >= self.settings.futures_metrics_limit:
            return None, None, None, None, False
        self.health["futures_checked"] += 1
        funding_rate_pct = None
        open_interest_contracts = None
        open_interest_usd = None
        oi_change_4h = None
        derivatives_available = False
        try:
            premium = get_json(self.session, BINANCE_FUNDING_URL, params={"symbol": symbol}, timeout=(5, 10))
            if isinstance(premium, dict) and "lastFundingRate" in premium:
                funding_rate_pct = safe_float(premium.get("lastFundingRate")) * 100
                derivatives_available = True
        except Exception as exc:
            if "404" in str(exc) or "400" in str(exc):
                self.health["futures_missing"] += 1
            else:
                self.health["futures_errors"].append(f"funding {symbol}: {exc}")
        try:
            oi = get_json(self.session, BINANCE_OI_URL, params={"symbol": symbol}, timeout=(5, 10))
            if isinstance(oi, dict) and "openInterest" in oi:
                open_interest_contracts = safe_float(oi.get("openInterest"))
                open_interest_usd = open_interest_contracts * last_price if last_price else None
                derivatives_available = True
        except Exception as exc:
            if "404" in str(exc) or "400" in str(exc):
                self.health["futures_missing"] += 1
            else:
                self.health["futures_errors"].append(f"oi {symbol}: {exc}")
        try:
            hist = get_json(self.session, BINANCE_OI_HIST_URL, params={"symbol": symbol, "period": "1h", "limit": 5}, timeout=(5, 10))
            if isinstance(hist, list) and len(hist) >= 5:
                first = safe_float(hist[0].get("sumOpenInterestValue"))
                last = safe_float(hist[-1].get("sumOpenInterestValue"))
                oi_change_4h = ((last - first) / first) * 100 if first else None
        except Exception:
            pass
        if derivatives_available:
            self.health["futures_available"] += 1
        return funding_rate_pct, open_interest_contracts, open_interest_usd, oi_change_4h, derivatives_available
