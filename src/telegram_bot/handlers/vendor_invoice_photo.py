from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from telegram import Update
from telegram.ext import ContextTypes

from src.core.utils_time import TimeContext
from src.db.connection import session
from src.db.repositories.vendor_invoices_repo import insert_vendor_invoice
from src.services.ocr_openai import extract_vendor_invoice_from_image


def _safe_float(value: Any, default: float = 0.0) -> float:
    """
    Convierte un valor a float de forma segura.

    Parameters
    ----------
    value:
        Valor de entrada.
    default:
        Valor por defecto si la conversión falla.

    Returns
    -------
    float
        Valor convertido o el default.
    """
    try:
        return float(value)
    except Exception:
        return default


def _currency_label(currency: str) -> str:
    """
    Devuelve una etiqueta legible para mostrar montos en Telegram.

    Convención actual:
    - USD -> $
    - PAB -> $
    - cualquier otro código -> 'CODIGO '

    Parameters
    ----------
    currency:
        Código de moneda.

    Returns
    -------
    str
        Etiqueta visual para chat.
    """
    code = (currency or "").strip().upper()
    if code in {"USD", "PAB"}:
        return "$"
    return f"{code} " if code else ""


def _summarize_items(items: List[Dict[str, Any]], currency_label: str) -> str:
    """
    Resume los ítems detectados para mostrarlos en el chat.

    Parameters
    ----------
    items:
        Lista de ítems extraídos por OCR.
    currency_label:
        Símbolo o prefijo de moneda.

    Returns
    -------
    str
        Texto resumido de los ítems.
    """
    if not items:
        return "• (Sin items detectados)\n"

    lines: List[str] = []
    for item in items[:8]:
        description = str(item.get("description", "Item")).strip() or "Item"
        qty = _safe_float(item.get("qty", 1), 1.0)
        line_total = _safe_float(item.get("line_total", 0), 0.0)
        lines.append(f"• {description} x{qty:g} = {currency_label}{line_total:.2f}")

    if len(items) > 8:
        lines.append(f"… +{len(items) - 8} más")

    return "\n".join(lines) + "\n"


async def vendor_invoice_photo_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Procesa una foto de factura de proveedor enviada por Telegram.

    Flujo
    -----
    1. Descarga la imagen al inbox local del proyecto.
    2. Ejecuta OCR con IA únicamente para esa imagen.
    3. Guarda cabecera + detalle en SQLite.
    4. Responde con un resumen legible al usuario.

    Requisitos esperados en context.bot_data
    ----------------------------------------
    - tctx: TimeContext
    - project_root: Path
    - db_path: Path | str
    - db_write_lock: lock async con método run(...)
    """
    if not update.message or not update.message.photo:
        return

    chat_id = update.effective_chat.id
    tctx: TimeContext = context.bot_data["tctx"]
    project_root: Path = context.bot_data["project_root"]
    db_path = context.bot_data["db_path"]
    lock = context.bot_data["db_write_lock"]

    # ---------------------------------------------------------------
    # 1) Descargar imagen enviada por Telegram
    # ---------------------------------------------------------------
    best_photo = update.message.photo[-1]
    telegram_file = await best_photo.get_file()

    inbox_dir = (project_root / "data" / "inbox").resolve()
    inbox_dir.mkdir(parents=True, exist_ok=True)

    image_path = inbox_dir / f"vendor_{chat_id}_{tctx.now_compact()}.jpg"
    await telegram_file.download_to_drive(custom_path=str(image_path))

    image_file_id = best_photo.file_id

    await update.message.reply_text(
        "🔎 Factura de proveedor recibida. Analizando… (IA encendida solo para esta imagen)"
    )

    # ---------------------------------------------------------------
    # 2) OCR / extracción estructurada
    # ---------------------------------------------------------------
    try:
        extracted = extract_vendor_invoice_from_image(image_path)
    except Exception as exc:
        await update.message.reply_text(
            "❌ No pude analizar la factura con OCR.\n"
            f"Detalle: {exc}"
        )
        return

    vendor_name = extracted.get("vendor_name")
    vendor_id = extracted.get("vendor_id")
    invoice_number = extracted.get("invoice_number")
    invoice_date = extracted.get("invoice_date")
    currency = extracted.get("currency") or "PAB"
    total = _safe_float(extracted.get("total", 0), 0.0)
    raw_text = extracted.get("raw_text") or ""
    items = extracted.get("items") or []

    # ---------------------------------------------------------------
    # 3) Guardar en DB bajo lock de escritura
    # ---------------------------------------------------------------
    async def _write() -> int:
        with session(db_path, immediate=True) as conn:
            return insert_vendor_invoice(
                conn,
                chat_id=chat_id,
                vendor_name=vendor_name,
                vendor_id=vendor_id,
                invoice_number=invoice_number,
                invoice_date=invoice_date,
                currency=currency,
                total=total,
                raw_text=raw_text,
                extracted=extracted,
                image_file_id=image_file_id,
                image_path=str(image_path),
                created_at=tctx.now_iso(),
                items=items,
            )

    try:
        vendor_invoice_id = await lock.run(_write)
    except Exception as exc:
        await update.message.reply_text(
            "❌ La factura fue analizada, pero no se pudo guardar en la base de datos.\n"
            f"Detalle: {exc}"
        )
        return

    # ---------------------------------------------------------------
    # 4) Resumen de confirmación al usuario
    # ---------------------------------------------------------------
    currency_label = _currency_label(currency)
    items_text = _summarize_items(items, currency_label)

    await update.message.reply_text(
        "✅ Factura de proveedor registrada\n"
        f"ID: {vendor_invoice_id}\n"
        f"Proveedor: {vendor_name or '—'}\n"
        f"RUC/NIT: {vendor_id or '—'}\n"
        f"Número: {invoice_number or '—'}\n"
        f"Fecha: {invoice_date or '—'}\n"
        f"Items:\n{items_text}"
        f"TOTAL: {currency_label}{total:.2f}\n\n"
        "📌 Guardada para análisis en Streamlit."
    )