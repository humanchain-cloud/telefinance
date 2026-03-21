"""
analytics.py
------------
Analíticas financieras y operativas de Telefinance.

Responsabilidades
-----------------
Este módulo centraliza cálculos y consultas analíticas reutilizables sobre SQLite.

Incluye:
1) Helpers simples para cálculos en memoria
   - calc_total(items)

2) Analíticas persistentes (SQLite)
   - Gastos  : vendor_invoices + vendor_invoice_items
   - Ingresos: service_invoices + service_invoice_items
   - Neto    : ingresos - gastos

Diseño
------
- Este módulo NO conoce Telegram ni Streamlit.
- Solo recibe `sqlite3.Connection` y devuelve resultados listos para UI/PDF.
- Las fechas se manejan con `TimeContext` y strings ISO8601.
- Para filtrar por rango en SQLite se usa `datetime(created_at)`.

Convenciones
------------
- `vendor_invoices.created_at` y `service_invoices.created_at` se almacenan como TEXT ISO.
- Los totales viven en la columna `total`.
- Los items usan `line_total`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.core.utils_time import TimeContext


# ---------------------------------------------------------------------
# Draft helpers (memoria)
# ---------------------------------------------------------------------
def calc_total(items: List[Dict[str, Any]]) -> float:
    """
    Calcula el total de una lista de items en memoria.
    """
    return float(sum(float(i.get("line_total", 0.0)) for i in items))


# ---------------------------------------------------------------------
# Tipos de retorno
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class RangeSummary:
    """
    Resumen simple de un rango temporal.
    """
    total: float
    count: int

    @property
    def avg_ticket(self) -> float:
        if self.count <= 0:
            return 0.0
        return float(self.total / self.count)


@dataclass(frozen=True)
class TopRow:
    """
    Fila para rankings.
    """
    name: str
    total: float


@dataclass(frozen=True)
class NetSummary:
    """
    Resumen neto = ingresos - gastos.
    """
    income_total: float
    income_count: int
    spend_total: float
    spend_count: int

    @property
    def net(self) -> float:
        return float(self.income_total - self.spend_total)

    @property
    def margin_pct(self) -> float:
        if self.income_total <= 0:
            return 0.0
        return float((self.net / self.income_total) * 100.0)


# ---------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------
def _normalize_name(value: Any, default: str = "—") -> str:
    """
    Normaliza textos usados en rankings.
    """
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _day_start_iso(d: date, tz) -> str:
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tz).isoformat(timespec="seconds")


def _day_end_iso(d: date, tz) -> str:
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=tz).isoformat(timespec="seconds")


def _range_iso(start: date, end: date, tz) -> Tuple[str, str]:
    return _day_start_iso(start, tz), _day_end_iso(end, tz)


def _coalesce_sum_count(row: Optional[Sequence[Any]]) -> RangeSummary:
    if not row:
        return RangeSummary(total=0.0, count=0)

    total = float(row[0] or 0.0)
    count = int(row[1] or 0)
    return RangeSummary(total=total, count=count)


# ---------------------------------------------------------------------
# Queries base: vendor / service
# ---------------------------------------------------------------------
def vendor_summary_between(conn: sqlite3.Connection, *, start_iso: str, end_iso: str) -> RangeSummary:
    """
    Total y cantidad de facturas de proveedores dentro de un rango.
    """
    cur = conn.execute(
        """
        SELECT COALESCE(SUM(total), 0), COUNT(*)
        FROM vendor_invoices
        WHERE datetime(created_at) >= datetime(?)
          AND datetime(created_at) <= datetime(?)
        """,
        (start_iso, end_iso),
    )
    return _coalesce_sum_count(cur.fetchone())


def service_summary_between(conn: sqlite3.Connection, *, start_iso: str, end_iso: str) -> RangeSummary:
    """
    Total y cantidad de facturas de servicio dentro de un rango.
    """
    cur = conn.execute(
        """
        SELECT COALESCE(SUM(total), 0), COUNT(*)
        FROM service_invoices
        WHERE datetime(created_at) >= datetime(?)
          AND datetime(created_at) <= datetime(?)
        """,
        (start_iso, end_iso),
    )
    return _coalesce_sum_count(cur.fetchone())


# ---------------------------------------------------------------------
# Shortcuts por periodos (vendor)
# ---------------------------------------------------------------------
def vendor_today(conn: sqlite3.Connection, tctx: TimeContext) -> RangeSummary:
    d = tctx.today()
    s, e = _range_iso(d, d, tctx.tz)
    return vendor_summary_between(conn, start_iso=s, end_iso=e)


def vendor_last_7_days(conn: sqlite3.Connection, tctx: TimeContext) -> RangeSummary:
    end = tctx.today()
    start = end - timedelta(days=6)
    s, e = _range_iso(start, end, tctx.tz)
    return vendor_summary_between(conn, start_iso=s, end_iso=e)


def vendor_last_n_days(conn: sqlite3.Connection, tctx: TimeContext, days: int) -> RangeSummary:
    days = max(int(days), 1)
    end = tctx.today()
    start = end - timedelta(days=days - 1)
    s, e = _range_iso(start, end, tctx.tz)
    return vendor_summary_between(conn, start_iso=s, end_iso=e)


def vendor_this_month(conn: sqlite3.Connection, tctx: TimeContext) -> RangeSummary:
    start, end = TimeContext.month_range(tctx.today())
    s, e = _range_iso(start, end, tctx.tz)
    return vendor_summary_between(conn, start_iso=s, end_iso=e)


def vendor_this_year(conn: sqlite3.Connection, tctx: TimeContext) -> RangeSummary:
    start, end = TimeContext.year_range(tctx.today())
    s, e = _range_iso(start, end, tctx.tz)
    return vendor_summary_between(conn, start_iso=s, end_iso=e)


# ---------------------------------------------------------------------
# Shortcuts por periodos (service)
# ---------------------------------------------------------------------
def service_today(conn: sqlite3.Connection, tctx: TimeContext) -> RangeSummary:
    d = tctx.today()
    s, e = _range_iso(d, d, tctx.tz)
    return service_summary_between(conn, start_iso=s, end_iso=e)


def service_last_7_days(conn: sqlite3.Connection, tctx: TimeContext) -> RangeSummary:
    end = tctx.today()
    start = end - timedelta(days=6)
    s, e = _range_iso(start, end, tctx.tz)
    return service_summary_between(conn, start_iso=s, end_iso=e)


def service_last_n_days(conn: sqlite3.Connection, tctx: TimeContext, days: int) -> RangeSummary:
    days = max(int(days), 1)
    end = tctx.today()
    start = end - timedelta(days=days - 1)
    s, e = _range_iso(start, end, tctx.tz)
    return service_summary_between(conn, start_iso=s, end_iso=e)


def service_this_month(conn: sqlite3.Connection, tctx: TimeContext) -> RangeSummary:
    start, end = TimeContext.month_range(tctx.today())
    s, e = _range_iso(start, end, tctx.tz)
    return service_summary_between(conn, start_iso=s, end_iso=e)


def service_this_year(conn: sqlite3.Connection, tctx: TimeContext) -> RangeSummary:
    start, end = TimeContext.year_range(tctx.today())
    s, e = _range_iso(start, end, tctx.tz)
    return service_summary_between(conn, start_iso=s, end_iso=e)


# ---------------------------------------------------------------------
# Rankings por rango
# ---------------------------------------------------------------------
def top_vendor_items_between(
    conn: sqlite3.Connection,
    *,
    start_iso: str,
    end_iso: str,
    limit: int = 10,
) -> List[TopRow]:
    """
    Top artículos de proveedor por gasto en un rango.
    """
    cur = conn.execute(
        """
        SELECT
            vii.description AS name,
            COALESCE(SUM(vii.line_total), 0) AS spent
        FROM vendor_invoice_items vii
        INNER JOIN vendor_invoices vi
            ON vi.id = vii.vendor_invoice_id
        WHERE datetime(vi.created_at) >= datetime(?)
          AND datetime(vi.created_at) <= datetime(?)
        GROUP BY name
        ORDER BY spent DESC, name ASC
        LIMIT ?
        """,
        (start_iso, end_iso, int(limit)),
    )
    return [TopRow(name=_normalize_name(r[0]), total=float(r[1] or 0.0)) for r in cur.fetchall()]


def top_service_items_between(
    conn: sqlite3.Connection,
    *,
    start_iso: str,
    end_iso: str,
    limit: int = 10,
) -> List[TopRow]:
    """
    Top conceptos de servicio por ingreso en un rango.
    """
    cur = conn.execute(
        """
        SELECT
            sii.description AS name,
            COALESCE(SUM(sii.line_total), 0) AS earned
        FROM service_invoice_items sii
        INNER JOIN service_invoices si
            ON si.id = sii.service_invoice_id
        WHERE datetime(si.created_at) >= datetime(?)
          AND datetime(si.created_at) <= datetime(?)
        GROUP BY name
        ORDER BY earned DESC, name ASC
        LIMIT ?
        """,
        (start_iso, end_iso, int(limit)),
    )
    return [TopRow(name=_normalize_name(r[0]), total=float(r[1] or 0.0)) for r in cur.fetchall()]


def top_vendors_between(
    conn: sqlite3.Connection,
    *,
    start_iso: str,
    end_iso: str,
    limit: int = 10,
) -> List[TopRow]:
    """
    Top proveedores por gasto en un rango.
    """
    cur = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(TRIM(vendor_name), ''), '—') AS vendor,
            COALESCE(SUM(total), 0) AS spent
        FROM vendor_invoices
        WHERE datetime(created_at) >= datetime(?)
          AND datetime(created_at) <= datetime(?)
        GROUP BY vendor
        ORDER BY spent DESC, vendor ASC
        LIMIT ?
        """,
        (start_iso, end_iso, int(limit)),
    )
    return [TopRow(name=_normalize_name(r[0]), total=float(r[1] or 0.0)) for r in cur.fetchall()]


