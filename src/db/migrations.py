# src/db/migrations.py
"""
migrations.py
-------------
Migraciones idempotentes y controladas para Telefinance.

Objetivos
---------
- Aplicar el schema base en instalaciones nuevas
- Ejecutar migraciones incrementales sin romper datos existentes
- Registrar qué migraciones ya fueron aplicadas
- Permitir evolución segura del schema

Reglas
------
- Nunca eliminar columnas automáticamente
- Nunca modificar tipos de forma destructiva
- Solo agregar tablas, columnas, índices o migrar datos de forma segura
- Toda migración debe ser idempotente
"""

from __future__ import annotations

import sqlite3

from src.db.schema import SCHEMA_SQL


# ---------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------
def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if not _table_exists(conn, table):
        return False
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(r[1] == column for r in cur.fetchall())


def _index_exists(conn: sqlite3.Connection, index_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=? LIMIT 1",
        (index_name,),
    ).fetchone()
    return row is not None


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column_ddl: str) -> None:
    column_name = column_ddl.split()[0]
    if not _column_exists(conn, table, column_name):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_ddl}")


# ---------------------------------------------------------------------
# Control de versiones de migración
# ---------------------------------------------------------------------
def _ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )


def _migration_applied(conn: sqlite3.Connection, version: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM schema_migrations WHERE version = ? LIMIT 1",
        (version,),
    ).fetchone()
    return row is not None


def _mark_migration_applied(conn: sqlite3.Connection, version: str) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO schema_migrations(version)
        VALUES (?);
        """,
        (version,),
    )


# ---------------------------------------------------------------------
# Migraciones incrementales
# ---------------------------------------------------------------------
def _migration_001_vendor_invoice_metadata(conn: sqlite3.Connection) -> None:
    version = "001_vendor_invoice_metadata"
    if _migration_applied(conn, version):
        return

    _add_column_if_missing(conn, "vendor_invoices", "vendor_id TEXT")
    _add_column_if_missing(conn, "vendor_invoices", "invoice_number TEXT")
    _add_column_if_missing(conn, "vendor_invoices", "extracted_json TEXT")
    _add_column_if_missing(conn, "vendor_invoices", "image_path TEXT")

    _mark_migration_applied(conn, version)


def _migration_002_coordinator_extra_columns(conn: sqlite3.Connection) -> None:
    version = "002_coordinator_extra_columns"
    if _migration_applied(conn, version):
        return

    # work_jobs
    _add_column_if_missing(conn, "work_jobs", "last_reminded_at TEXT")
    _add_column_if_missing(conn, "work_jobs", "place_type TEXT")
    _add_column_if_missing(conn, "work_jobs", "place_name TEXT")
    _add_column_if_missing(conn, "work_jobs", "tower TEXT")
    _add_column_if_missing(conn, "work_jobs", "apartment TEXT")
    _add_column_if_missing(conn, "work_jobs", "waze_query TEXT")
    _add_column_if_missing(conn, "work_jobs", "appliance TEXT")
    _add_column_if_missing(conn, "work_jobs", "kind TEXT")
    _add_column_if_missing(conn, "work_jobs", "updated_at TEXT")

    # maintenance_plans
    _add_column_if_missing(conn, "maintenance_plans", "last_reminded_at TEXT")
    _add_column_if_missing(conn, "maintenance_plans", "updated_at TEXT")

    # ordered_parts
    _add_column_if_missing(conn, "ordered_parts", "last_reminded_at TEXT")
    _add_column_if_missing(conn, "ordered_parts", "waze_url TEXT")
    _add_column_if_missing(conn, "ordered_parts", "total_usd REAL")
    _add_column_if_missing(conn, "ordered_parts", "updated_at TEXT")

    _mark_migration_applied(conn, version)


def _migration_003_invoice_and_service_updates(conn: sqlite3.Connection) -> None:
    version = "003_invoice_and_service_updates"
    if _migration_applied(conn, version):
        return

    _add_column_if_missing(conn, "vendor_invoices", "updated_at TEXT")
    _add_column_if_missing(conn, "service_invoices", "updated_at TEXT")

    _mark_migration_applied(conn, version)


def _migration_004_split_invoice_items(conn: sqlite3.Connection) -> None:
    """
    Migra desde la tabla legacy `invoice_items` hacia tablas separadas:

    - vendor_invoice_items
    - service_invoice_items

    Casos soportados
    ----------------
    1. Base nueva:
       - `invoice_items` no existe
       - se crean tablas nuevas e índices
       - NO falla
       - NO intenta copiar datos inexistentes

    2. Base vieja:
       - `invoice_items` existe
       - copia los datos legacy hacia las nuevas tablas
       - evita duplicados
    """
    version = "004_split_invoice_items"
    if _migration_applied(conn, version):
        return

    # ---------------------------------------------------------
    # 1) Crear tablas nuevas
    # ---------------------------------------------------------
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vendor_invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_invoice_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            qty REAL NOT NULL DEFAULT 1,
            unit_price REAL,
            line_total REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (vendor_invoice_id)
                REFERENCES vendor_invoices(id)
                ON DELETE CASCADE
        );
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS service_invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_invoice_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            qty REAL NOT NULL DEFAULT 1,
            unit_price REAL,
            line_total REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (service_invoice_id)
                REFERENCES service_invoices(id)
                ON DELETE CASCADE
        );
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_vendor_invoice_items_invoice_id
        ON vendor_invoice_items(vendor_invoice_id);
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_vendor_invoice_items_desc
        ON vendor_invoice_items(description);
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_service_invoice_items_invoice_id
        ON service_invoice_items(service_invoice_id);
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_service_invoice_items_desc
        ON service_invoice_items(description);
        """
    )

    # ---------------------------------------------------------
    # 2) Si no existe la tabla legacy, no hay nada que migrar
    # ---------------------------------------------------------
    if not _table_exists(conn, "invoice_items"):
        _mark_migration_applied(conn, version)
        return

    # ---------------------------------------------------------
    # 3) Migrar vendor items legacy -> vendor_invoice_items
    # ---------------------------------------------------------
    conn.execute(
        """
        INSERT INTO vendor_invoice_items (
            vendor_invoice_id,
            description,
            qty,
            unit_price,
            line_total
        )
        SELECT
            invoice_id,
            description,
            qty,
            unit_price,
            line_total
        FROM invoice_items
        WHERE invoice_type = 'vendor'
          AND NOT EXISTS (
              SELECT 1
              FROM vendor_invoice_items v
              WHERE v.vendor_invoice_id = invoice_items.invoice_id
                AND v.description = invoice_items.description
                AND COALESCE(v.qty, 0) = COALESCE(invoice_items.qty, 0)
                AND COALESCE(v.unit_price, -1) = COALESCE(invoice_items.unit_price, -1)
                AND COALESCE(v.line_total, 0) = COALESCE(invoice_items.line_total, 0)
          );
        """
    )

    # ---------------------------------------------------------
    # 4) Migrar service items legacy -> service_invoice_items
    # ---------------------------------------------------------
    conn.execute(
        """
        INSERT INTO service_invoice_items (
            service_invoice_id,
            description,
            qty,
            unit_price,
            line_total
        )
        SELECT
            invoice_id,
            description,
            qty,
            unit_price,
            line_total
        FROM invoice_items
        WHERE invoice_type = 'service'
          AND NOT EXISTS (
              SELECT 1
              FROM service_invoice_items s
              WHERE s.service_invoice_id = invoice_items.invoice_id
                AND s.description = invoice_items.description
                AND COALESCE(s.qty, 0) = COALESCE(invoice_items.qty, 0)
                AND COALESCE(s.unit_price, -1) = COALESCE(invoice_items.unit_price, -1)
                AND COALESCE(s.line_total, 0) = COALESCE(invoice_items.line_total, 0)
          );
        """
    )

    _mark_migration_applied(conn, version)


