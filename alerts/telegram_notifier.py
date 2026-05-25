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

    def format_summary(self, run_id: str, total: int, alerts: int, watchlist: int, rejected: int, report_path: str, health: list[dict] | None = None, performance_summary: dict | None = None, run_url: str = "") -> str:
        health = health or []
        health_line = ", ".join(f"{esc(h.get('source'))}: {esc(h.get('status'))}" for h in health) or "brak danych"
        market_health = [h for h in health if h.get("source") in {"DEX/DexScreener", "CEX/Binance"}]
        failed_market = [h for h in market_health if h.get("status") == "FAILED"]
        warning = "\n⚠️ Część źródeł danych FAILED — wynik może być niewiarygodny." if failed_market else ""
        if total == 0 and market_health and all(h.get("status") == "OK" for h in market_health):
            warning += "\nℹ️ 0 alertów przy działających źródłach danych."
        perf_line = ""
        if performance_summary:
            sample = list(performance_summary.items())[:3]
            parts = []
            for k, v in sample:
                avg = v.get('avg_change')
                delay = v.get('avg_delay_hours')
                if avg is not None:
                    parts.append(f"{esc(k)} n={v.get('count')} avg={avg:.2f}% delay={delay:.2f}h" if delay is not None else f"{esc(k)} n={v.get('count')} avg={avg:.2f}%")
            if parts:
                perf_line = "\nPerformance: " + "; ".join(parts)
        actions_line = f"\nGitHub run: {esc(run_url)}" if run_url else ""
        return (
            f"📊 <b>Crypto Alpha Engine v0.7.2</b>\n"
            f"Run: {esc(run_id)}\n"
            f"Przeanalizowano: {total}\n"
            f"Alerty: {alerts}\n"
            f"Watchlist: {watchlist}\n"
            f"Odrzucone: {rejected}\n"
            f"Health: {health_line}{warning}{perf_line}\n"
            f"Raport: {esc(report_path)}{actions_line}\n"
            f"SAFE_MODE: true"
        )
