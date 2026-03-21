from __future__ import annotations

import csv
import io
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Sequence

import streamlit as st
from streamlit.errors import StreamlitAPIException

try:
    st.set_page_config(page_title="Telefinance Dashboard", layout="wide")
except StreamlitAPIException:
    pass

"""
Telefinance Streamlit Dashboard
------------------------------
Dashboard ejecutivo para visualizar:

- Gastos (vendor_invoices)
- Ingresos (service_invoices)
- Neto (Ingresos - Gastos)

Diseño actualizado:
- Lectura de SQLite en modo readonly
- Diagnóstico de tablas alineado al nuevo esquema
- Rankings y gráficos filtrados por rango real
"""

# ------------------------------------------------------------
# Bootstrapping PYTHONPATH (permite imports `src.*`)
# ------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import Settings
from src.core.utils_time import TimeContext
from src.db.connection import readonly_session
from src.services.analytics import (
    service_last_7_days,
    service_this_month,
    service_this_year,
    service_today,
    vendor_last_7_days,
    vendor_this_month,
    vendor_this_year,
    vendor_today,
)

# ------------------------------------------------------------
# Config & DB path
# ------------------------------------------------------------
settings = Settings()
tctx = TimeContext(settings.tz())
DB_PATH = PROJECT_ROOT / "data" / "telefinance.db"

st.title("📊 Telefinance — Dashboard")


# ============================================================
# Helpers DB
# ============================================================
def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _count_rows(conn, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


# ============================================================
# Diagnóstico
# ============================================================
with st.expander("🛠️ Diagnóstico (DB / Conteos / Fechas)", expanded=False):
    st.caption(f"PROJECT_ROOT: {PROJECT_ROOT}")
    st.caption(f"DB_PATH: {DB_PATH}")
    st.caption(
        f"DB exists: {DB_PATH.exists()}  |  size: {DB_PATH.stat().st_size if DB_PATH.exists() else 'NA'}"
    )

    if DB_PATH.exists():
        with readonly_session(DB_PATH) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
            ).fetchall()
            st.write("Tables:", [t[0] for t in tables])

            counts = {
                "vendor_invoices": _count_rows(conn, "vendor_invoices")
                if _table_exists(conn, "vendor_invoices")
                else 0,
                "service_invoices": _count_rows(conn, "service_invoices")
                if _table_exists(conn, "service_invoices")
                else 0,
                "vendor_invoice_items": _count_rows(conn, "vendor_invoice_items")
                if _table_exists(conn, "vendor_invoice_items")
                else 0,
                "service_invoice_items": _count_rows(conn, "service_invoice_items")
                if _table_exists(conn, "service_invoice_items")
                else 0,
                "work_jobs": _count_rows(conn, "work_jobs")
                if _table_exists(conn, "work_jobs")
                else 0,
                "maintenance_plans": _count_rows(conn, "maintenance_plans")
                if _table_exists(conn, "maintenance_plans")
                else 0,
                "ordered_parts": _count_rows(conn, "ordered_parts")
                if _table_exists(conn, "ordered_parts")
                else 0,
            }
            st.write("Counts:", counts)

            if _table_exists(conn, "vendor_invoices"):
                v_minmax = conn.execute(
                    "SELECT MIN(created_at), MAX(created_at) FROM vendor_invoices;"
                ).fetchone()
                st.write("vendor_invoices created_at (min/max):", v_minmax)

            if _table_exists(conn, "service_invoices"):
                s_minmax = conn.execute(
                    "SELECT MIN(created_at), MAX(created_at) FROM service_invoices;"
                ).fetchone()
                st.write("service_invoices created_at (min/max):", s_minmax)


# ============================================================
# Helpers UI
# ============================================================
def _money(v: float) -> str:
    return f"$ {float(v):.2f}"


