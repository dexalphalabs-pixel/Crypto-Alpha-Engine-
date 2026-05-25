import json
from datetime import datetime, timezone, timedelta
from utils.http_client import build_session, get_json
from utils.time_utils import utc_now_iso

BINANCE_PRICE_URL = "https://api.binance.com/api/v3/ticker/price"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
DEX_PAIR_URL = "https://api.dexscreener.com/latest/dex/pairs/{chain}/{pair}"


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class PerformanceEngine:
    def __init__(self, db, settings):
        self.db = db
        self.settings = settings
        self.session = build_session()

    def update_due_checks(self):
        cur = self.db.conn.cursor()
        now = datetime.now(timezone.utc)
        for window in self.settings.performance_windows:
            rows = cur.execute("""
                SELECT * FROM alerts a
                WHERE datetime(a.created_at, '+' || ? || ' hours') <= datetime('now')
                AND NOT EXISTS (
                    SELECT 1 FROM performance p WHERE p.alert_id=a.alert_id AND p.window_hours=?
                )
            """, (window, window)).fetchall()
            for row in rows:
                payload = json.loads(row["payload"])
                created = _parse_iso(row["created_at"])
                due_at = created + timedelta(hours=window)
                current_price, price_source = self._fetch_price(payload, due_at)
                if not current_price or not row["price_at_alert"]:
                    continue
                actual_delay_hours = max(0.0, (now - due_at).total_seconds() / 3600)
                change_pct = ((current_price - row["price_at_alert"]) / row["price_at_alert"]) * 100
                result = self._label(change_pct, window)
                cur.execute("""
                    INSERT OR REPLACE INTO performance(
                        alert_id, checked_at, due_at, window_hours, current_price, change_pct,
                        result_label, actual_delay_hours, price_source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    row["alert_id"], utc_now_iso(), due_at.replace(microsecond=0).isoformat(),
                    window, current_price, change_pct, result, actual_delay_hours, price_source
                ))
        self.db.conn.commit()

    def _fetch_price(self, payload: dict, due_at: datetime) -> tuple[float | None, str]:
        try:
            if payload.get("source") == "CEX":
                if self.settings.performance_use_cex_historical_klines:
                    historical = self._fetch_cex_historical_price(payload.get("symbol"), due_at)
                    if historical:
                        return historical, "binance_1h_kline_nearest_due_at"
                data = get_json(self.session, BINANCE_PRICE_URL, params={"symbol": payload.get("symbol")}, timeout=(4, 10))
                return float(data.get("price")), "binance_current_price_fallback"
            if payload.get("source") == "DEX" and payload.get("chain") and payload.get("pair_address"):
                url = DEX_PAIR_URL.format(chain=payload.get("chain"), pair=payload.get("pair_address"))
                data = get_json(self.session, url, timeout=(4, 10))
                pair = (data.get("pair") or {}) if isinstance(data, dict) else {}
                return float(pair.get("priceUsd")), "dexscreener_current_price_approx"
        except Exception:
            return None, "failed"
        return None, "unsupported"

    def _fetch_cex_historical_price(self, symbol: str | None, due_at: datetime) -> float | None:
        if not symbol:
            return None
        # Query a 2-hour window around due_at and take the candle closest to due_at.
        start = int((due_at - timedelta(minutes=65)).timestamp() * 1000)
        end = int((due_at + timedelta(minutes=65)).timestamp() * 1000)
        klines = get_json(
            self.session,
            BINANCE_KLINES_URL,
            params={"symbol": symbol, "interval": "1h", "startTime": start, "endTime": end, "limit": 3},
            timeout=(4, 10),
        )
        if not isinstance(klines, list) or not klines:
            return None
        due_ms = int(due_at.timestamp() * 1000)
        closest = min(klines, key=lambda k: abs(int(k[0]) - due_ms))
        # close price
        return float(closest[4])

    def _label(self, change_pct: float, window: int) -> str:
        if change_pct >= 10:
            return "GOOD_SIGNAL"
        if change_pct <= -10:
            return "BAD_SIGNAL"
        if window <= 4 and change_pct >= 4:
            return "GOOD_SHORT_TERM"
        if abs(change_pct) < 2:
            return "NO_FOLLOW_THROUGH"
        return "NEUTRAL"
