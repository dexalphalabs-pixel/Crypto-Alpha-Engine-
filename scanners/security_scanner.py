from __future__ import annotations

from data.models import Candidate
from utils.http_client import build_session, get_json, CircuitBreaker
from utils.logger import get_logger
from utils.validators import safe_float, clamp

log = get_logger(__name__)

GOPLUS_TOKEN_SECURITY_URL = "https://api.gopluslabs.io/api/v1/token_security/{chain_id}"

CHAIN_IDS = {
    "ethereum": "1",
    "eth": "1",
    "bsc": "56",
    "binance-smart-chain": "56",
    "polygon": "137",
    "arbitrum": "42161",
    "base": "8453",
    "optimism": "10",
    "avalanche": "43114",
    "fantom": "250",
}


class SecurityScanner:
    """Best-effort DEX token security enrichment.

    Uses public GoPlus data for EVM chains. Unsupported chains, missing data, or API failures are treated
    conservatively by the scoring engine. This is not a full smart-contract audit.
    """

    def __init__(self, settings):
        self.settings = settings
        self.session = build_session()
        self.breaker = CircuitBreaker(settings.api_circuit_breaker_failures)
        self.health = {
            "source": "Security/GoPlus",
            "status": "NOT_RUN",
            "errors": [],
            "checked": 0,
            "unsupported": 0,
            "verified": 0,
            "high_risk": 0,
            "circuit_open": False,
        }

    def enrich(self, candidates: list[Candidate]) -> list[Candidate]:
        if not self.settings.security_enabled:
            self.health["status"] = "DISABLED"
            return candidates

        dex_candidates = [c for c in candidates if c.source == "DEX" and c.address]
        dex_candidates.sort(key=lambda c: (c.liquidity_usd * 0.45 + c.volume_24h_usd * 0.45 + c.txns_24h * 100 + abs(c.price_change_24h_pct) * 500), reverse=True)
        for c in dex_candidates[: self.settings.security_max_dex_checks]:
            if self.breaker.is_open:
                self.health["circuit_open"] = True
                self.health["errors"].append("circuit breaker open: skipped remaining GoPlus checks")
                break
            chain_id = CHAIN_IDS.get((c.chain or "").lower())
            if not chain_id:
                self.health["unsupported"] += 1
                c.security_source = "unsupported_chain"
                c.security_verified = False
                c.security_flags.append(f"security unsupported for chain={c.chain}")
                continue
            self.health["checked"] += 1
            try:
                data = get_json(
                    self.session,
                    GOPLUS_TOKEN_SECURITY_URL.format(chain_id=chain_id),
                    params={"contract_addresses": c.address},
                    timeout=(5, 15),
                )
                self.breaker.record_success()
                result = (data.get("result") or {}).get(c.address.lower()) or (data.get("result") or {}).get(c.address) or {}
                if not isinstance(result, dict) or not result:
                    c.security_source = "goplus_no_data"
                    c.security_verified = False
                    c.security_flags.append("GoPlus: brak danych bezpieczeństwa")
                    continue
                self._apply_goplus(c, result)
                if c.security_score is not None and c.security_score >= 70:
                    self.health["verified"] += 1
                if c.security_score is not None and c.security_score < 45:
                    self.health["high_risk"] += 1
            except Exception as exc:
                self.breaker.record_failure()
                msg = f"{c.symbol}/{c.chain}: {exc}"
                self.health["errors"].append(msg)
                c.security_source = "goplus_error"
                c.security_verified = False
                c.security_flags.append("GoPlus: błąd pobierania danych")
                log.warning("Security scan failed for %s: %s", c.key(), exc)

        if self.health["checked"] == 0 and self.health["unsupported"] == 0:
            self.health["status"] = "OK"
        elif self.health["errors"] and self.health["verified"] == 0:
            self.health["status"] = "FAILED"
        elif self.health["errors"] or self.health["unsupported"]:
            self.health["status"] = "DEGRADED"
        else:
            self.health["status"] = "OK"
        return candidates

    def _apply_goplus(self, c: Candidate, result: dict) -> None:
        flags: list[str] = []
        score = 100.0

        def is_bad_bool(field: str) -> bool:
            return str(result.get(field, "0")).lower() in {"1", "true", "yes"}

        def is_good_bool(field: str) -> bool:
            return str(result.get(field, "0")).lower() in {"1", "true", "yes"}

        c.buy_tax_pct = self._tax_pct(result.get("buy_tax"))
        c.sell_tax_pct = self._tax_pct(result.get("sell_tax"))
        c.holder_count = int(safe_float(result.get("holder_count"))) if result.get("holder_count") is not None else None
        owner = result.get("owner_address")
        zero_owner = "0x0000000000000000000000000000000000000000"
        c.owner_renounced = True if owner in {"", None, zero_owner} else False
        c.security_source = "goplus"

        critical_fields = {
            "is_honeypot": "honeypot",
            "is_blacklisted": "blacklist risk",
            "is_mintable": "mintable token",
            "is_proxy": "proxy contract",
            "can_take_back_ownership": "ownership can be taken back",
            "selfdestruct": "selfdestruct function",
            "is_in_dex": "not confirmed in DEX",
        }
        for field, label in critical_fields.items():
            if field == "is_in_dex":
                if str(result.get(field, "1")) in {"0", "false", "False"}:
                    score -= 18
                    flags.append(label)
            elif is_bad_bool(field):
                penalty = 45 if field in {"is_honeypot", "is_blacklisted"} else 15
                score -= penalty
                flags.append(label)

        if str(result.get("is_open_source", "1")) in {"0", "false", "False"}:
            score -= 20
            flags.append("contract not open source")

        if c.buy_tax_pct is not None and c.buy_tax_pct > self.settings.max_buy_tax_pct:
            score -= 18
            flags.append(f"buy tax {c.buy_tax_pct:.2f}%")
        if c.sell_tax_pct is not None and c.sell_tax_pct > self.settings.max_sell_tax_pct:
            score -= 22
            flags.append(f"sell tax {c.sell_tax_pct:.2f}%")

        if c.holder_count is not None and c.holder_count < self.settings.min_holder_count:
            score -= 12
            flags.append(f"low holder count: {c.holder_count}")

        # LP lock is complex and inconsistent across APIs. We detect obvious burn/lock-like LP holders if present.
        c.lp_locked = self._lp_locked_proxy(result)
        if c.lp_locked is False:
            score -= 10
            flags.append("LP lock not detected")

        c.security_score = clamp(score, 0, 100)
        c.security_flags = sorted(set(c.security_flags + flags))
        c.security_verified = c.security_score >= 70 and not any(x in " ".join(flags).lower() for x in ["honeypot", "blacklist"])

    def _tax_pct(self, value) -> float | None:
        if value is None or value == "":
            return None
        raw = safe_float(value)
        # GoPlus often returns tax as decimal fraction: 0.05 = 5%.
        return raw * 100 if 0 <= raw <= 1 else raw

    def _lp_locked_proxy(self, result: dict) -> bool | None:
        lp_holders = result.get("lp_holders")
        if not isinstance(lp_holders, list) or not lp_holders:
            return None
        known_lock_words = ("dead", "burn", "lock", "locker", "pinklock", "unicrypt", "team.finance")
        locked_pct = 0.0
        for holder in lp_holders:
            if not isinstance(holder, dict):
                continue
            tag = f"{holder.get('tag','')} {holder.get('address','')}".lower()
            pct = safe_float(holder.get("percent"))
            if any(word in tag for word in known_lock_words):
                locked_pct += pct * 100 if pct <= 1 else pct
        if locked_pct == 0:
            return False
        return locked_pct >= 50