def top_clients_between(
    conn: sqlite3.Connection,
    *,
    start_iso: str,
    end_iso: str,
    limit: int = 10,
) -> List[TopRow]:
    """
    Top clientes por ingreso en un rango.
    """
    cur = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(TRIM(client_name), ''), '—') AS client,
            COALESCE(SUM(total), 0) AS earned
        FROM service_invoices
        WHERE datetime(created_at) >= datetime(?)
          AND datetime(created_at) <= datetime(?)
        GROUP BY client
        ORDER BY earned DESC, client ASC
        LIMIT ?
        """,
        (start_iso, end_iso, int(limit)),
    )
    return [TopRow(name=_normalize_name(r[0]), total=float(r[1] or 0.0)) for r in cur.fetchall()]


# ---------------------------------------------------------------------
# Rankings globales (compatibilidad)
# ---------------------------------------------------------------------
def top_vendor_items(conn: sqlite3.Connection, *, limit: int = 10) -> List[TopRow]:
    """
    Top artículos de proveedor sin filtro de fecha.
    """
    cur = conn.execute(
        """
        SELECT
            description,
            COALESCE(SUM(line_total), 0) AS spent
        FROM vendor_invoice_items
        GROUP BY description
        ORDER BY spent DESC, description ASC
        LIMIT ?
        """,
        (int(limit),),
    )
    return [TopRow(name=_normalize_name(r[0]), total=float(r[1] or 0.0)) for r in cur.fetchall()]


def top_service_items(conn: sqlite3.Connection, *, limit: int = 10) -> List[TopRow]:
    """
    Top conceptos de servicio sin filtro de fecha.
    """
    cur = conn.execute(
        """
        SELECT
            description,
            COALESCE(SUM(line_total), 0) AS earned
        FROM service_invoice_items
        GROUP BY description
        ORDER BY earned DESC, description ASC
        LIMIT ?
        """,
        (int(limit),),
    )
    return [TopRow(name=_normalize_name(r[0]), total=float(r[1] or 0.0)) for r in cur.fetchall()]


def top_vendors(conn: sqlite3.Connection, *, limit: int = 10) -> List[TopRow]:
    """
    Top proveedores sin filtro de fecha.
    """
    cur = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(TRIM(vendor_name), ''), '—') AS vendor,
            COALESCE(SUM(total), 0) AS spent
        FROM vendor_invoices
        GROUP BY vendor
        ORDER BY spent DESC, vendor ASC
        LIMIT ?
        """,
        (int(limit),),
    )
    return [TopRow(name=_normalize_name(r[0]), total=float(r[1] or 0.0)) for r in cur.fetchall()]


