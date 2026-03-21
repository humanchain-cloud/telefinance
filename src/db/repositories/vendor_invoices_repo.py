from __future__ import annotations

import json
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


def _normalize_vendor_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza un ítem de proveedor para persistencia segura.

    Reglas:
    - description nunca vacía
    - qty mínimo 1 si viene inválido
    - unit_price puede ser None
    - line_total nunca negativo
    """
    description = _normalize_text(item.get("description"), default="Item")
    qty = _normalize_float(item.get("qty"), default=1.0)
    if qty <= 0:
        qty = 1.0

    raw_unit_price = item.get("unit_price")
    unit_price = None if raw_unit_price in (None, "") else _normalize_float(raw_unit_price, default=0.0)
    if unit_price is not None and unit_price < 0:
        unit_price = 0.0

    raw_line_total = item.get("line_total")
    if raw_line_total in (None, ""):
        line_total = qty * (unit_price or 0.0)
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


def insert_vendor_invoice(
    conn: sqlite3.Connection,
    *,
    chat_id: int,
    vendor_name: Optional[str],
    vendor_id: Optional[str],
    invoice_number: Optional[str],
    invoice_date: Optional[str],
    currency: str,
    total: float,
    raw_text: str,
    extracted: Dict[str, Any],
    image_file_id: Optional[str],
    image_path: Optional[str],
    created_at: str,
    items: List[Dict[str, Any]],
) -> int:
    """
    Inserta una factura de proveedor y sus ítems normalizados.

    Diseño actual:
    - Cabecera en `vendor_invoices`
    - Detalle en `vendor_invoice_items`

    Consideraciones:
    - No controla commit/rollback; eso lo maneja el caller.
    - Guarda `extracted_json` para auditoría y reproducibilidad del OCR.
    - Sanitiza los ítems antes de insertarlos.
    """
    cur = conn.cursor()

    normalized_vendor_name = _normalize_text(vendor_name, default="Proveedor no identificado")
    normalized_invoice_number = _normalize_text(invoice_number) or None
    normalized_invoice_date = _normalize_text(invoice_date) or None
    normalized_currency = _normalize_text(currency, default="PAB") or "PAB"
    normalized_raw_text = _normalize_text(raw_text)
    normalized_total = _normalize_float(total, default=0.0)

    if normalized_total < 0:
        normalized_total = 0.0

    cur.execute(
        """
        INSERT INTO vendor_invoices (
            chat_id,
            vendor_name,
            vendor_id,
            invoice_number,
            invoice_date,
            currency,
            total,
            raw_text,
            extracted_json,
            image_file_id,
            image_path,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(chat_id),
            normalized_vendor_name,
            _normalize_text(vendor_id) or None,
            normalized_invoice_number,
            normalized_invoice_date,
            normalized_currency,
            normalized_total,
            normalized_raw_text,
            json.dumps(extracted or {}, ensure_ascii=False),
            _normalize_text(image_file_id) or None,
            _normalize_text(image_path) or None,
            created_at,
            created_at,
        ),
    )

    vendor_invoice_id = int(cur.lastrowid)

    for raw_item in items or []:
        item = _normalize_vendor_item(raw_item)

        cur.execute(
            """
            INSERT INTO vendor_invoice_items (
                vendor_invoice_id,
                description,
                qty,
                unit_price,
                line_total,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                vendor_invoice_id,
                item["description"],
                item["qty"],
                item["unit_price"],
                item["line_total"],
                created_at,
            ),
        )

    return vendor_invoice_id