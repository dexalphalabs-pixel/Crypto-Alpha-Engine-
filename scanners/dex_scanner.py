from __future__ import annotations

from data.models import Candidate
from utils.http_client import build_session, get_json, CircuitBreaker
from utils.logger import get_logger
from utils.time_utils import age_hours_from_ms
from utils.validators import safe_float

log = get_logger(__name__)

DEXSCREENER_SEARCH_URL = "https://api.dexscreener.com/latest/dex/search"


class DexScanner:
    def __init__(self, settings):
        self.settings = settings
        self.session = build_session()
        self.breaker = CircuitBreaker(settings.api_circuit_breaker_failures)
        self.health = {
            "source": "DEX/DexScreener",
            "status": "NOT_RUN",
            "errors": [],
            "queries": 0,
            "pairs_raw": 0,
            "candidates": 0,
            "circuit_open": False,
        }

    def scan(self) -> list[Candidate]:
        candidates: dict[str, Candidate] = {}
        allowed_chains = {c.lower() for c in self.settings.dex_chains}
        for query in self.settings.dex_trending_queries:
            if self.breaker.is_open:
                self.health["circuit_open"] = True
                self.health["errors"].append("circuit breaker open: skipped remaining DexScreener queries")
                break
            self.health["queries"] += 1
            try:
                data = get_json(self.session, DEXSCREENER_SEARCH_URL, params={"q": query}, timeout=(5, 12))
                self.breaker.record_success()
                if not isinstance(data, dict):
                    self.health["errors"].append(f"query={query}: unexpected response type {type(data).__name__}")
                    continue
                pairs = data.get("pairs", []) or []
                if not isinstance(pairs, list):
                    self.health["errors"].append(f"query={query}: pairs is not list")
                    continue
                self.health["pairs_raw"] += len(pairs)
            except Exception as exc:
                self.breaker.record_failure()
                self.health["errors"].append(f"query={query}: {exc}")
                log.warning("DEX scan failed for query=%s: %s", query, exc)
                continue

            for pair in pairs:
                if not isinstance(pair, dict):
                    continue
                candidate = self._pair_to_candidate(pair)
                if not candidate:
                    continue
                if candidate.chain and candidate.chain.lower() not in allowed_chains:
                    continue
                candidates[candidate.key()] = candidate
        self.health["candidates"] = len(candidates)
        if candidates:
            self.health["status"] = "OK" if not self.health["errors"] else "DEGRADED"
        else:
            self.health["status"] = "FAILED" if self.health["errors"] else "OK"
        return list(candidates.values())

    def _pair_to_candidate(self, pair: dict) -> Candidate | None:
        base = pair.get("baseToken") or {}
        symbol = base.get("symbol") or "UNKNOWN"
        name = base.get("name") or symbol
        chain = pair.get("chainId")
        liquidity = safe_float((pair.get("liquidity") or {}).get("usd"))
        volume_24h = safe_float((pair.get("volume") or {}).get("h24"))
        age_hours = age_hours_from_ms(pair.get("pairCreatedAt"))
        txns = pair.get("txns") or {}
        buys = int(safe_float((txns.get("h24") or {}).get("buys")))
        sells = int(safe_float((txns.get("h24") or {}).get("sells")))
        price_change = pair.get("priceChange") or {}
        info = pair.get("info") or {}
        websites = info.get("websites") or []
        socials = info.get("socials") or []
        security_verified = bool(websites or socials)  # Conservative proxy, not a contract audit.

        if liquidity <= 0 or volume_24h <= 0:
            return None

        candidate = Candidate(
            source="DEX",
            symbol=symbol.upper(),
            name=name,
            chain=chain,
            address=base.get("address"),
            pair_address=pair.get("pairAddress"),
            exchange=pair.get("dexId"),
            url=pair.get("url"),
            price_usd=safe_float(pair.get("priceUsd")),
            liquidity_usd=liquidity,
            volume_24h_usd=volume_24h,
            price_change_1h_pct=safe_float(price_change.get("h1")),
            price_change_4h_pct=safe_float(price_change.get("h6")),  # DEX h6 proxy, labelled in reports.
            price_change_24h_pct=safe_float(price_change.get("h24")),
            txns_24h=buys + sells,
            age_hours=age_hours,
            security_verified=security_verified,
            raw=pair,
        )
        candidate.raw["dex_change_4h_is_h6_proxy"] = True
        return candidate
