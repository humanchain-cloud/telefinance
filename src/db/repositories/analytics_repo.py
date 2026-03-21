"""
analytics_repo.py
-----------------
Consultas agregadas para Streamlit, reportes PDF y métricas rápidas del bot.

Criterio temporal actual
------------------------
Las funciones de este módulo filtran por `created_at`, es decir,
por la fecha/hora en que el registro fue persistido en la base de datos.

Esto es útil para:
- dashboard operativo
- reportes diarios / semanales / mensuales
- seguimiento de actividad del sistema
"""

from __future__ import annotations

import sqlite3
from typing import List, Tuple


def sum_totals_vendor(conn: sqlite3.Connection, start_iso: str, end_iso: str) -> float:
    """
    Suma el total de gastos de proveedores en un rango de `created_at`.
    """
    row = conn.execute(
        """
        SELECT COALESCE(SUM(total), 0) AS total
        FROM vendor_invoices
        WHERE created_at >= ? AND created_at <= ?
        """,
        (start_iso, end_iso),
    ).fetchone()
    return float(row["total"] or 0.0)


def count_vendor_invoices(conn: sqlite3.Connection, start_iso: str, end_iso: str) -> int:
    """
    Cuenta cuántas facturas de proveedor fueron registradas en el rango.
    """
    row = conn.execute(
        """
        SELECT COUNT(*) AS count_rows
        FROM vendor_invoices
        WHERE created_at >= ? AND created_at <= ?
        """,
        (start_iso, end_iso),
    ).fetchone()
    return int(row["count_rows"] or 0)


def sum_totals_service(conn: sqlite3.Connection, start_iso: str, end_iso: str) -> float:
    """
    Suma el total de ingresos por servicios en un rango de `created_at`.
    """
    row = conn.execute(
        """
        SELECT COALESCE(SUM(total), 0) AS total
        FROM service_invoices
        WHERE created_at >= ? AND created_at <= ?
        """,
        (start_iso, end_iso),
    ).fetchone()
    return float(row["total"] or 0.0)


def count_service_invoices(conn: sqlite3.Connection, start_iso: str, end_iso: str) -> int:
    """
    Cuenta cuántas facturas de servicio fueron registradas en el rango.
    """
    row = conn.execute(
        """
        SELECT COUNT(*) AS count_rows
        FROM service_invoices
        WHERE created_at >= ? AND created_at <= ?
        """,
        (start_iso, end_iso),
    ).fetchone()
    return int(row["count_rows"] or 0)


def top_vendor_items(
    conn: sqlite3.Connection,
    start_iso: str,
    end_iso: str,
    limit: int = 10,
) -> List[Tuple[str, float]]:
    """
    Top conceptos de proveedor por suma de `line_total`.
    """
    rows = conn.execute(
        """
        SELECT
            vii.description AS description,
            COALESCE(SUM(vii.line_total), 0) AS amount
        FROM vendor_invoice_items vii
        INNER JOIN vendor_invoices vi
            ON vi.id = vii.vendor_invoice_id
        WHERE vi.created_at >= ? AND vi.created_at <= ?
        GROUP BY vii.description
        ORDER BY amount DESC, vii.description ASC
        LIMIT ?
        """,
        (start_iso, end_iso, int(limit)),
    ).fetchall()

    return [(str(r["description"]), float(r["amount"])) for r in rows]


def top_service_items(
    conn: sqlite3.Connection,
    start_iso: str,
    end_iso: str,
    limit: int = 10,
) -> List[Tuple[str, float]]:
    """
    Top conceptos de servicio por suma de `line_total`.
    """
    rows = conn.execute(
        """
        SELECT
            sii.description AS description,
            COALESCE(SUM(sii.line_total), 0) AS amount
        FROM service_invoice_items sii
        INNER JOIN service_invoices si
            ON si.id = sii.service_invoice_id
        WHERE si.created_at >= ? AND si.created_at <= ?
        GROUP BY sii.description
        ORDER BY amount DESC, sii.description ASC
        LIMIT ?
        """,
        (start_iso, end_iso, int(limit)),
    ).fetchall()

    return [(str(r["description"]), float(r["amount"])) for r in rows]


def top_vendors(
    conn: sqlite3.Connection,
    start_iso: str,
    end_iso: str,
    limit: int = 10,
) -> List[Tuple[str, float]]:
    """
    Top proveedores por suma de `total`.
    """
    rows = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(TRIM(vendor_name), ''), 'Proveedor no identificado') AS vendor_name,
            COALESCE(SUM(total), 0) AS amount
        FROM vendor_invoices
        WHERE created_at >= ? AND created_at <= ?
        GROUP BY vendor_name
        ORDER BY amount DESC, vendor_name ASC
        LIMIT ?
        """,
        (start_iso, end_iso, int(limit)),
    ).fetchall()

    return [(str(r["vendor_name"]), float(r["amount"])) for r in rows]


def top_clients(
    conn: sqlite3.Connection,
    start_iso: str,
    end_iso: str,
    limit: int = 10,
) -> List[Tuple[str, float]]:
    """
    Top clientes por suma de `total` en facturas de servicio.
    """
    rows = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(TRIM(client_name), ''), 'Cliente no identificado') AS client_name,
            COALESCE(SUM(total), 0) AS amount
        FROM service_invoices
        WHERE created_at >= ? AND created_at <= ?
        GROUP BY client_name
        ORDER BY amount DESC, client_name ASC
        LIMIT ?
        """,
        (start_iso, end_iso, int(limit)),
    ).fetchall()

    return [(str(r["client_name"]), float(r["amount"])) for r in rows]