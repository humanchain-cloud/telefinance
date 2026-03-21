"""
invoice_parser.py
-----------------
Utilidades de parsing/normalización para Telefinance.

Este módulo NO genera PDFs ni toca DB.
Su responsabilidad es:
- Normalizar cadenas y montos.
- Convertir formatos de fecha para presentación en PDF.
- (Futuro) apoyar el parsing del texto OCR de facturas de proveedor.

Convenciones:
- DB puede guardar fechas en ISO: YYYY-MM-DD
- PDF/recibo se muestra en formato humano: DD/MM/YYYY
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from typing import Any, Optional


# ---------------------------------------------------------------------
# Fechas
# ---------------------------------------------------------------------
def iso_to_ddmmyyyy(date_str: str) -> str:
    """
    Convierte 'YYYY-MM-DD' -> 'DD/MM/YYYY'.

    Si no se puede parsear, devuelve el string original sin romper el flujo.

    Examples
    --------
    >>> iso_to_ddmmyyyy("2026-02-12")
    '12/02/2026'
    """
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return date_str


def ddmmyyyy_to_iso(date_str: str) -> str:
    """
    Convierte 'DD/MM/YYYY' -> 'YYYY-MM-DD'.

    Si no se puede parsear, devuelve el string original.

    Examples
    --------
    >>> ddmmyyyy_to_iso("12/02/2026")
    '2026-02-12'
    """
    try:
        dt = datetime.strptime(date_str.strip(), "%d/%m/%Y")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return date_str


def today_iso() -> str:
    """
    Devuelve la fecha de hoy en ISO (YYYY-MM-DD) usando reloj del sistema.
    """
    return date.today().isoformat()


# ---------------------------------------------------------------------
# Normalización básica
# ---------------------------------------------------------------------
def normalize_text(s: Any) -> str:
    """
    Normaliza texto:
    - Convierte a str
    - Trim
    - Colapsa espacios múltiples

    Nota:
    - No aplica "title()" porque a veces nombres técnicos necesitan mayúsculas exactas.
    """
    if s is None:
        return ""
    text = str(s).strip()
    # colapsa espacios
    while "  " in text:
        text = text.replace("  ", " ")
    return text


def to_float(value: Any, *, default: float = 0.0) -> float:
    """
    Convierte valores a float de forma tolerante.
    - Acepta "1,234.56" o "1234.56"
    - Acepta "1.234,56" (lo intenta normalizar si detecta coma decimal)

    Si falla, retorna default.
    """
    if value is None:
        return float(default)

    if isinstance(value, (int, float)):
        return float(value)

    s = normalize_text(value)

    # Normalización básica de separadores:
    # Caso típico US: 1,234.56 -> remover comas miles
    # Caso típico EU: 1.234,56 -> remover puntos miles, cambiar coma a punto
    try:
        if "," in s and "." in s:
            # Si la coma está después del punto, sugiere formato EU (1.234,56)
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        else:
            # Si solo hay coma, podría ser decimal
            if "," in s and "." not in s:
                s = s.replace(",", ".")
        return float(s)
    except Exception:
        return float(default)


def fmt_money(amount: float) -> str:
    """
    Formatea monto con 2 decimales.
    """
    try:
        return f"{float(amount):.2f}"
    except Exception:
        return "0.00"


def fmt_qty(qty: float) -> str:
    """
    Formatea cantidad:
    - entero -> sin decimales
    - no entero -> 2 decimales
    """
    try:
        q = float(qty)
        if abs(q - int(q)) < 1e-9:
            return str(int(q))
        return f"{q:.2f}"
    except Exception:
        return "1"