def _range_picker(*, key_prefix: str, default_days: int = 7) -> tuple[date, date]:
    """
    Selector de rango de fechas.
    """
    today = tctx.today()
    start_default = today if default_days <= 1 else (today - timedelta(days=default_days - 1))

    col_a, col_b = st.columns(2)
    with col_a:
        start = st.date_input("Desde", value=start_default, key=f"{key_prefix}_desde")
    with col_b:
        end = st.date_input("Hasta", value=today, key=f"{key_prefix}_hasta")

    if start > end:
        st.warning("⚠️ Rango inválido: 'Desde' > 'Hasta'. Intercambiando.")
        start, end = end, start

    return start, end


def _range_to_sqlite(start: date, end: date) -> tuple[str, str]:
    """
    Convierte un rango a datetime strings compatibles con SQLite.
    """
    start_s = f"{start.isoformat()} 00:00:00"
    end_s = f"{end.isoformat()} 23:59:59"
    return start_s, end_s


def _top_table(rows: Sequence[object], col_name: str) -> None:
    if not rows:
        st.info("Aún no hay datos.")
        return

    normalized = []
    for row in rows:
        if isinstance(row, dict):
            name = row.get("name", "")
            total = row.get("total", 0.0)
        else:
            name = getattr(row, "name", "")
            total = getattr(row, "total", 0.0)

        normalized.append(
            {
                col_name: str(name),
                "Total": round(float(total or 0.0), 2),
            }
        )

    st.dataframe(
        normalized,
        use_container_width=True,
        hide_index=True,
    )


def _download_csv_from_rows(
    *,
    filename: str,
    headers: list[str],
    rows: Iterable[Sequence[object]],
    button_label: str | None = None,
) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(list(row))

    st.download_button(
        label=button_label or f"⬇️ Descargar {filename}",
        data=buf.getvalue().encode("utf-8"),
        file_name=filename,
        mime="text/csv",
    )


# ============================================================
# Queries por rango
# ============================================================
def _q_total_count(conn, table: str, start_dt: str, end_dt: str) -> tuple[float, int]:
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
    *,
    table: str,
    name_col: str,
    start_dt: str,
    end_dt: str,
    limit: int = 10,
) -> list[dict]:
    rows = conn.execute(
        f"""
        SELECT COALESCE(NULLIF(TRIM({name_col}), ''), '(sin nombre)') AS name,
               COALESCE(SUM(total),0) AS total
        FROM {table}
        WHERE datetime(created_at) >= datetime(?)
          AND datetime(created_at) <= datetime(?)
        GROUP BY name
        ORDER BY total DESC, name ASC
        LIMIT ?
        """,
        (start_dt, end_dt, int(limit)),
    ).fetchall()

    return [{"name": str(r["name"]), "total": float(r["total"] or 0.0)} for r in rows]


def _q_top_vendor_items(conn, *, start_dt: str, end_dt: str, limit: int = 10) -> list[dict]:
    if not _table_exists(conn, "vendor_invoice_items"):
        return []

    rows = conn.execute(
        """
        SELECT
            vii.description AS name,
            COALESCE(SUM(vii.line_total), 0) AS total
        FROM vendor_invoice_items vii
        INNER JOIN vendor_invoices vi
            ON vi.id = vii.vendor_invoice_id
        WHERE datetime(vi.created_at) >= datetime(?)
          AND datetime(vi.created_at) <= datetime(?)
        GROUP BY name
        ORDER BY total DESC, name ASC
        LIMIT ?
        """,
        (start_dt, end_dt, int(limit)),
    ).fetchall()

    return [{"name": str(r["name"]), "total": float(r["total"] or 0.0)} for r in rows]


def _q_top_service_items(conn, *, start_dt: str, end_dt: str, limit: int = 10) -> list[dict]:
    if not _table_exists(conn, "service_invoice_items"):
        return []

    rows = conn.execute(
        """
        SELECT
            sii.description AS name,
            COALESCE(SUM(sii.line_total), 0) AS total
        FROM service_invoice_items sii
        INNER JOIN service_invoices si
            ON si.id = sii.service_invoice_id
        WHERE datetime(si.created_at) >= datetime(?)
          AND datetime(si.created_at) <= datetime(?)
        GROUP BY name
        ORDER BY total DESC, name ASC
        LIMIT ?
        """,
        (start_dt, end_dt, int(limit)),
    ).fetchall()

    return [{"name": str(r["name"]), "total": float(r["total"] or 0.0)} for r in rows]


