"""
consecutivo.py
--------------
Consecutivo para facturas de servicio.

Implementación:
- consecutivo = MAX(consecutivo) + 1
- Debe ejecutarse dentro de una transacción (nuestra session() lo hace).
"""

from __future__ import annotations

import sqlite3
from src.db.repositories.service_invoices_repo import get_last_consecutivo


def next_consecutivo(conn: sqlite3.Connection) -> int:
    return get_last_consecutivo(conn) + 1
