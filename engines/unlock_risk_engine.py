
from __future__ import annotations

import csv
from datetime import datetime, timezone, timedelta
from pathlib import Path


class UnlockRiskEngine:
    """Optional local token unlock calendar.

    Format data/token_unlocks.csv:
    symbol,date_utc,description,risk_score
    OP,2026-06-01,large unlock,18
    """

    def __init__(self, settings):
        self.settings = settings
        self.health = {"source": "UnlockCalendar/local_csv", "status": "NOT_RUN", "errors": [], "events": 0, "matches": 0}
        self.events = []

    def load(self):
        if not self.settings.unlock_risk_enabled:
            self.health["status"] = "DISABLED"
            return
        path = Path(self.settings.token_unlocks_csv)
        if not path.exists():
            self.health["status"] = "NO_DATA"
            return
        try:
            with path.open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.events = rows
            self.health["events"] = len(rows)
            self.health["status"] = "OK"
        except Exception as exc:
            self.health["status"] = "FAILED"
            self.health["errors"].append(str(exc))

    def enrich(self, candidates):
        if self.health["status"] == "NOT_RUN":
            self.load()
        if self.health["status"] not in {"OK"}:
            return candidates
        now = datetime.now(timezone.utc).date()
        cutoff = now + timedelta(days=self.settings.unlock_risk_lookahead_days)
        for c in candidates:
            base_symbol = c.symbol.replace("USDT", "").replace("BUSD", "").upper()
            for e in self.events:
                if (e.get("symbol") or "").upper() != base_symbol:
                    continue
                try:
                    event_date = datetime.fromisoformat((e.get("date_utc") or "").replace("Z", "+00:00")).date()
                except Exception:
                    continue
                if now <= event_date <= cutoff:
                    score = float(e.get("risk_score") or 15)
                    desc = e.get("description") or "token unlock"
                    c.unlock_risk_score += score
                    c.unlock_flags.append(f"unlock {event_date.isoformat()}: {desc}")
                    self.health["matches"] += 1
        return candidates
