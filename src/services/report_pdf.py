"""
report_pdf.py
-------------
Generador de reportes PDF corporativos para Telefinance.

Incluye:
- Resumen de Proveedores (Gastos)
- Resumen de Servicios (Ingresos)

Fuentes de datos:
- vendor_invoices + vendor_invoice_items
- service_invoices + service_invoice_items

Características:
- Consulta SQLite en modo solo lectura
- Genera gráficos PNG con Matplotlib
- Embebe gráficos en HTML como data-uri
- Renderiza PDF usando `src/services/pdf_renderer.py`
- Integra KPIs financieros ejecutivos
- Inserta el logo corporativo del proyecto
"""

from __future__ import annotations

import base64
from datetime import timedelta
from pathlib import Path
from typing import List, Tuple

import matplotlib.pyplot as plt

from src.core.utils_time import TimeContext
from src.db.connection import readonly_session
from src.services.analytics import (
    net_last_n_days,
    service_last_n_days,
    vendor_last_n_days,
)
from src.services.pdf_renderer import render_pdf


# ============================================================
# Paths
# ============================================================

def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _reports_dir() -> Path:
    out = _project_root() / "output" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _reports_assets_dir() -> Path:
    out = _reports_dir() / "_assets"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _report_css_path() -> Path:
    return _project_root() / "assets" / "report.css"


def _logo_path() -> Path:
    return _project_root() / "assets" / "logo_factura.png"


# ============================================================
# Utils
# ============================================================

def _money(v: float) -> str:
    return f"$ {float(v):.2f}"


def _percent(v: float) -> str:
    return f"{float(v):.2f}%"


def _sqlite_range_last_days(tctx: TimeContext, days: int) -> Tuple[str, str, str, str]:
    end = tctx.today()
    start = end - timedelta(days=max(days, 1) - 1)
    start_dt = f"{start.isoformat()} 00:00:00"
    end_dt = f"{end.isoformat()} 23:59:59"
    return start.isoformat(), end.isoformat(), start_dt, end_dt


def _save_png(fig, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _png_as_data_uri(path: Path) -> str:
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _safe_labels(labels: List[str], max_len: int = 22) -> List[str]:
    out: List[str] = []
    for s in labels:
        s = (s or "").strip()
        if len(s) > max_len:
            out.append(s[: max_len - 1] + "…")
        else:
            out.append(s)
    return out


# ============================================================
# Charts
# ============================================================

def _chart_daily_timeseries(*, days: List[str], totals: List[float], title: str, out: Path) -> Path:
    fig = plt.figure()
    ax = fig.add_subplot(111)
    ax.plot(days, totals, marker="o")
    ax.set_title(title)
    ax.set_xlabel("Día")
    ax.set_ylabel("Total")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.6)
    return _save_png(fig, out)


def _chart_top_bar(*, labels: List[str], totals: List[float], title: str, out: Path) -> Path:
    fig = plt.figure()
    ax = fig.add_subplot(111)
    ax.bar(_safe_labels(labels), totals)
    ax.set_title(title)
    ax.set_ylabel("Total")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(True, axis="y", linestyle="--", linewidth=0.5, alpha=0.6)
    return _save_png(fig, out)


# ============================================================
# Queries
# ============================================================

def _q_daily_sum(conn, table: str, start_dt: str, end_dt: str) -> List[Tuple[str, float]]:
    return conn.execute(
        f"""
        SELECT date(created_at) AS day, COALESCE(SUM(total),0) AS total
        FROM {table}
        WHERE datetime(created_at) >= datetime(?)
          AND datetime(created_at) <= datetime(?)
        GROUP BY day
        ORDER BY day ASC
        """,
        (start_dt, end_dt),
    ).fetchall()


def _q_total_count(conn, table: str, start_dt: str, end_dt: str) -> Tuple[float, int]:
    total, count = conn.execute(
        f"""
        SELECT COALESCE(SUM(total),0), COUNT(*)
        FROM {table}
        WHERE datetime(created_at) >= datetime(?)
          AND datetime(created_at) <= datetime(?)
        """,
        (start_dt, end_dt),
    ).fetchone()
    return float(total or 0.0), int(count or 0)


def _q_top_group_sum(
    conn,
    table: str,
    name_col: str,
    start_dt: str,
    end_dt: str,
    limit: int = 10,
) -> List[Tuple[str, float]]:
    return conn.execute(
        f"""
        SELECT COALESCE(NULLIF(TRIM({name_col}), ''), '(sin nombre)') AS name,
               COALESCE(SUM(total),0) AS total
        FROM {table}
        WHERE datetime(created_at) >= datetime(?)
          AND datetime(created_at) <= datetime(?)
        GROUP BY name
        ORDER BY total DESC
        LIMIT {int(limit)}
        """,
        (start_dt, end_dt),
    ).fetchall()


