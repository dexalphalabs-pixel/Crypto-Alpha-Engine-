from __future__ import annotations

import re
from data.models import Candidate
from utils.http_client import build_session, get_json
from utils.logger import get_logger

log = get_logger(__name__)

BINANCE_ANNOUNCEMENTS_URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"


class EventRiskEngine:
    """Lightweight event/news risk layer.

    Uses strict symbol matching to reduce false positives on short tickers such as AI, ID, ONE or API.
    Missing news data does not block the run and should not degrade market-data health.
    """

    def __init__(self, settings):
        self.settings = settings
        self.session = build_session()
        self.health = {"source": "News/BinanceAnnouncements", "status": "NOT_RUN", "errors": [], "articles": 0, "matches": 0}
        self.articles: list[dict] = []

    def load(self) -> None:
        if not self.settings.news_risk_enabled or not self.settings.binance_announcements_enabled:
            self.health["status"] = "DISABLED"
            return
        try:
            data = get_json(
                self.session,
                BINANCE_ANNOUNCEMENTS_URL,
                params={"type": 1, "pageNo": 1, "pageSize": 50},
                timeout=(5, 15),
            )
            raw_catalogs = (((data or {}).get("data") or {}).get("catalogs") or [])
            articles: list[dict] = []
            for catalog in raw_catalogs:
                for article in catalog.get("articles", []) or []:
                    title = article.get("title") or ""
                    if title:
                        articles.append({"title": title, "url": article.get("code") or article.get("id")})
            self.articles = articles[:80]
            self.health["articles"] = len(self.articles)
            self.health["status"] = "OK"
        except Exception as exc:
            self.health["status"] = "FAILED"
            self.health["errors"].append(str(exc))
            log.warning("News risk load failed: %s", exc)

    def enrich(self, candidates: list[Candidate]) -> list[Candidate]:
        if not self.settings.news_risk_enabled:
            return candidates
        if self.health["status"] == "NOT_RUN":
            self.load()
        risk_keywords = [x.lower() for x in self.settings.news_risk_keywords]
        positive_keywords = [x.lower() for x in self.settings.news_positive_keywords]

        for c in candidates:
            symbol_token = c.symbol.replace("USDT", "").replace("BUSD", "").upper()
            matched = []
            for article in self.articles:
                title = article.get("title", "")
                t = title.lower()
                if not self._matches_token(title, symbol_token, c.name):
                    continue
                matched.append(title)
                if any(k in t for k in risk_keywords):
                    c.event_risk_score += 25
                    c.event_risk_flags.append(f"news risk: {title[:120]}")
                elif any(k in t for k in positive_keywords):
                    c.reasons.append(f"news/listing catalyst: {title[:120]}")
                    c.news_hits.append(title[:160])
            if matched:
                self.health["matches"] += len(matched)
                c.news_hits = list(dict.fromkeys(c.news_hits + matched[:5]))
        return candidates

    def _matches_token(self, title: str, symbol: str, name: str | None) -> bool:
        title_l = title.lower()
        symbol_u = (symbol or "").upper()
        name_l = (name or "").lower().strip()
        # Strong patterns for tickers; avoids substring noise.
        strong_patterns = [
            rf"\({re.escape(symbol_u)}\)",
            rf"\b{re.escape(symbol_u)}USDT\b",
            rf"\b{re.escape(symbol_u)}/USDT\b",
            rf"\b{re.escape(symbol_u)}\s+token\b",
        ]
        if any(re.search(p, title, re.IGNORECASE) for p in strong_patterns):
            return True
        # For long symbols, allow exact word boundary. For short symbols, require strong patterns only.
        if len(symbol_u) >= 4 and re.search(rf"\b{re.escape(symbol_u)}\b", title, re.IGNORECASE):
            return True
        # Name matching only if the name is specific enough.
        if len(name_l) >= 5 and name_l not in {"unknown", symbol.lower()} and re.search(rf"\b{re.escape(name_l)}\b", title_l):
            return True
        return False
