from datetime import datetime, timezone
from pathlib import Path

from config import Settings
from scanners.dex_scanner import DexScanner
from scanners.cex_scanner import CexScanner
from scanners.security_scanner import SecurityScanner
from engines.event_risk_engine import EventRiskEngine
from engines.narrative_engine import NarrativeEngine
from engines.scoring_engine import ScoringEngine
from engines.watchlist_engine import WatchlistEngine
from engines.performance_engine import PerformanceEngine
from engines.diagnostics_engine import DiagnosticsEngine
from engines.market_context_engine import MarketContextEngine
from engines.unlock_risk_engine import UnlockRiskEngine
from engines.data_quality_engine import DataQualityEngine
from storage.database import Database
from reports.report_builder import ReportBuilder
from alerts.telegram_notifier import TelegramNotifier
from utils.logger import get_logger
from utils.safe_mode import enforce_safe_mode

log = get_logger(__name__)


def _market_sources_failed(health: list[dict]) -> bool:
    market = [h for h in health if h.get("source") in {"DEX/DexScreener", "CEX/Binance"}]
    return bool(market) and all(h.get("status") == "FAILED" for h in market)


def _should_send_digest(settings: Settings, db: Database, now: datetime) -> bool:
    if not settings.send_telegram_daily_digest or settings.digest_mode == "off":
        return False
    if settings.digest_mode == "hourly":
        return db.can_send_digest(now, min_interval_hours=1)
    if now.hour != settings.digest_hour_utc:
        return False
    return db.can_send_digest(now, min_interval_hours=settings.digest_min_interval_hours)


def run() -> None:
    settings = Settings()
    settings.validate()
    enforce_safe_mode(settings.safe_mode)
    Path(settings.output_dir).mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log.info("Crypto Alpha Engine v0.7.2 start | run_id=%s | SAFE_MODE=%s | RUN_MODE=%s", run_id, settings.safe_mode, settings.run_mode)

    db = Database(settings.database_path)
    all_candidates = []
    health = []

    if settings.run_mode in {"full", "dex"} and settings.dex_enabled:
        dex_scanner = DexScanner(settings)
        dex_candidates = dex_scanner.scan()
        health.append(dex_scanner.health)
        log.info("DEX candidates: %s | health=%s", len(dex_candidates), dex_scanner.health.get("status"))
        all_candidates.extend(dex_candidates)

    if settings.run_mode in {"full", "cex"} and settings.cex_enabled:
        cex_scanner = CexScanner(settings)
        cex_candidates = cex_scanner.scan()
        health.append(cex_scanner.health)
        log.info("CEX candidates: %s | health=%s", len(cex_candidates), cex_scanner.health.get("status"))
        all_candidates.extend(cex_candidates)

    skip_secondary = settings.global_api_failure_fast_mode and settings.skip_secondary_sources_if_market_data_failed and _market_sources_failed(health)
    if skip_secondary:
        log.warning("Fast-fail: market data sources failed, skipping secondary enrichment layers.")

    if not skip_secondary and settings.run_mode in {"full", "dex"} and settings.security_enabled:
        security_scanner = SecurityScanner(settings)
        all_candidates = security_scanner.enrich(all_candidates)
        health.append(security_scanner.health)
        log.info("Security checks: %s | verified=%s | health=%s", security_scanner.health.get("checked"), security_scanner.health.get("verified"), security_scanner.health.get("status"))

    event_risk = EventRiskEngine(settings)
    if not skip_secondary and settings.run_mode in {"full", "cex", "dex"} and settings.news_risk_enabled:
        all_candidates = event_risk.enrich(all_candidates)
        health.append(event_risk.health)
        log.info("Event/news risk: articles=%s matches=%s health=%s", event_risk.health.get("articles"), event_risk.health.get("matches"), event_risk.health.get("status"))

    unlock_engine = UnlockRiskEngine(settings)
    if not skip_secondary and settings.run_mode in {"full", "cex", "dex"} and settings.unlock_risk_enabled:
        all_candidates = unlock_engine.enrich(all_candidates)
        health.append(unlock_engine.health)

    data_quality = DataQualityEngine(settings)
    if settings.data_quality_enabled:
        all_candidates = data_quality.enrich(all_candidates, health)
        health.append(data_quality.health)

    narrative = NarrativeEngine()
    scoring = ScoringEngine(settings)
    scored = []
    for candidate in all_candidates:
        narrative.tag(candidate)
        scoring.score(candidate)
        scored.append(candidate)

    if not skip_secondary and settings.market_context_enabled and settings.run_mode in {"full", "cex", "dex"}:
        market_context = MarketContextEngine(settings)
        scored = market_context.enrich(scored)
        health.append(market_context.health)
        scored = [scoring.refresh_status(c) for c in scored]

    scored.sort(key=lambda x: x.final_score, reverse=True)

    db.apply_watchlist_trends(scored)
    watch_engine = WatchlistEngine(settings)
    watchlist = watch_engine.select(scored)
    recently_alerted = db.recently_alerted_keys(settings.alert_cooldown_hours)
    alerts = watch_engine.alertable(scored, recently_alerted)

    if settings.run_mode != "performance":
        db.save_candidates(run_id, scored)
        db.upsert_watchlist(watchlist)
        db.save_alerts(alerts)

    try:
        PerformanceEngine(db, settings).update_due_checks()
    except Exception as exc:
        log.warning("Performance update skipped: %s", exc)

    enabled_source_health = [h for h in health if h.get("status") not in {"DISABLED", "NOT_RUN"} and not h.get("source", "").startswith("Security") and not h.get("source", "").startswith("News")]
    if not scored and enabled_source_health and all(h.get("status") == "FAILED" for h in enabled_source_health):
        log.warning("No candidates because all enabled market data sources failed. This is not the same as no market opportunities.")

    perf_summary = db.performance_summary()
    diagnostics = DiagnosticsEngine(settings, db).build(scored, alerts, health)
    paths = ReportBuilder(settings.output_dir).build(run_id, scored, alerts, watchlist, health=health, performance_summary=perf_summary, diagnostics=diagnostics)

    if settings.dry_run_verbose:
        log.info("DRY_RUN_VERBOSE diagnostics: %s", diagnostics.get("verbose", diagnostics))

    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    instant_alerts = [a for a in alerts if a.status in set(settings.instant_alert_statuses)]
    digest_alerts = [a for a in alerts if a.status not in set(settings.instant_alert_statuses)]

    if notifier.enabled and settings.send_telegram_alerts:
        for alert in instant_alerts[:10]:
            try:
                notifier.send(notifier.format_alert(alert))
            except Exception as exc:
                log.warning("Telegram alert failed for %s: %s", alert.symbol, exc)

    digest_now = datetime.now(timezone.utc)
    if notifier.enabled and _should_send_digest(settings, db, digest_now) and digest_alerts:
        try:
            notifier.send(notifier.format_digest(digest_alerts, diagnostics))
            db.mark_digest_sent(digest_now)
        except Exception as exc:
            log.warning("Telegram digest failed: %s", exc)

    if notifier.enabled and settings.send_telegram_summary:
        try:
            rejected = len([c for c in scored if c.status.startswith("REJECTED")])
            notifier.send(notifier.format_summary(run_id, len(scored), len(alerts), len(watchlist), rejected, paths["html"], health=health, performance_summary=perf_summary, run_url=settings.github_run_url))
        except Exception as exc:
            log.warning("Telegram summary failed: %s", exc)

    log.info("Done | total=%s alerts=%s watchlist=%s report=%s", len(scored), len(alerts), len(watchlist), paths["html"])


if __name__ == "__main__":
    run()