def _q_top_vendor_items(conn, start_dt: str, end_dt: str, limit: int = 10) -> List[Tuple[str, float]]:
    return conn.execute(
        f"""
        SELECT vii.description AS name, COALESCE(SUM(vii.line_total),0) AS total
        FROM vendor_invoice_items vii
        INNER JOIN vendor_invoices vi ON vi.id = vii.vendor_invoice_id
        WHERE datetime(vi.created_at) >= datetime(?)
          AND datetime(vi.created_at) <= datetime(?)
        GROUP BY name
        ORDER BY total DESC
        LIMIT {int(limit)}
        """,
        (start_dt, end_dt),
    ).fetchall()


def _q_top_service_items(conn, start_dt: str, end_dt: str, limit: int = 10) -> List[Tuple[str, float]]:
    return conn.execute(
        f"""
        SELECT sii.description AS name, COALESCE(SUM(sii.line_total),0) AS total
        FROM service_invoice_items sii
        INNER JOIN service_invoices si ON si.id = sii.service_invoice_id
        WHERE datetime(si.created_at) >= datetime(?)
          AND datetime(si.created_at) <= datetime(?)
        GROUP BY name
        ORDER BY total DESC
        LIMIT {int(limit)}
        """,
        (start_dt, end_dt),
    ).fetchall()


# ============================================================
# KPI helpers
# ============================================================

def _financial_kpis_for_period(conn, tctx: TimeContext, days: int) -> List[Tuple[str, str]]:
    income = service_last_n_days(conn, tctx, days)
    spend = vendor_last_n_days(conn, tctx, days)
    net = net_last_n_days(conn, tctx, days)

    return [
        ("Ingresos Período", _money(income.total)),
        ("Gastos Período", _money(spend.total)),
        ("Neto", _money(net.net)),
        ("Margen %", _percent(net.margin_pct)),
    ]


# ============================================================
# HTML
# ============================================================

def _html_report(
    *,
    title: str,
    subtitle: str,
    logo_src: str,
    kpis_primary: List[Tuple[str, str]],
    kpis_financial: List[Tuple[str, str]],
    charts: List[Tuple[str, str]],
    table_sections: List[Tuple[str, List[Tuple[str, float]]]],
) -> str:
    def table_html(rows: List[Tuple[str, float]]) -> str:
        if not rows:
            return "<p class='muted'><i>Sin datos.</i></p>"

        trs = "".join(
            f"<tr><td>{n}</td><td class='td-right'>{_money(t)}</td></tr>"
            for n, t in rows
        )
        return f"""
        <table class="tbl">
          <tr><th>Nombre</th><th class="td-right">Total</th></tr>
          {trs}
        </table>
        """

    kpi_primary_html = "".join(
        f"<div class='kpi'><div class='kpi-k'>{k}</div><div class='kpi-v'>{v}</div></div>"
        for k, v in kpis_primary
    )

    kpi_financial_html = "".join(
        f"<div class='kpi kpi-fin'><div class='kpi-k'>{k}</div><div class='kpi-v'>{v}</div></div>"
        for k, v in kpis_financial
    )

    charts_html = "".join(
        f"""
        <div class="card">
          <div class="card-title">{cap}</div>
          <img class="chart" src="{src}" />
        </div>
        """
        for cap, src in charts
    )

    tables_html = "".join(
        f"""
        <div class="card">
          <div class="card-title">{sec_title}</div>
          {table_html(rows)}
        </div>
        """
        for sec_title, rows in table_sections
    )

    return f"""
    <html>
    <head>
      <meta charset="utf-8">
      <title>{title}</title>
    </head>
    <body>
      <div class="report">
        <div class="header">
          <div class="header-left">
            <img class="logo" src="{logo_src}" />
          </div>

          <div class="header-right">
            <div class="header-title">{title}</div>
            <div class="header-sub">{subtitle}</div>
          </div>
        </div>

        <div class="section-label">KPIs Operativos</div>
        <div class="kpis">{kpi_primary_html}</div>

        <div class="section-label mt">KPIs Financieros</div>
        <div class="kpis">{kpi_financial_html}</div>

        <div class="section-label mt">Visualizaciones</div>
        <div class="grid grid-2 mt">{charts_html}</div>

        <div class="section-label mt">Rankings</div>
        <div class="grid grid-2 mt">{tables_html}</div>

        <div class="footer">
          Generado por Telefinance • Reporte corporativo
        </div>
      </div>
    </body>
    </html>
    """


# ============================================================
# Public API
# ============================================================