# ============================================================
# Helpers de gráficos
# ============================================================
def _chart_timeseries(*, conn, table: str, start_dt: str, end_dt: str, title: str) -> None:
    rows = conn.execute(
        f"""
        SELECT date(created_at) AS day, COALESCE(SUM(total), 0) AS total
        FROM {table}
        WHERE datetime(created_at) >= datetime(?)
          AND datetime(created_at) <= datetime(?)
        GROUP BY day
        ORDER BY day ASC
        """,
        (start_dt, end_dt),
    ).fetchall()

    if not rows:
        st.info("No hay datos para graficar en este rango.")
        return

    data = [{"day": r["day"], "total": float(r["total"] or 0.0)} for r in rows]
    st.subheader(title)
    st.line_chart(data, x="day", y="total", use_container_width=True)


def _chart_top_bar(*, rows: Sequence[dict], label: str, title: str) -> None:
    if not rows:
        st.info("No hay datos para graficar.")
        return

    data = [{label: str(r["name"]), "total": float(r["total"] or 0.0)} for r in rows]
    st.subheader(title)
    st.bar_chart(data, x=label, y="total", use_container_width=True)


def _chart_net_timeseries(*, conn, start_dt: str, end_dt: str) -> None:
    inc_rows = conn.execute(
        """
        SELECT date(created_at) AS day, COALESCE(SUM(total), 0) AS total
        FROM service_invoices
        WHERE datetime(created_at) >= datetime(?)
          AND datetime(created_at) <= datetime(?)
        GROUP BY day
        ORDER BY day ASC
        """,
        (start_dt, end_dt),
    ).fetchall()

    spend_rows = conn.execute(
        """
        SELECT date(created_at) AS day, COALESCE(SUM(total), 0) AS total
        FROM vendor_invoices
        WHERE datetime(created_at) >= datetime(?)
          AND datetime(created_at) <= datetime(?)
        GROUP BY day
        ORDER BY day ASC
        """,
        (start_dt, end_dt),
    ).fetchall()

    inc_map = {r["day"]: float(r["total"] or 0.0) for r in inc_rows}
    spend_map = {r["day"]: float(r["total"] or 0.0) for r in spend_rows}
    days = sorted(set(inc_map.keys()) | set(spend_map.keys()))

    if not days:
        st.info("No hay datos para graficar el neto en este rango.")
        return

    compare = [
        {
            "day": day,
            "Ingresos": inc_map.get(day, 0.0),
            "Gastos": spend_map.get(day, 0.0),
        }
        for day in days
    ]
    net = [
        {
            "day": day,
            "Neto": inc_map.get(day, 0.0) - spend_map.get(day, 0.0),
        }
        for day in days
    ]

    st.subheader("Ingresos vs Gastos (por día)")
    st.line_chart(compare, x="day", y=["Ingresos", "Gastos"], use_container_width=True)

    st.subheader("Neto diario (Ingresos - Gastos)")
    st.bar_chart(net, x="day", y="Neto", use_container_width=True)


# ============================================================
# Tabs
# ============================================================
tab_gastos, tab_ingresos, tab_neto = st.tabs(
    ["💸 Gastos (Proveedores)", "💰 Ingresos (Servicios)", "🧮 Neto"]
)


