class WatchlistEngine:
    def __init__(self, settings):
        self.settings = settings

    def select(self, candidates):
        return [c for c in candidates if c.status in {"WATCHLIST", "MOMENTUM_ALERT", "HIGH_CONVICTION", "WATCHLIST_IMPROVING", "WATCHLIST_DEGRADING"}]

    def alertable(self, candidates, recently_alerted_keys: set[str]):
        alerts = []
        for c in candidates:
            if c.status not in {"MOMENTUM_ALERT", "HIGH_CONVICTION"}:
                continue
            if c.key() in recently_alerted_keys:
                c.risks.append("cooldown alertów aktywny")
                continue
            alerts.append(c)
        return alerts
