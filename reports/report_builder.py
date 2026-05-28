import json
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
from jinja2 import Template

HTML_TEMPLATE = """
<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <title>Crypto Alpha Engine v0.7.7 Report</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; color: #1f2937; }
    h1, h2 { color: #111827; }
    .box { padding: 12px 16px; border: 1px solid #e5e7eb; border-radius: 10px; margin: 12px 0; }
    table { border-collapse: collapse; width: 100%; margin-bottom: 24px; }
    th, td { border: 1px solid #e5e7eb; padding: 8px; font-size: 13px; vertical-align: top; }
    th { background: #f9fafb; text-align: left; }
    .risk { color: #b91c1c; }
    .good { color: #047857; font-weight: bold; }
    .muted { color: #6b7280; }
    .warn { color: #92400e; font-weight: bold; }
  </style>
</head>
<body>
  <h1>Crypto Alpha Engine v0.7.7 Report</h1>
  <div class="box">
    <b>Run ID:</b> {{ run_id }}<br>
    <b>UTC:</b> {{ generated_at }}<br>
    <b>SAFE_MODE:</b> true<br>
    <b>Tryb działania:</b> {{ diagnostics.get("operational_mode", "UNKNOWN") }}<br>
    <b>Kandydaci:</b> {{ total }} | <b>Alerty:</b> {{ alerts|length }} | <b>Watchlist:</b> {{ watchlist|length }}<br>
    <b>Health:</b> {{ health_summary }}<br>
    <b>Scoring profile:</b> {{ diagnostics.get("scoring_profile", "balanced") }}
  </div>

  <h2>Status źródeł danych</h2>
  {{ health_table }}

  <h2>Source Intelligence</h2>
  <div class="box">
    <b>Coverage score:</b> {{ diagnostics.get("source_coverage_summary", {}).get("coverage_score", "brak") }}/100<br>
    <b>Aktywne źródła:</b> {{ diagnostics.get("source_coverage_summary", {}).get("active_source_names", []) }}<br>
    <b>Źródła failed:</b> {{ diagnostics.get("source_coverage_summary", {}).get("failed_source_names", []) }}<br>
    <b>Źródła blocked 451:</b> {{ diagnostics.get("source_coverage_summary", {}).get("blocked_451_sources", []) }}
  </div>
  <h3>Provider Matrix</h3>
  {{ provider_matrix_table }}

  <h2>Performance summary</h2>
  {{ performance_table }}

  <h2>Rejected Reasons Summary</h2>
  {{ rejected_reasons_table }}

  <h2>Watchlist Upgrades</h2>
  {{ watchlist_upgrades_table }}

  <h2>Missed Opportunities Report</h2>
  {{ missed_opportunities_table }}

  <h2>Data Quality</h2>
  {{ data_quality_table }}

  <h2>High Conviction / Momentum Alerts</h2>
  {{ alerts_table }}

  <h2>Watchlist</h2>
  {{ watchlist_table }}

  <h2>Rejected / Low Score</h2>
  {{ rejected_table }}

  <p class="muted">To jest narzędzie analityczne. Nie wykonuje transakcji i nie jest rekomendacją inwestycyjną. Security layer to automatyczny screening, nie pełny audyt kontraktu.</p>
</body>
</html>
"""