# ============================================================
# TAB 1: GASTOS
# ============================================================
with tab_gastos:
    st.subheader("💸 Gastos — KPIs")

    c1, c2, c3, c4 = st.columns(4)
    with readonly_session(DB_PATH) as conn:
        s_today = vendor_today(conn, tctx)
        s_week = vendor_last_7_days(conn, tctx)
        s_month = vendor_this_month(conn, tctx)
        s_year = vendor_this_year(conn, tctx)

    c1.metric("Hoy", _money(s_today.total), f"{s_today.count} facturas")
    c2.metric("Últimos 7 días", _money(s_week.total), f"{s_week.count} facturas")
    c3.metric("Este mes", _money(s_month.total), f"{s_month.count} facturas")
    c4.metric("Este año", _money(s_year.total), f"{s_year.count} facturas")

    st.divider()
    st.subheader("🔎 Gastos por rango de fechas")

    v_start, v_end = _range_picker(key_prefix="vendor_range", default_days=7)
    v_start_dt, v_end_dt = _range_to_sqlite(v_start, v_end)

    with readonly_session(DB_PATH) as conn:
        v_total, v_count = _q_total_count(conn, "vendor_invoices", v_start_dt, v_end_dt)

    st.info(
        f"Rango: **{v_start.isoformat()}** → **{v_end.isoformat()}**  |  "
        f"Total: **{_money(v_total)}**  |  Facturas: **{v_count}**"
    )

    st.divider()
    st.subheader("📈 Gráficos (Gastos)")

    with readonly_session(DB_PATH) as conn:
        _chart_timeseries(
            conn=conn,
            table="vendor_invoices",
            start_dt=v_start_dt,
            end_dt=v_end_dt,
            title="Gasto diario (SUM total por día)",
        )

    st.divider()
    left, right = st.columns(2)

    with readonly_session(DB_PATH) as conn:
        v_items_top = _q_top_vendor_items(conn, start_dt=v_start_dt, end_dt=v_end_dt, limit=10)
        v_vendors_top = _q_top_group_sum(
            conn,
            table="vendor_invoices",
            name_col="vendor_name",
            start_dt=v_start_dt,
            end_dt=v_end_dt,
            limit=10,
        )

    with left:
        st.subheader("🧾 Top artículos (por gasto)")
        _top_table(v_items_top, "Artículo")

    with right:
        st.subheader("🏪 Top proveedores (por gasto)")
        _top_table(v_vendors_top, "Proveedor")

    st.divider()
    st.subheader("📊 Rankings (Gastos)")
    _chart_top_bar(rows=v_items_top, label="Artículo", title="Top artículos por gasto")
    _chart_top_bar(rows=v_vendors_top, label="Proveedor", title="Top proveedores por gasto")

    st.divider()
    st.subheader("⬇️ Export CSV (vendor_invoices del rango)")

    with readonly_session(DB_PATH) as conn:
        v_rows = conn.execute(
            """
            SELECT id, vendor_name, vendor_id, invoice_number, invoice_date, currency, total, created_at
            FROM vendor_invoices
            WHERE datetime(created_at) >= datetime(?)
              AND datetime(created_at) <= datetime(?)
            ORDER BY id DESC
            """,
            (v_start_dt, v_end_dt),
        ).fetchall()

    _download_csv_from_rows(
        filename=f"vendor_invoices_{v_start.isoformat()}_{v_end.isoformat()}.csv",
        headers=[
            "id",
            "vendor_name",
            "vendor_id",
            "invoice_number",
            "invoice_date",
            "currency",
            "total",
            "created_at",
        ],
        rows=v_rows,
    )


