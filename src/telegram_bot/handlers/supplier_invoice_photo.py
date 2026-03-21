from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from telegram import Update
from telegram.ext import ContextTypes

from src.core.utils_time import TimeContext
from src.db.connection import session
from src.db.repositories.supplier_invoices_repo import insert_supplier_invoice
from src.services.ocr_openai import extract_supplier_invoice


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _summarize_items(items: List[Dict[str, Any]], currency: str) -> str:
    if not items:
        return "• (Sin items detectados)\n"
    lines = []
    for it in items[:8]:  # máximo 8 líneas en chat
        desc = str(it.get("description", "Item")).strip()
        qty = _safe_float(it.get("qty", 1), 1)
        lt = _safe_float(it.get("line_total", 0), 0)
        lines.append(f"• {desc} x{qty:g} = {currency}{lt:.2f}")
    if len(items) > 8:
        lines.append(f"… +{len(items)-8} más")
    return "\n".join(lines) + "\n"


async def supplier_invoice_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Recibe foto de factura proveedor.
    - Descarga imagen
    - Activa IA (solo aquí) para extracción OCR
    - Guarda en SQLite (serializado con db_write_lock)
    - Responde con resumen al usuario
    """
    if not update.message or not update.message.photo:
        return

    chat_id = update.effective_chat.id
    tctx: TimeContext = context.bot_data["tctx"]
    project_root: Path = context.bot_data["project_root"]
    db_path = context.bot_data["db_path"]
    lock = context.bot_data["db_write_lock"]

    # 1) Descargar la imagen (fuera de DB)
    photos = update.message.photo
    best = photos[-1]  # mayor resolución
    tg_file = await best.get_file()

    inbox_dir = (project_root / "data" / "inbox").resolve()
    inbox_dir.mkdir(parents=True, exist_ok=True)

    img_path = inbox_dir / f"supplier_{chat_id}_{tctx.now_compact()}.jpg"
    await tg_file.download_to_drive(custom_path=str(img_path))

    await update.message.reply_text("🔎 Recibido. Analizando factura… (IA activada solo para esta imagen)")

    # 2) IA OCR (solo aquí)
    extracted = extract_supplier_invoice(img_path)

    vendor_name = extracted.get("vendor_name")
    vendor_id = extracted.get("vendor_id")
    invoice_number = extracted.get("invoice_number")
    invoice_date = extracted.get("invoice_date")
    currency = extracted.get("currency") or "USD"
    total = _safe_float(extracted.get("total", 0), 0)
    raw_text = extracted.get("raw_text") or ""
    items = extracted.get("items") or []

    # 3) Guardar en DB bajo lock (sin awaits dentro)
    async def _write():
        with session(db_path, immediate=True) as conn:
            return insert_supplier_invoice(
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
                image_path=str(img_path),
                created_at=tctx.now_iso(),
                items=items,
            )

    supplier_invoice_id = await lock.run(_write)

    # 4) Responder resumen
    items_txt = _summarize_items(items, "$" if currency.upper() == "USD" else f"{currency} ")
    total_label = "$" if currency.upper() == "USD" else f"{currency} "

    await update.message.reply_text(
        "✅ Factura de proveedor registrada\n"
        f"ID: {supplier_invoice_id}\n"
        f"Proveedor: {vendor_name or '—'}\n"
        f"Número: {invoice_number or '—'}\n"
        f"Fecha: {invoice_date or '—'}\n"
        f"Items:\n{items_txt}"
        f"TOTAL: {total_label}{total:.2f}\n\n"
        "📌 Quedó guardada para análisis en Streamlit."
    )
