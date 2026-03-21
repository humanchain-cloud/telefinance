from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional


def insert_supplier_invoice(
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
    image_path: str,
    created_at: str,
    items: List[Dict[str, Any]],
) -> int:
    """
    Inserta factura proveedor + items y retorna supplier_invoice_id.

    IMPORTANTÍSIMO:
    - Esta función asume que el caller maneja transacción (en tu caso: session(immediate=True))
    - No hace await. Es pura DB.
    """
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO supplier_invoices (
          chat_id, vendor_name, vendor_id, invoice_number, invoice_date,
          currency, total, raw_text, extracted_json, image_path, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chat_id,
            vendor_name,
            vendor_id,
            invoice_number,
            invoice_date,
            currency or "USD",
            float(total or 0),
            raw_text or "",
            json.dumps(extracted, ensure_ascii=False),
            image_path,
            created_at,
        ),
    )

    supplier_invoice_id = int(cur.lastrowid)

    for it in items:
        desc = str(it.get("description", "")).strip() or "Item"
        qty = float(it.get("qty", 1) or 1)
        unit_price = float(it.get("unit_price", 0) or 0)
        line_total = float(it.get("line_total", qty * unit_price) or 0)

        cur.execute(
            """
            INSERT INTO supplier_invoice_items (
              supplier_invoice_id, description, qty, unit_price, line_total
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (supplier_invoice_id, desc, qty, unit_price, line_total),
        )

    return supplier_invoice_id
