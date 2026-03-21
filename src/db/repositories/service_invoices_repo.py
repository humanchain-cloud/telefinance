"""
service_invoices_repo.py
------------------------
Repositorio para facturas de SERVICIO (ingresos).

Diseño actual:
- service_invoices: cabecera
- service_invoice_items: líneas del servicio
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional


def _normalize_text(value: Optional[str], default: str = "") -> str:
    """
    Normaliza texto nullable a string limpio.
    """
    if value is None:
        return default
    return str(value).strip()


def _normalize_float(value: Any, default: float = 0.0) -> float:
    """
    Convierte un valor a float de forma segura.
    """
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _normalize_service_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza un ítem de servicio antes de persistir.

    Reglas:
    - description nunca vacía
    - qty mínimo 1
    - unit_price nunca negativo
    - line_total nunca negativo
    """
    description = _normalize_text(item.get("description"), default="Servicio")
    qty = _normalize_float(item.get("qty"), default=1.0)
    if qty <= 0:
        qty = 1.0

    unit_price = _normalize_float(item.get("unit_price"), default=0.0)
    if unit_price < 0:
        unit_price = 0.0

    raw_line_total = item.get("line_total")
    if raw_line_total in (None, ""):
        line_total = qty * unit_price
    else:
        line_total = _normalize_float(raw_line_total, default=0.0)

    if line_total < 0:
        line_total = 0.0

    return {
        "description": description,
        "qty": qty,
        "unit_price": unit_price,
        "line_total": line_total,
    }


def insert_service_invoice(
    conn: sqlite3.Connection,
    *,
    chat_id: int,
    consecutivo: int,
    client_name: str,
    client_phone: Optional[str],
    service_date: str,
    currency: str,
    total: float,
    pdf_path: str,
    created_at: str,
    items: List[Dict[str, Any]],
) -> int:
    """
    Inserta una factura de servicio y sus líneas normalizadas.

    Consideraciones:
    - No controla commit/rollback; eso lo maneja el caller.
    - Guarda cabecera en `service_invoices`.
    - Guarda detalle en `service_invoice_items`.
    """
    normalized_client_name = _normalize_text(client_name, default="Cliente no identificado")
    normalized_client_phone = _normalize_text(client_phone) or None
    normalized_service_date = _normalize_text(service_date)
    normalized_currency = _normalize_text(currency, default="PAB") or "PAB"
    normalized_total = _normalize_float(total, default=0.0)
    normalized_pdf_path = _normalize_text(pdf_path)

    if normalized_total < 0:
        normalized_total = 0.0

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO service_invoices (
            chat_id,
            consecutivo,
            client_name,
            client_phone,
            service_date,
            currency,
            total,
            pdf_path,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(chat_id),
            int(consecutivo),
            normalized_client_name,
            normalized_client_phone,
            normalized_service_date,
            normalized_currency,
            normalized_total,
            normalized_pdf_path,
            created_at,
            created_at,
        ),
    )
    service_invoice_id = int(cur.lastrowid)

    for raw_item in items or []:
        item = _normalize_service_item(raw_item)

        cur.execute(
            """
            INSERT INTO service_invoice_items (
                service_invoice_id,
                description,
                qty,
                unit_price,
                line_total,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                service_invoice_id,
                item["description"],
                item["qty"],
                item["unit_price"],
                item["line_total"],
                created_at,
            ),
        )

    return service_invoice_id


def get_last_consecutivo(conn: sqlite3.Connection) -> int:
    """
    Obtiene el último consecutivo usado en service_invoices.
    """
    row = conn.execute(
        "SELECT MAX(consecutivo) AS max_consecutivo FROM service_invoices"
    ).fetchone()
    return int(row["max_consecutivo"] or 0)