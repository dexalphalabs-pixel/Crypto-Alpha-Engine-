import html
from utils.http_client import build_session


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=False)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.session = build_session()

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> bool:
        if not self.enabled:
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text[:3900], "parse_mode": "HTML", "disable_web_page_preview": True}
        response = self.session.post(url, json=payload, timeout=20)
        response.raise_for_status()
        return True

    def format_alert(self, c) -> str:
        reasons = "\n".join(f"✅ {esc(r)}" for r in c.reasons[:7]) or "brak"
        risks = "\n".join(f"⚠️ {esc(r)}" for r in c.risks[:7]) or "brak istotnych ryzyk w modelu"
        tags = esc(", ".join(c.narrative_tags) or "brak")
        rs_btc = "brak" if c.relative_strength_btc_24h is None else f"{c.relative_strength_btc_24h:.2f} pp"
        funding = "brak" if c.funding_rate_pct is None else f"{c.funding_rate_pct:.4f}%"
        oi = "brak" if c.open_interest_usd is None else f"${c.open_interest_usd:,.0f}"
        security = "brak" if c.security_score is None else f"{c.security_score:.0f}/100 ({esc(c.security_source)})"
        confidence = f"{esc(getattr(c, 'source_confidence', 'UNKNOWN'))} ({getattr(c, 'source_confidence_score', 0):.0f}/100)"
        active_sources = ", ".join(getattr(c, 'active_sources', [])[:4]) or "brak"
        return (
            f"🚨 <b>{esc(c.status)}</b>\n"
            f"<b>{esc(c.symbol)}</b> | {esc(c.source)} | {esc(c.exchange or c.chain)}\n"
            f"Score: <b>{c.final_score:.1f}</b> | Risk: <b>{c.risk_score:.1f}</b>\n"
            f"Cena: {esc(c.price_usd)}\n"
            f"Wolumen 24h: ${c.volume_24h_usd:,.0f}\n"
            f"Zmiana: 1h {c.price_change_1h_pct:.2f}% | 4h {c.price_change_4h_pct:.2f}% | 24h {c.price_change_24h_pct:.2f}%\n"
            f"RS vs BTC 24h: {esc(rs_btc)}\n"
            f"Funding: {esc(funding)} | OI: {esc(oi)}\n"
            f"Market: {esc(c.market_regime or 'brak')} | BTC vol 24h: {esc('brak' if c.btc_volatility_24h_pct is None else f'{c.btc_volatility_24h_pct:.2f}%')}\n"
            f"Security: {security}\n"
            f"Data quality: {c.data_quality_score:.0f}/100\n"
            f"Tagi: {tags}\n\n"
            f"<b>Powody:</b>\n{reasons}\n\n"
            f"<b>Ryzyka:</b>\n{risks}\n"
            f"{esc(c.url or '')}\n\n"
            f"SAFE_MODE: analiza bez tradingu."
        )



    def format_digest(self, alerts, diagnostics: dict | None = None) -> str:
        diagnostics = diagnostics or {}
        lines = ["🧭 <b>Crypto Alpha Engine Daily Digest</b>"]
        if alerts:
            lines.append("\n<b>Alerty niepilne / digest:</b>")
            for c in alerts[:12]:
                lines.append(f"• <b>{esc(c.symbol)}</b> {esc(c.status)} | score {c.final_score:.1f} | risk {c.risk_score:.1f}")
        upgrades = diagnostics.get("watchlist_upgrades", [])[:8]
        if upgrades:
            lines.append("\n<b>Watchlist upgrades:</b>")
            for u in upgrades:
                lines.append(f"• <b>{esc(u.get('symbol'))}</b> {esc(u.get('source'))} | score {esc(u.get('final_score'))} | {esc(u.get('reason'))}")
        missed = diagnostics.get("missed_opportunities", [])[:5]
        if missed:
            lines.append("\n<b>Missed opportunities:</b>")
            for m in missed:
                lines.append(f"• <b>{esc(m.get('symbol'))}</b> +{esc(m.get('change_pct'))}% bez alertu | status: {esc(m.get('status_at_track'))}")
        dq = diagnostics.get("data_quality_summary", {})
        if dq:
            lines.append(f"\n<b>Data quality:</b> avg {esc(dq.get('avg'))}, low quality {esc(dq.get('low_quality_count'))}")
        rejected = diagnostics.get("rejected_reasons_summary", [])[:5]
        if rejected:
            lines.append("\n<b>Top powody odrzucenia:</b>")
            for r in rejected:
                lines.append(f"• {esc(r.get('reason'))}: {esc(r.get('count'))}")
        lines.append("\nSAFE_MODE: true")
        return "\n".join(lines)

    def _candidate_brief(self, c, idx: int) -> str:
        reasons = "; ".join(esc(r) for r in c.reasons[:2]) or "brak powodu"
        risks = "; ".join(esc(r) for r in c.risks[:2]) or "brak dużych ryzyk w modelu"
        tags = ", ".join(c.narrative_tags[:3]) or "brak tagów"
        security = "brak" if c.security_score is None else f"{c.security_score:.0f}/100"
        return (
            f"{idx}. <b>{esc(c.symbol)}</b> | {esc(c.source)} | {esc(c.status)}\n"
            f"   Score {c.final_score:.1f} | Risk {c.risk_score:.1f} | DQ {c.data_quality_score:.0f}/100 | Security {esc(security)}\n"
            f"   24h {c.price_change_24h_pct:.2f}% | vol ${c.volume_24h_usd:,.0f} | tagi: {esc(tags)}\n"
            f"   Dlaczego: {reasons}\n"
            f"   Ryzyka: {risks}"
        )

    def _health_note(self, health: list[dict]) -> str:
        failed = [h for h in health if h.get("status") == "FAILED"]
        degraded = [h for h in health if h.get("status") == "DEGRADED"]
        notes = []
        if failed:
            notes.append("FAILED: " + ", ".join(esc(h.get("source")) for h in failed[:4]))
        if degraded:
            notes.append("DEGRADED: " + ", ".join(esc(h.get("source")) for h in degraded[:4]))
        if not notes:
            return ""
        return "\n⚠️ Źródła: " + " | ".join(notes)

    def format_summary(self, run_id: str, total: int, alerts: int, watchlist: int, rejected: int, report_path: str, health: list[dict] | None = None, performance_summary: dict | None = None, run_url: str = "", alert_candidates: list | None = None, watchlist_candidates: list | None = None, operational_mode: str = "UNKNOWN") -> str:
        health = health or []
        alert_candidates = alert_candidates or []
        watchlist_candidates = watchlist_candidates or []
        health_line = ", ".join(f"{esc(h.get('source'))}: {esc(h.get('status'))}" for h in health) or "brak danych"
        market_health = [h for h in health if h.get("source") in {"DEX/DexScreener", "CEX/Binance", "CEX/OKXFallback", "CEX/BybitFallback", "CEX/Fallbacks", "MarketContext/Binance", "MarketContext/CoinGeckoFallback", "MarketContext/BybitFallback"}]
        failed_market = [h for h in market_health if h.get("status") == "FAILED"]
        warning = "\n⚠️ Część źródeł danych FAILED — wynik może być niepełny." if failed_market else ""
        if operational_mode in {"DEX_ONLY", "DEX_ONLY_DEGRADED"}:
            warning += "\nℹ️ Tryb DEX-only: CEX/market context nie jest w pełni dostępny."
        elif operational_mode and operational_mode != "FULL":
            warning += f"\nℹ️ Tryb działania: {esc(operational_mode)}"
        if total == 0 and market_health and all(h.get("status") == "OK" for h in market_health):
            warning += "\nℹ️ 0 alertów przy działających źródłach danych."
        fallback_note = self._health_note(health)
        # Source Intelligence summary from health + candidates gives quick trust context.
        coverage_score = 0
        for h in health:
            if h.get("source") == "SourceIntelligence":
                coverage_score = h.get("coverage_score", 0) or 0
        confidence_counts = {}
        for c in (alert_candidates or []) + (watchlist_candidates or []):
            lvl = getattr(c, "source_confidence", "UNKNOWN")
            confidence_counts[lvl] = confidence_counts.get(lvl, 0) + 1
        confidence_line = f"\nSource coverage: {coverage_score}/100"
        if confidence_counts:
            confidence_line += " | Confidence: " + ", ".join(f"{esc(k)}={v}" for k, v in sorted(confidence_counts.items()))
        perf_line = ""
        if performance_summary:
            sample = list(performance_summary.items())[:3]
            parts = []
            for k, v in sample:
                avg = v.get('avg_change')
                delay = v.get('avg_delay_hours')
                if avg is not None:
                    stale = " STALE" if delay is not None and delay > 6 else ""
                    parts.append(f"{esc(k)} n={v.get('count')} avg={avg:.2f}% delay={delay:.2f}h{stale}" if delay is not None else f"{esc(k)} n={v.get('count')} avg={avg:.2f}%")
            if parts:
                perf_line = "\nPerformance: " + "; ".join(parts)

        # Keep the operational links near the top. Telegram truncates long messages,
        # so the report/run pointers must not be placed after long alert details.
        links = f"Raport: {esc(report_path)}"
        if run_url:
            links += f"\nGitHub run: {esc(run_url)}"

        header = (
            f"📊 <b>Crypto Alpha Engine v0.7.7</b>\n"
            f"Run: {esc(run_id)}\n"
            f"Przeanalizowano: {total} | Alerty: {alerts} | Watchlist: {watchlist} | Odrzucone: {rejected}\n"
            f"Tryb: {esc(operational_mode)}\n"
            f"{links}\n"
            f"Health: {health_line}{warning}{fallback_note}{perf_line}\n"
            f"SAFE_MODE: true"
        )

        attention = []
        if alert_candidates:
            attention.append("\n<b>🚨 Warte uwagi / alerty:</b>")
            for i, c in enumerate(alert_candidates[:3], start=1):
                attention.append(self._candidate_brief(c, i))
        if watchlist_candidates:
            attention.append("\n<b>👀 Do obserwacji:</b>")
            for i, c in enumerate(watchlist_candidates[:3], start=1):
                attention.append(self._candidate_brief(c, i))
        if not attention:
            attention.append("\n<b>Warte uwagi:</b> brak nowych alertów i brak kandydatów watchlist w tym runie.")

        return header + "\n" + "\n".join(attention)