class ReportBuilder:
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build(self, run_id: str, candidates, alerts, watchlist, health: list[dict] | None = None, performance_summary: dict | None = None, diagnostics: dict | None = None) -> dict:
        health = health or []
        performance_summary = performance_summary or {}
        diagnostics = diagnostics or {}
        rows = [self._row(c) for c in candidates]
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values(["status", "final_score"], ascending=[True, False])

        json_path = self.output_dir / f"report_{run_id}.json"
        csv_path = self.output_dir / f"report_{run_id}.csv"
        html_path = self.output_dir / f"report_{run_id}.html"
        latest_html = self.output_dir / "latest_report.html"
        health_path = self.output_dir / f"health_{run_id}.json"
        perf_path = self.output_dir / f"performance_summary_{run_id}.json"
        diagnostics_path = self.output_dir / f"diagnostics_{run_id}.json"

        json_path.write_text(json.dumps([c.to_dict() for c in candidates], ensure_ascii=False, indent=2), encoding="utf-8")
        health_path.write_text(json.dumps(health, ensure_ascii=False, indent=2), encoding="utf-8")
        perf_path.write_text(json.dumps(performance_summary, ensure_ascii=False, indent=2), encoding="utf-8")
        diagnostics_path.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
        df.to_csv(csv_path, index=False)

        alerts_df = pd.DataFrame([self._row(c) for c in alerts])
        watch_df = pd.DataFrame([self._row(c) for c in watchlist])
        rejected_df = pd.DataFrame([self._row(c) for c in candidates if c.status.startswith("REJECTED")]).head(50)
        health_df = pd.DataFrame(health)
        perf_df = self._performance_df(performance_summary)
        rejected_reasons_df = pd.DataFrame(diagnostics.get("rejected_reasons_summary", []))
        watchlist_upgrades_df = pd.DataFrame(diagnostics.get("watchlist_upgrades", []))
        missed_opportunities_df = pd.DataFrame(diagnostics.get("missed_opportunities", []))
        data_quality_df = pd.DataFrame([self._data_quality_row(c) for c in candidates]).sort_values("data_quality_score", ascending=True).head(50) if candidates else pd.DataFrame()

        health_summary = ", ".join(f"{h.get('source')}: {h.get('status')}" for h in health) or "brak danych"
        html = Template(HTML_TEMPLATE).render(
            run_id=run_id,
            generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            total=len(candidates),
            alerts=alerts,
            watchlist=watchlist,
            health_summary=health_summary,
            health_table=self._html_any_table(health_df),
            performance_table=self._html_any_table(perf_df),
            diagnostics=diagnostics,
            provider_matrix_table=self._html_any_table(pd.DataFrame(diagnostics.get("provider_matrix", []))),
            rejected_reasons_table=self._html_any_table(rejected_reasons_df),
            watchlist_upgrades_table=self._html_any_table(watchlist_upgrades_df),
            missed_opportunities_table=self._html_any_table(missed_opportunities_df),
            data_quality_table=self._html_any_table(data_quality_df),
            alerts_table=self._html_table(alerts_df),
            watchlist_table=self._html_table(watch_df.head(100)),
            rejected_table=self._html_table(rejected_df),
        )
        html_path.write_text(html, encoding="utf-8")
        latest_html.write_text(html, encoding="utf-8")
        return {"json": str(json_path), "csv": str(csv_path), "html": str(html_path), "latest_html": str(latest_html), "health": str(health_path), "performance_summary": str(perf_path), "diagnostics": str(diagnostics_path)}

    def _row(self, c):
        return {
            "source": c.source,
            "symbol": c.symbol,
            "name": c.name,
            "chain": c.chain,
            "exchange": c.exchange,
            "status": c.status,
            "price_usd": c.price_usd,
            "volume_24h_usd": round(c.volume_24h_usd, 2),
            "liquidity_usd": round(c.liquidity_usd, 2),
            "change_1h_pct": round(c.price_change_1h_pct, 2),
            "change_4h_pct": round(c.price_change_4h_pct, 2),
            "dex_change_4h_note": "h6 proxy" if c.source == "DEX" and c.raw.get("dex_change_4h_is_h6_proxy") else "",
            "change_24h_pct": round(c.price_change_24h_pct, 2),
            "rs_btc_24h": None if c.relative_strength_btc_24h is None else round(c.relative_strength_btc_24h, 2),
            "rs_eth_24h": None if c.relative_strength_eth_24h is None else round(c.relative_strength_eth_24h, 2),
            "volume_change_1h_pct": None if c.volume_change_1h_pct is None else round(c.volume_change_1h_pct, 2),
            "spread_pct": None if c.spread_pct is None else round(c.spread_pct, 4),
            "funding_rate_pct": None if c.funding_rate_pct is None else round(c.funding_rate_pct, 5),
            "open_interest_usd": None if c.open_interest_usd is None else round(c.open_interest_usd, 2),
            "open_interest_change_4h_pct": None if c.open_interest_change_4h_pct is None else round(c.open_interest_change_4h_pct, 2),
            "market_regime": c.market_regime,
            "btc_volatility_24h_pct": None if c.btc_volatility_24h_pct is None else round(c.btc_volatility_24h_pct, 2),
            "market_context_score": round(c.market_context_score, 2),
            "source_confidence": getattr(c, "source_confidence", "UNKNOWN"),
            "source_confidence_score": round(getattr(c, "source_confidence_score", 0), 2),
            "source_coverage_score": round(getattr(c, "source_coverage_score", 0), 2),
            "source_agreement_score": round(getattr(c, "source_agreement_score", 0), 2),
            "active_sources": "; ".join(getattr(c, "active_sources", [])),
            "source_missing": "; ".join(getattr(c, "source_missing", [])),
            "source_confidence_reasons": "; ".join(getattr(c, "source_confidence_reasons", [])),
            "data_quality_score": round(c.data_quality_score, 2),
            "source_confidence": getattr(c, "source_confidence", "UNKNOWN"),
            "source_confidence_score": round(getattr(c, "source_confidence_score", 0), 2),
            "data_quality_flags": "; ".join(c.data_quality_flags),
            "unlock_risk_score": round(c.unlock_risk_score, 2),
            "unlock_flags": "; ".join(c.unlock_flags),
            "security_score": c.security_score,
            "security_source": c.security_source,
            "buy_tax_pct": c.buy_tax_pct,
            "sell_tax_pct": c.sell_tax_pct,
            "holder_count": c.holder_count,
            "event_risk_score": c.event_risk_score,
            "alpha_score": round(c.alpha_score, 2),
            "risk_score": round(c.risk_score, 2),
            "tradability_score": round(c.tradability_score, 2),
            "final_score": round(c.final_score, 2),
            "tags": ", ".join(c.narrative_tags),
            "reasons": "; ".join(c.reasons),
            "risks": "; ".join(c.risks),
            "security_flags": "; ".join(c.security_flags),
            "event_flags": "; ".join(c.event_risk_flags),
            "url": c.url,
        }

    def _html_table(self, df: pd.DataFrame) -> str:
        if df.empty:
            return "<p>Brak wyników.</p>"
        columns = [
            "source", "symbol", "exchange", "status", "price_usd", "volume_24h_usd", "change_1h_pct",
            "change_4h_pct", "dex_change_4h_note", "change_24h_pct", "rs_btc_24h", "funding_rate_pct", "open_interest_usd", "open_interest_change_4h_pct", "market_regime", "btc_volatility_24h_pct",
            "security_score", "source_confidence", "source_confidence_score", "source_coverage_score", "event_risk_score", "data_quality_score", "unlock_risk_score", "final_score", "risk_score", "tags", "reasons", "risks", "url"
        ]
        existing = [c for c in columns if c in df.columns]
        return df[existing].to_html(index=False, escape=True)

    def _html_any_table(self, df: pd.DataFrame) -> str:
        if df.empty:
            return "<p>Brak danych.</p>"
        return df.to_html(index=False, escape=True)

    def _data_quality_row(self, c):
        return {
            "symbol": c.symbol,
            "source": c.source,
            "status": c.status,
            "data_quality_score": round(c.data_quality_score, 2),
            "source_confidence": getattr(c, "source_confidence", "UNKNOWN"),
            "source_confidence_score": round(getattr(c, "source_confidence_score", 0), 2),
            "data_quality_flags": "; ".join(c.data_quality_flags),
            "unlock_risk_score": round(c.unlock_risk_score, 2),
            "unlock_flags": "; ".join(c.unlock_flags),
            "final_score": round(c.final_score, 2),
            "risk_score": round(c.risk_score, 2),
        }

    def _performance_df(self, summary: dict) -> pd.DataFrame:
        rows = []
        for key, value in summary.items():
            window, label = key.split(":", 1) if ":" in key else (key, "")
            rows.append({"window": window, "result": label, "count": value.get("count"), "avg_change_pct": value.get("avg_change"), "avg_delay_hours": value.get("avg_delay_hours")})
        return pd.DataFrame(rows)
