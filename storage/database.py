import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from utils.time_utils import utc_now_iso


class Database:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.init()

    def init(self):
        cur = self.conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS candidates (
            run_id TEXT,
            created_at TEXT,
            candidate_key TEXT,
            source TEXT,
            symbol TEXT,
            status TEXT,
            price_usd REAL,
            final_score REAL,
            risk_score REAL,
            payload TEXT,
            PRIMARY KEY(run_id, candidate_key)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            candidate_key TEXT PRIMARY KEY,
            first_seen_at TEXT,
            last_seen_at TEXT,
            source TEXT,
            symbol TEXT,
            status TEXT,
            best_score REAL,
            last_score REAL,
            last_price_usd REAL,
            seen_count INTEGER,
            payload TEXT
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            candidate_key TEXT,
            source TEXT,
            symbol TEXT,
            status TEXT,
            price_at_alert REAL,
            final_score REAL,
            risk_score REAL,
            payload TEXT
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS performance (
            alert_id INTEGER,
            checked_at TEXT,
            due_at TEXT,
            window_hours INTEGER,
            current_price REAL,
            change_pct REAL,
            result_label TEXT,
            actual_delay_hours REAL,
            price_source TEXT,
            PRIMARY KEY(alert_id, window_hours)
        )
        """)
        self._ensure_column("performance", "price_source", "TEXT")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS tracked_non_alerts (
            candidate_key TEXT PRIMARY KEY,
            created_at TEXT,
            last_checked_at TEXT,
            source TEXT,
            symbol TEXT,
            status_at_track TEXT,
            price_at_track REAL,
            best_score_at_track REAL,
            payload TEXT
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS runtime_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        )
        """)
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, coltype: str) -> None:
        cols = {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")

    def save_candidates(self, run_id: str, candidates):
        now = utc_now_iso()
        rows = []
        for c in candidates:
            rows.append((run_id, now, c.key(), c.source, c.symbol, c.status, c.price_usd, c.final_score, c.risk_score, json.dumps(c.to_dict(), ensure_ascii=False)))
        self.conn.executemany("""
            INSERT OR REPLACE INTO candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        self.conn.commit()

    def apply_watchlist_trends(self, candidates):
        """Annotate current candidates with watchlist trend before alerts/reports are built."""
        for c in candidates:
            if c.status not in {"WATCHLIST", "MOMENTUM_ALERT", "HIGH_CONVICTION"}:
                continue
            existing = self.conn.execute("SELECT * FROM watchlist WHERE candidate_key=?", (c.key(),)).fetchone()
            if not existing:
                continue
            last_score = float(existing["last_score"] or 0)
            best_score = float(existing["best_score"] or 0)
            if c.final_score >= last_score + 8 and c.status == "WATCHLIST":
                c.status = "WATCHLIST_IMPROVING"
                c.reasons.append(f"watchlist improving: score +{c.final_score - last_score:.1f}")
            elif c.final_score <= last_score - 10 and c.status == "WATCHLIST":
                c.status = "WATCHLIST_DEGRADING"
                c.risks.append(f"watchlist degrading: score {c.final_score - last_score:.1f}")
            elif c.final_score > best_score + 5:
                c.reasons.append("nowy najlepszy score na watchliście")

    def upsert_watchlist(self, candidates):
        now = utc_now_iso()
        for c in candidates:
            existing = self.conn.execute("SELECT * FROM watchlist WHERE candidate_key=?", (c.key(),)).fetchone()
            first_seen = existing["first_seen_at"] if existing else now
            previous_best = float(existing["best_score"] or 0) if existing else 0
            best_score = max(previous_best, c.final_score)
            seen_count = int(existing["seen_count"] or 0) + 1 if existing else 1
            self.conn.execute("""
                INSERT OR REPLACE INTO watchlist VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (c.key(), first_seen, now, c.source, c.symbol, c.status, best_score, c.final_score, c.price_usd, seen_count, json.dumps(c.to_dict(), ensure_ascii=False)))
        self.conn.commit()

    def recently_alerted_keys(self, cooldown_hours: int) -> set[str]:
        rows = self.conn.execute("""
            SELECT candidate_key FROM alerts
            WHERE datetime(created_at) >= datetime('now', ?)
        """, (f"-{cooldown_hours} hours",)).fetchall()
        return {r["candidate_key"] for r in rows}

    def save_alerts(self, alerts):
        now = utc_now_iso()
        for c in alerts:
            self.conn.execute("""
                INSERT INTO alerts(created_at, candidate_key, source, symbol, status, price_at_alert, final_score, risk_score, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (now, c.key(), c.source, c.symbol, c.status, c.price_usd, c.final_score, c.risk_score, json.dumps(c.to_dict(), ensure_ascii=False)))
        self.conn.commit()

    def performance_summary(self) -> dict:
        rows = self.conn.execute("""
            SELECT window_hours, result_label, COUNT(*) AS n, AVG(change_pct) AS avg_change, AVG(actual_delay_hours) AS avg_delay
            FROM performance
            GROUP BY window_hours, result_label
            ORDER BY window_hours, result_label
        """).fetchall()
        return {f"{r['window_hours']}h:{r['result_label']}": {"count": r["n"], "avg_change": r["avg_change"], "avg_delay_hours": r["avg_delay"]} for r in rows}

    def summary(self) -> dict:
        cur = self.conn.cursor()
        alerts_total = cur.execute("SELECT COUNT(*) AS n FROM alerts").fetchone()["n"]
        watchlist_total = cur.execute("SELECT COUNT(*) AS n FROM watchlist").fetchone()["n"]
        return {"alerts_total": alerts_total, "watchlist_total": watchlist_total}


    def get_state(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM runtime_state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_state(self, key: str, value: str) -> None:
        now = utc_now_iso()
        self.conn.execute(
            "INSERT OR REPLACE INTO runtime_state(key, value, updated_at) VALUES (?, ?, ?)",
            (key, str(value), now),
        )
        self.conn.commit()

    def can_send_digest(self, now: datetime, min_interval_hours: int = 20) -> bool:
        last = self.get_state("last_digest_sent_at")
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            return (now - last_dt).total_seconds() >= max(1, int(min_interval_hours)) * 3600
        except Exception:
            return True

    def mark_digest_sent(self, now: datetime) -> None:
        self.set_state("last_digest_sent_at", now.replace(microsecond=0).isoformat())

    def cleanup_tracked_non_alerts(self, retention_days: int = 30):
        """Remove stale non-alert tracking rows so the SQLite DB stays small on GitHub cache."""
        days = max(1, int(retention_days))
        self.conn.execute(
            "DELETE FROM tracked_non_alerts WHERE datetime(created_at) < datetime('now', ?)",
            (f"-{days} days",),
        )
        self.conn.commit()

    def track_top_non_alert_candidates(self, candidates, alert_keys: set[str], limit: int = 50):
        """Persist top non-alerted candidates to discover future false negatives."""
        now = utc_now_iso()
        pool = [c for c in candidates if c.key() not in alert_keys and c.price_usd and c.price_usd > 0]
        pool.sort(key=lambda c: (c.final_score, -c.risk_score), reverse=True)
        for c in pool[: max(0, int(limit))]:
            self.conn.execute("""
                INSERT OR IGNORE INTO tracked_non_alerts(
                    candidate_key, created_at, last_checked_at, source, symbol, status_at_track,
                    price_at_track, best_score_at_track, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (c.key(), now, now, c.source, c.symbol, c.status, c.price_usd, c.final_score, json.dumps(c.to_dict(), ensure_ascii=False)))
        self.conn.commit()

    def missed_opportunities(self, current_candidates, gain_pct: float = 12.0, window_hours: int = 24) -> list[dict]:
        """Return tracked non-alert candidates that later moved strongly without an alert."""
        now = utc_now_iso()
        current = {c.key(): c for c in current_candidates if c.price_usd and c.price_usd > 0}
        rows = self.conn.execute("""
            SELECT * FROM tracked_non_alerts
            WHERE datetime(created_at, '+' || ? || ' hours') <= datetime('now')
        """, (int(window_hours),)).fetchall()
        missed = []
        for row in rows:
            c = current.get(row["candidate_key"])
            if not c or not row["price_at_track"]:
                continue
            change = ((c.price_usd - row["price_at_track"]) / row["price_at_track"]) * 100
            self.conn.execute("UPDATE tracked_non_alerts SET last_checked_at=? WHERE candidate_key=?", (now, row["candidate_key"]))
            if change >= gain_pct:
                missed.append({
                    "symbol": row["symbol"],
                    "source": row["source"],
                    "status_at_track": row["status_at_track"],
                    "current_status": c.status,
                    "price_at_track": row["price_at_track"],
                    "current_price": c.price_usd,
                    "change_pct": round(change, 2),
                    "score_at_track": row["best_score_at_track"],
                    "current_score": round(c.final_score, 2),
                    "url": c.url,
                })
        self.conn.commit()
        missed.sort(key=lambda x: x["change_pct"], reverse=True)
        return missed[:50]