def build_vendor_summary_pdf(*, db_path: Path, tctx: TimeContext, days: int = 30) -> Path:
    root = _project_root()
    assets = _reports_assets_dir()
    out_dir = _reports_dir()

    start_date, end_date, start_dt, end_dt = _sqlite_range_last_days(tctx, days)
    logo_uri = _logo_path().as_uri()

    with readonly_session(db_path) as conn:
        total, count = _q_total_count(conn, "vendor_invoices", start_dt, end_dt)
        daily = _q_daily_sum(conn, "vendor_invoices", start_dt, end_dt)
        top_vendors = _q_top_group_sum(conn, "vendor_invoices", "vendor_name", start_dt, end_dt, limit=10)
        top_items = _q_top_vendor_items(conn, start_dt, end_dt, limit=10)
        financial_kpis = _financial_kpis_for_period(conn, tctx, days)

    days_x = [d for d, _ in daily] or [start_date, end_date]
    totals_y = [float(t) for _, t in daily] or [0.0, 0.0]

    chart1 = _chart_daily_timeseries(
        days=days_x,
        totals=totals_y,
        title="Gasto diario",
        out=assets / f"vendor_daily_{end_date}.png",
    )

    chart2 = _chart_top_bar(
        labels=[n for n, _ in top_vendors] or ["(sin datos)"],
        totals=[float(t) for _, t in top_vendors] or [0.0],
        title="Top proveedores por gasto",
        out=assets / f"vendor_top_vendors_{end_date}.png",
    )

    chart3 = _chart_top_bar(
        labels=[n for n, _ in top_items] or ["(sin datos)"],
        totals=[float(t) for _, t in top_items] or [0.0],
        title="Top artículos por gasto",
        out=assets / f"vendor_top_items_{end_date}.png",
    )

    html = _html_report(
        title="Telefinance — Resumen Proveedores (Gastos)",
        subtitle=f"Rango: {start_date} → {end_date} • Ventana: últimos {days} días",
        logo_src=logo_uri,
        kpis_primary=[
            ("Total Gastos", _money(total)),
            ("# Facturas", str(count)),
            ("Promedio/Ventana", _money(total / max(days, 1))),
            ("Moneda", "PAB/USD"),
        ],
        kpis_financial=financial_kpis,
        charts=[
            ("Gasto diario", _png_as_data_uri(chart1)),
            ("Top proveedores", _png_as_data_uri(chart2)),
            ("Top artículos", _png_as_data_uri(chart3)),
        ],
        table_sections=[
            ("Top 10 Proveedores", [(n, float(t)) for n, t in top_vendors]),
            ("Top 10 Artículos", [(n, float(t)) for n, t in top_items]),
        ],
    )

    pdf_path = out_dir / f"resumen_proveedores_{end_date}.pdf"
    render_pdf(
        html=html,
        output_path=pdf_path,
        base_dir=root,
        css_path=_report_css_path(),
        debug_html=True,
    )
    return pdf_path


def build_service_summary_pdf(*, db_path: Path, tctx: TimeContext, days: int = 30) -> Path:
    root = _project_root()
    assets = _reports_assets_dir()
    out_dir = _reports_dir()

    start_date, end_date, start_dt, end_dt = _sqlite_range_last_days(tctx, days)
    logo_uri = _logo_path().as_uri()

    with readonly_session(db_path) as conn:
        total, count = _q_total_count(conn, "service_invoices", start_dt, end_dt)
        daily = _q_daily_sum(conn, "service_invoices", start_dt, end_dt)
        top_clients = _q_top_group_sum(conn, "service_invoices", "client_name", start_dt, end_dt, limit=10)
        top_items = _q_top_service_items(conn, start_dt, end_dt, limit=10)
        financial_kpis = _financial_kpis_for_period(conn, tctx, days)

    days_x = [d for d, _ in daily] or [start_date, end_date]
    totals_y = [float(t) for _, t in daily] or [0.0, 0.0]

    chart1 = _chart_daily_timeseries(
        days=days_x,
        totals=totals_y,
        title="Ingreso diario",
        out=assets / f"service_daily_{end_date}.png",
    )

    chart2 = _chart_top_bar(
        labels=[n for n, _ in top_clients] or ["(sin datos)"],
        totals=[float(t) for _, t in top_clients] or [0.0],
        title="Top clientes por ingreso",
        out=assets / f"service_top_clients_{end_date}.png",
    )

    chart3 = _chart_top_bar(
        labels=[n for n, _ in top_items] or ["(sin datos)"],
        totals=[float(t) for _, t in top_items] or [0.0],
        title="Top conceptos por ingreso",
        out=assets / f"service_top_items_{end_date}.png",
    )

    html = _html_report(
        title="Telefinance — Resumen Servicios (Ingresos)",
        subtitle=f"Rango: {start_date} → {end_date} • Ventana: últimos {days} días",
        logo_src=logo_uri,
        kpis_primary=[
            ("Total Ingresos", _money(total)),
            ("# Recibos", str(count)),
            ("Promedio/Ventana", _money(total / max(days, 1))),
            ("Moneda", "PAB/USD"),
        ],
        kpis_financial=financial_kpis,
        charts=[
            ("Ingreso diario", _png_as_data_uri(chart1)),
            ("Top clientes", _png_as_data_uri(chart2)),
            ("Top conceptos", _png_as_data_uri(chart3)),
        ],
        table_sections=[
            ("Top 10 Clientes", [(n, float(t)) for n, t in top_clients]),
            ("Top 10 Conceptos", [(n, float(t)) for n, t in top_items]),
        ],
    )

    pdf_path = out_dir / f"resumen_servicios_{end_date}.pdf"
    render_pdf(
        html=html,
        output_path=pdf_path,
        base_dir=root,
        css_path=_report_css_path(),
        debug_html=True,
    )
    return pdf_path