def _ensure_indexes(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_vendor_invoice_date
        ON vendor_invoices(invoice_date);
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_vendor_name
        ON vendor_invoices(vendor_name);
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_vendor_invoices_chat_created
        ON vendor_invoices(chat_id, created_at);
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_service_invoices_chat_created
        ON service_invoices(chat_id, created_at);
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_drafts_updated_at
        ON drafts(updated_at);
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_work_jobs_chat_start
        ON work_jobs(chat_id, start_dt);
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_work_jobs_status_start
        ON work_jobs(status, start_dt);
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_work_jobs_last_reminded
        ON work_jobs(last_reminded_at);
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_maint_chat_next_due
        ON maintenance_plans(chat_id, next_due_dt);
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_maint_status_next_due
        ON maintenance_plans(status, next_due_dt);
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_maintenance_last_reminded
        ON maintenance_plans(last_reminded_at);
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_order_parts_next_remind
        ON ordered_parts(installed, next_remind_dt);
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_order_parts_chat_next
        ON ordered_parts(chat_id, next_remind_dt);
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ordered_parts_last_reminded
        ON ordered_parts(last_reminded_at);
        """
    )


# ---------------------------------------------------------------------
# Aplicación principal
# ---------------------------------------------------------------------
def apply_schema(conn: sqlite3.Connection) -> None:
    """
    Aplica el schema base y luego ejecuta migraciones incrementales seguras.
    """
    conn.executescript(SCHEMA_SQL)
    _ensure_schema_migrations_table(conn)

    _migration_001_vendor_invoice_metadata(conn)
    _migration_002_coordinator_extra_columns(conn)
    _migration_003_invoice_and_service_updates(conn)
    _migration_004_split_invoice_items(conn)

    _ensure_indexes(conn)
    conn.commit()