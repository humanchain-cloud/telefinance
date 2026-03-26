"""
schema.py
---------
Schema principal (DDL) de Telefinance.

Este módulo define el esquema base de SQLite para:

- Gastos de proveedores (OCR desde imagen)
- Ingresos por servicios (facturas emitidas por el bot)
- Coordinador de trabajo (agenda, mantenimientos, pedidos)
- Drafts del wizard de Telegram

Notas de diseño
----------------
1. Se separan los ítems de proveedores y servicios en tablas distintas
   para permitir integridad referencial real y consultas más claras.
2. Se incluyen restricciones CHECK para reforzar consistencia.
3. Los PRAGMA críticos deben aplicarse también desde connection.py.
"""

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS vendor_invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    vendor_name TEXT NOT NULL,
    vendor_external_id TEXT,
    invoice_number TEXT,
    invoice_date TEXT,
    currency TEXT NOT NULL DEFAULT 'PAB'
        CHECK(currency IN ('PAB', 'USD')),
    total REAL NOT NULL CHECK(total >= 0),
    raw_text TEXT NOT NULL,
    extracted_json TEXT,
    image_file_id TEXT,
    image_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS vendor_invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_invoice_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    qty REAL NOT NULL DEFAULT 1 CHECK(qty > 0),
    unit_price REAL CHECK(unit_price IS NULL OR unit_price >= 0),
    line_total REAL NOT NULL CHECK(line_total >= 0),
    created_at TEXT NOT NULL,
    FOREIGN KEY (vendor_invoice_id)
        REFERENCES vendor_invoices(id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS service_invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    consecutivo INTEGER UNIQUE,
    client_name TEXT NOT NULL,
    client_phone TEXT,
    service_date TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'PAB'
        CHECK(currency IN ('PAB', 'USD')),
    total REAL NOT NULL CHECK(total >= 0),
    pdf_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS service_invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_invoice_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    qty REAL NOT NULL DEFAULT 1 CHECK(qty > 0),
    unit_price REAL CHECK(unit_price IS NULL OR unit_price >= 0),
    line_total REAL NOT NULL CHECK(line_total >= 0),
    created_at TEXT NOT NULL,
    FOREIGN KEY (service_invoice_id)
        REFERENCES service_invoices(id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS drafts (
    chat_id INTEGER PRIMARY KEY,
    flow TEXT NOT NULL,
    step TEXT NOT NULL,
    data_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS work_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    client TEXT NOT NULL,
    phone TEXT NOT NULL,
    address_text TEXT NOT NULL,
    concept TEXT NOT NULL,
    start_dt TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'done', 'cancelled')),
    place_type TEXT,
    place_name TEXT,
    tower TEXT,
    apartment TEXT,
    waze_query TEXT,
    appliance TEXT,
    kind TEXT,
    last_reminded_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS maintenance_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    client TEXT NOT NULL,
    phone TEXT NOT NULL,
    ph_type TEXT NOT NULL
        CHECK(ph_type IN ('PH', 'Casa')),
    ph_name TEXT,
    address_text TEXT NOT NULL,
    waze_url TEXT,
    appliances_count INTEGER NOT NULL DEFAULT 1
        CHECK(appliances_count >= 1),
    appliances_json TEXT NOT NULL DEFAULT '[]',
    photos_json TEXT NOT NULL DEFAULT '[]',
    start_dt TEXT NOT NULL,
    next_due_dt TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active', 'done', 'cancelled')),
    last_reminded_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS ordered_parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    client TEXT NOT NULL,
    phone TEXT NOT NULL,
    address_text TEXT NOT NULL,
    part_desc TEXT NOT NULL,
    ordered_at TEXT NOT NULL,
    first_remind_dt TEXT NOT NULL,
    next_remind_dt TEXT NOT NULL,
    remind_count INTEGER NOT NULL DEFAULT 0
        CHECK(remind_count >= 0),
    arrived INTEGER NOT NULL DEFAULT 0
        CHECK(arrived IN (0, 1)),
    installed INTEGER NOT NULL DEFAULT 0
        CHECK(installed IN (0, 1)),
    legend TEXT,
    closed_at TEXT,
    last_reminded_at TEXT,
    waze_url TEXT,
    total_usd REAL CHECK(total_usd IS NULL OR total_usd >= 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_vendor_invoices_created_at
    ON vendor_invoices(created_at);

CREATE INDEX IF NOT EXISTS idx_vendor_invoices_chat_created
    ON vendor_invoices(chat_id, created_at);

CREATE INDEX IF NOT EXISTS idx_vendor_invoices_invoice_date
    ON vendor_invoices(invoice_date);

CREATE INDEX IF NOT EXISTS idx_vendor_invoices_vendor_name
    ON vendor_invoices(vendor_name);

CREATE INDEX IF NOT EXISTS idx_vendor_invoice_items_invoice_id
    ON vendor_invoice_items(vendor_invoice_id);

CREATE INDEX IF NOT EXISTS idx_vendor_invoice_items_desc
    ON vendor_invoice_items(description);

CREATE INDEX IF NOT EXISTS idx_service_invoices_created_at
    ON service_invoices(created_at);

CREATE INDEX IF NOT EXISTS idx_service_invoices_chat_created
    ON service_invoices(chat_id, created_at);

CREATE INDEX IF NOT EXISTS idx_service_invoices_service_date
    ON service_invoices(service_date);

CREATE INDEX IF NOT EXISTS idx_service_invoice_items_invoice_id
    ON service_invoice_items(service_invoice_id);

CREATE INDEX IF NOT EXISTS idx_service_invoice_items_desc
    ON service_invoice_items(description);

CREATE INDEX IF NOT EXISTS idx_drafts_updated_at
    ON drafts(updated_at);

CREATE INDEX IF NOT EXISTS idx_work_jobs_chat_start
    ON work_jobs(chat_id, start_dt);

CREATE INDEX IF NOT EXISTS idx_work_jobs_status_start
    ON work_jobs(status, start_dt);

CREATE INDEX IF NOT EXISTS idx_work_jobs_last_reminded
    ON work_jobs(last_reminded_at);

CREATE INDEX IF NOT EXISTS idx_maintenance_chat_next_due
    ON maintenance_plans(chat_id, next_due_dt);

CREATE INDEX IF NOT EXISTS idx_maintenance_status_next_due
    ON maintenance_plans(status, next_due_dt);

CREATE INDEX IF NOT EXISTS idx_maintenance_last_reminded
    ON maintenance_plans(last_reminded_at);

CREATE INDEX IF NOT EXISTS idx_ordered_parts_chat_next
    ON ordered_parts(chat_id, next_remind_dt);

CREATE INDEX IF NOT EXISTS idx_ordered_parts_next_remind
    ON ordered_parts(installed, next_remind_dt);

CREATE INDEX IF NOT EXISTS idx_ordered_parts_last_reminded
    ON ordered_parts(last_reminded_at);
"""