def top_clients(conn: sqlite3.Connection, *, limit: int = 10) -> List[TopRow]:
    """
    Top clientes sin filtro de fecha.
    """
    cur = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(TRIM(client_name), ''), '—') AS client,
            COALESCE(SUM(total), 0) AS earned
        FROM service_invoices
        GROUP BY client
        ORDER BY earned DESC, client ASC
        LIMIT ?
        """,
        (int(limit),),
    )
    return [TopRow(name=_normalize_name(r[0]), total=float(r[1] or 0.0)) for r in cur.fetchall()]


# ---------------------------------------------------------------------
# KPI: Neto
# ---------------------------------------------------------------------
def net_between(conn: sqlite3.Connection, *, start_iso: str, end_iso: str) -> NetSummary:
    """
    Neto en un rango arbitrario.
    """
    income = service_summary_between(conn, start_iso=start_iso, end_iso=end_iso)
    spend = vendor_summary_between(conn, start_iso=start_iso, end_iso=end_iso)

    return NetSummary(
        income_total=income.total,
        income_count=income.count,
        spend_total=spend.total,
        spend_count=spend.count,
    )


def net_today(conn: sqlite3.Connection, tctx: TimeContext) -> NetSummary:
    d = tctx.today()
    s, e = _range_iso(d, d, tctx.tz)
    return net_between(conn, start_iso=s, end_iso=e)


def net_last_7_days(conn: sqlite3.Connection, tctx: TimeContext) -> NetSummary:
    end = tctx.today()
    start = end - timedelta(days=6)
    s, e = _range_iso(start, end, tctx.tz)
    return net_between(conn, start_iso=s, end_iso=e)


def net_last_n_days(conn: sqlite3.Connection, tctx: TimeContext, days: int) -> NetSummary:
    days = max(int(days), 1)
    end = tctx.today()
    start = end - timedelta(days=days - 1)
    s, e = _range_iso(start, end, tctx.tz)
    return net_between(conn, start_iso=s, end_iso=e)


def net_this_month(conn: sqlite3.Connection, tctx: TimeContext) -> NetSummary:
    start, end = TimeContext.month_range(tctx.today())
    s, e = _range_iso(start, end, tctx.tz)
    return net_between(conn, start_iso=s, end_iso=e)


def net_this_year(conn: sqlite3.Connection, tctx: TimeContext) -> NetSummary:
    start, end = TimeContext.year_range(tctx.today())
    s, e = _range_iso(start, end, tctx.tz)
    return net_between(conn, start_iso=s, end_iso=e)