# ============================================================
# TAB 2: INGRESOS
# ============================================================
with tab_ingresos:
    st.subheader("💰 Ingresos — KPIs")

    c1, c2, c3, c4 = st.columns(4)
    with readonly_session(DB_PATH) as conn:
        i_today = service_today(conn, tctx)
        i_week = service_last_7_days(conn, tctx)
        i_month = service_this_month(conn, tctx)
        i_year = service_this_year(conn, tctx)

    c1.metric("Hoy", _money(i_today.total), f"{i_today.count} recibos")
    c2.metric("Últimos 7 días", _money(i_week.total), f"{i_week.count} recibos")
    c3.metric("Este mes", _money(i_month.total), f"{i_month.count} recibos")
    c4.metric("Este año", _money(i_year.total), f"{i_year.count} recibos")

    st.divider()
    st.subheader("🔎 Ingresos por rango de fechas")

    s_start, s_end = _range_picker(key_prefix="service_range", default_days=7)
    s_start_dt, s_end_dt = _range_to_sqlite(s_start, s_end)

    with readonly_session(DB_PATH) as conn:
        s_total, s_count = _q_total_count(conn, "service_invoices", s_start_dt, s_end_dt)

    st.info(
        f"Rango: **{s_start.isoformat()}** → **{s_end.isoformat()}**  |  "
        f"Total: **{_money(s_total)}**  |  Recibos: **{s_count}**"
    )

    st.divider()
    st.subheader("📈 Gráficos (Ingresos)")

    with readonly_session(DB_PATH) as conn:
        _chart_timeseries(
            conn=conn,
            table="service_invoices",
            start_dt=s_start_dt,
            end_dt=s_end_dt,
            title="Ingreso diario (SUM total por día)",
        )

    st.divider()
    left, right = st.columns(2)

    with readonly_session(DB_PATH) as conn:
        s_items_top = _q_top_service_items(conn, start_dt=s_start_dt, end_dt=s_end_dt, limit=10)
        s_clients_top = _q_top_group_sum(
            conn,
            table="service_invoices",
            name_col="client_name",
            start_dt=s_start_dt,
            end_dt=s_end_dt,
            limit=10,
        )

    with left:
        st.subheader("🧾 Top conceptos (por ingreso)")
        _top_table(s_items_top, "Concepto")

    with right:
        st.subheader("👤 Top clientes (por ingreso)")
        _top_table(s_clients_top, "Cliente")

    st.divider()
    st.subheader("📊 Rankings (Ingresos)")
    _chart_top_bar(rows=s_items_top, label="Concepto", title="Top conceptos por ingreso")
    _chart_top_bar(rows=s_clients_top, label="Cliente", title="Top clientes por ingreso")

    st.divider()
    st.subheader("⬇️ Export CSV (service_invoices del rango)")

    with readonly_session(DB_PATH) as conn:
        s_rows = conn.execute(
            """
            SELECT id, consecutivo, client_name, client_phone, service_date, currency, total, created_at, pdf_path
            FROM service_invoices
            WHERE datetime(created_at) >= datetime(?)
              AND datetime(created_at) <= datetime(?)
            ORDER BY id DESC
            """,
            (s_start_dt, s_end_dt),
        ).fetchall()

    _download_csv_from_rows(
        filename=f"service_invoices_{s_start.isoformat()}_{s_end.isoformat()}.csv",
        headers=[
            "id",
            "consecutivo",
            "client_name",
            "client_phone",
            "service_date",
            "currency",
            "total",
            "created_at",
            "pdf_path",
        ],
        rows=s_rows,
    )


# ============================================================
# TAB 3: NETO
# ============================================================
with tab_neto:
    st.subheader("🧮 Neto (Ingresos - Gastos)")

    n_start, n_end = _range_picker(key_prefix="net_range", default_days=30)
    n_start_dt, n_end_dt = _range_to_sqlite(n_start, n_end)

    with readonly_session(DB_PATH) as conn:
        income_total, income_count = _q_total_count(conn, "service_invoices", n_start_dt, n_end_dt)
        spend_total, spend_count = _q_total_count(conn, "vendor_invoices", n_start_dt, n_end_dt)
        net_val = income_total - spend_total

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Ingresos", _money(income_total), f"{income_count} recibos")
    col_b.metric("Gastos", _money(spend_total), f"{spend_count} facturas")
    col_c.metric("NETO", _money(net_val))

    st.caption("NETO = Ingresos (service_invoices) - Gastos (vendor_invoices) en el rango seleccionado.")

    st.divider()
    with readonly_session(DB_PATH) as conn:
        _chart_net_timeseries(conn=conn, start_dt=n_start_dt, end_dt=n_end_dt)