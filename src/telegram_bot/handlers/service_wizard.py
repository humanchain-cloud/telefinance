"""
service_wizard.py
-----------------
Wizard por chat para crear recibos de servicio y operar el Coordinador de trabajo.

Incluye:
- Menú principal
- Wizard de recibo de servicio
- Coordinador:
    1) Agendar trabajo
    2) Agendar mantenimiento
    3) Resumen de trabajos
    4) Resumen de mantenimientos
    5) Registrar pedido de pieza
    6) Resumen de pedidos
    0) Volver al menú principal

Reglas operativas:
- Nunca mantener una conexión SQLite abierta mientras haya `await`
- Todas las escrituras pasan por `db_write_lock`
- Las lecturas usan `readonly_session()`
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from telegram import Update
from telegram.ext import ContextTypes

from src.core.config import Settings
from src.core.utils_time import TimeContext
from src.db.connection import readonly_session, session
from src.db.repositories import drafts_repo
from src.db.repositories.maintenance_repo import (
    insert_maintenance_plan,
    list_maintenances_next_12_months,
)
from src.db.repositories.ordered_parts_repo import (
    insert_ordered_part,
    list_due_order_reminders,
)
from src.db.repositories.service_invoices_repo import insert_service_invoice
from src.db.repositories.work_jobs_repo import (
    insert_work_job,
    list_upcoming_work_jobs,
)
from src.services.consecutivo import next_consecutivo
from src.services.invoice_builder import ServiceInvoicePayload, build_service_invoice_html
from src.services.invoice_parser import iso_to_ddmmyyyy
from src.services.pdf_renderer import render_pdf
from src.services.report_pdf import build_service_summary_pdf, build_vendor_summary_pdf
from src.telegram_bot.state.wizard_state import (
    FLOW_CREATE_SERVICE_INVOICE,
    FLOW_MAIN_MENU,
    FLOW_ORDER_REMINDER,
    FLOW_SCHEDULE_MAINTENANCE,
    FLOW_SCHEDULE_WORK,
    FLOW_WORK_COORDINATOR,
    STEP_CLIENT_NAME,
    STEP_COORD_MENU,
    STEP_DATE_CHOICE,
    STEP_DATE_MANUAL,
    STEP_ITEM_DESC,
    STEP_ITEM_MORE,
    STEP_ITEM_QTY,
    STEP_ITEM_UNIT,
    STEP_MAINT_ADDRESS,
    STEP_MAINT_APPLIANCE_ONE,
    STEP_MAINT_APPLIANCES_COUNT,
    STEP_MAINT_CLIENT,
    STEP_MAINT_PH_NAME,
    STEP_MAINT_PHOTOS,
    STEP_MAINT_PH_TYPE,
    STEP_MAINT_PHONE,
    STEP_MAINT_START_DT,
    STEP_MENU,
    STEP_ORDER_CLIENT,
    STEP_ORDER_DESC,
    STEP_ORDER_PHONE,
    STEP_ORDER_AWAIT_STATUS,
    STEP_WORK_ADDRESS,
    STEP_WORK_CLIENT,
    STEP_WORK_CONCEPT,
    STEP_WORK_PHONE,
    STEP_WORK_START_DT,
)


# ---------------------------------------------------------------------
# Helpers: resolución robusta de paths
# ---------------------------------------------------------------------
def _find_project_root_from_file() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "assets" / "factura.css").exists():
            return parent
    return here.parents[3] if len(here.parents) >= 4 else here.parent


def _resolve_project_root(context: ContextTypes.DEFAULT_TYPE) -> Path:
    proposed = context.bot_data.get("project_root")
    if proposed:
        proposed_path = Path(proposed).resolve()
        if (proposed_path / "assets" / "factura.css").exists():
            return proposed_path
    return _find_project_root_from_file()


# ---------------------------------------------------------------------
# UX helpers
# ---------------------------------------------------------------------
_ICON_TO_DIGIT = {
    "0️⃣": "0",
    "1️⃣": "1",
    "2️⃣": "2",
    "3️⃣": "3",
    "4️⃣": "4",
    "5️⃣": "5",
    "6️⃣": "6",
    "7️⃣": "7",
    "8️⃣": "8",
    "9️⃣": "9",
}


def _choice(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    if raw in _ICON_TO_DIGIT:
        return _ICON_TO_DIGIT[raw]
    if raw[0].isdigit():
        return raw[0]
    return raw


def _normalize_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _waze_from_text(q: str) -> str:
    query = (q or "").strip()
    if not query:
        return ""
    return f"https://waze.com/ul?q={quote_plus(query)}&navigate=yes"


# ---------------------------------------------------------------------
# Helpers para PDFs
# ---------------------------------------------------------------------
def _ensure_tctx(context: ContextTypes.DEFAULT_TYPE) -> TimeContext:
    from zoneinfo import ZoneInfo

    tctx = context.bot_data.get("tctx")
    if isinstance(tctx, TimeContext):
        return tctx

    tctx = TimeContext(ZoneInfo("America/Panama"))
    context.bot_data["tctx"] = tctx
    return tctx


def _track_bot_message(
    context: ContextTypes.DEFAULT_TYPE,
    message_id: int,
    max_keep: int = 200,
) -> None:
    ids = context.chat_data.get("bot_message_ids", [])
    ids.append(int(message_id))
    context.chat_data["bot_message_ids"] = ids[-max_keep:]


async def reply_text_tracked(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    **kwargs,
):
    msg = await update.message.reply_text(text, **kwargs)
    _track_bot_message(context, msg.message_id)
    return msg


async def reply_document_tracked(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    document,
    filename: str,
    caption: str | None = None,
    **kwargs,
):
    msg = await update.message.reply_document(
        document=document,
        filename=filename,
        caption=caption,
        **kwargs,
    )
    _track_bot_message(context, msg.message_id)
    return msg


async def _send_pdf_doc(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    pdf_path: Path,
    caption: str,
) -> None:
    with open(pdf_path, "rb") as file_obj:
        await reply_document_tracked(
            update,
            context,
            document=file_obj,
            filename=pdf_path.name,
            caption=caption,
        )


async def _clear_tracked_bot_messages(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    chat_id = update.effective_chat.id
    ids = list(context.chat_data.get("bot_message_ids", []))
    deleted = 0

    for message_id in reversed(ids):
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            deleted += 1
        except Exception:
            pass

    context.chat_data["bot_message_ids"] = []
    return deleted


def _help_text() -> str:
    return (
        "ℹ️ *Ayuda de Telefinance*\n\n"
        "*1️⃣ Crear recibo de servicio*\n"
        "Genera un recibo PDF por servicio realizado.\n\n"
        "*2️⃣ Coordinador de trabajo*\n"
        "Administra trabajos, mantenimientos y pedidos.\n\n"
        "*3️⃣ Dashboard (Ingresos/Gastos)*\n"
        "Abre el panel visual de Telefinance.\n\n"
        "*4️⃣ PDF Resumen Proveedores*\n"
        "Genera un reporte ejecutivo de gastos.\n\n"
        "*5️⃣ PDF Resumen Servicios*\n"
        "Genera un reporte ejecutivo de ingresos.\n\n"
        "*6️⃣ Limpiar mensajes del bot*\n"
        "Borra mensajes recientes enviados por el bot.\n\n"
        "*7️⃣ Ayuda*\n"
        "Muestra esta guía.\n\n"
        "*Cancelar durante un flujo*\n"
        "Escribe *0* para volver al menú principal.\n\n"
        "*Cómo responder*\n"
        "Puedes escribir el número simple (`4`) o el número ícono (`4️⃣`)."
    )


# ---------------------------------------------------------------------
# Parsing de fecha/hora
# ---------------------------------------------------------------------
def _parse_local_dt(text: str, tctx: TimeContext) -> Optional[str]:
    raw = (text or "").strip()
    if not raw:
        return None

    try:
        if " " not in raw and "T" not in raw:
            dt = datetime.fromisoformat(raw).replace(
                hour=8,
                minute=30,
                second=0,
                microsecond=0,
                tzinfo=tctx.tz,
            )
            return dt.isoformat(timespec="seconds")

        normalized = raw.replace(" ", "T")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tctx.tz)
        return dt.isoformat(timespec="seconds")
    except Exception:
        return None


_MONTHS_ES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_WEEKDAYS_ES = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "miércoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "sábado": 5,
    "domingo": 6,
}


def _resolve_no_year_date(
    tctx: TimeContext,
    *,
    day: int,
    month: int,
    weekday: Optional[int],
) -> Tuple[bool, Optional[str], str]:
    today = tctx.today()

    for year in (today.year, today.year + 1):
        try:
            dt = datetime(year, month, day)
        except ValueError:
            return False, None, "❌ Fecha inválida (día/mes no existen)."

        if dt.date() < today:
            continue

        if weekday is not None and dt.weekday() != weekday:
            return False, None, "❌ El día de la semana no coincide."

        return True, dt.date().isoformat(), ""

    return False, None, "❌ Esa fecha ya pasó. Escribe otra fecha futura."


def _parse_day_no_year(text: str, tctx: TimeContext) -> Tuple[bool, Optional[str], str]:
    raw = re.sub(r"\s+", " ", (text or "").strip().lower())

    match = re.match(r"^(\d{1,2})/(\d{1,2})$", raw)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        return _resolve_no_year_date(tctx, day=day, month=month, weekday=None)

    parts = raw.split(" ")
    weekday = None

    if parts and parts[0] in _WEEKDAYS_ES:
        weekday = _WEEKDAYS_ES[parts[0]]
        parts = parts[1:]

    if len(parts) < 2:
        return False, None, "❌ Formato inválido. Ej: `martes 3 marzo`, `3 marzo` o `03/03`."

    try:
        day = int(parts[0])
    except Exception:
        return False, None, "❌ Día inválido."

    month_txt = parts[1]
    if month_txt not in _MONTHS_ES:
        return False, None, "❌ Mes inválido."

    month = _MONTHS_ES[month_txt]
    return _resolve_no_year_date(tctx, day=day, month=month, weekday=weekday)


def _parse_time(text: str) -> Tuple[bool, Optional[Tuple[int, int]], str]:
    raw = (text or "").strip().lower().replace(" ", "")
    match = re.match(r"^(\d{1,2}):(\d{2})(am|pm)?$", raw)
    if not match:
        return False, None, "❌ Hora inválida. Ej: `16:25`, `08:30`, `4:25pm`."

    hh = int(match.group(1))
    mm = int(match.group(2))
    ap = match.group(3)

    if mm < 0 or mm > 59:
        return False, None, "❌ Minutos inválidos."

    if ap:
        if hh < 1 or hh > 12:
            return False, None, "❌ Hora inválida en formato AM/PM."
        if ap == "pm" and hh != 12:
            hh += 12
        if ap == "am" and hh == 12:
            hh = 0
    else:
        if hh < 0 or hh > 23:
            return False, None, "❌ Hora inválida (0-23)."

    return True, (hh, mm), ""


# ---------------------------------------------------------------------
# UI texts
# ---------------------------------------------------------------------
def _menu_text() -> str:
    return (
        "✅ *Telefinance*\n\n"
        "*Menú principal*\n"
        "1️⃣ 🧾 Crear recibo de servicio\n\n"
        "2️⃣ 🗓️ Coordinador de trabajo\n\n"
        "3️⃣ 📊 Dashboard (Ingresos/Gastos)\n\n"
        "4️⃣ 🧾 PDF Resumen Proveedores\n\n"
        "5️⃣ 🧾 PDF Resumen Servicios\n\n"
        "6️⃣ 🧹 Limpiar mensajes del bot\n\n"
        "7️⃣ ℹ️ Ayuda\n\n"
        "Responde con el número ícono o el dígito.\n\n"
        "Durante un flujo activo puedes escribir *0* para volver al menú principal."
    )


def _coord_menu_text() -> str:
    return (
        "🗓️ *Coordinador de trabajo*\n\n"
        "1️⃣ 📌 Agendar trabajo\n\n"
        "2️⃣ 🧰 Agendar mantenimiento\n\n"
        "3️⃣ 📋 Resumen de trabajos agendados\n\n"
        "4️⃣ 🗓️ Resumen de mantenimientos programados\n\n"
        "5️⃣ 📦 Registrar pedido de pieza\n\n"
        "6️⃣ 🧾 Resumen de pedidos\n\n"
        "0️⃣ 🔙 Volver al menú principal"
    )


def _new_invoice_draft() -> Dict[str, Any]:
    return {
        "client_name": None,
        "service_date": None,
        "currency": "USD",
        "items": [],
        "current_item": {},
    }


def _new_coord_draft() -> Dict[str, Any]:
    return {
        "mode": "coord",
        "flow": None,
        "tmp": {},
    }


# ---------------------------------------------------------------------
# DB helpers draft
# ---------------------------------------------------------------------
def _draft_read(db_path: str | Path, chat_id: int):
    with readonly_session(db_path) as conn:
        return drafts_repo.get(conn, chat_id)


async def _draft_write(context: ContextTypes.DEFAULT_TYPE, fn):
    db_path = context.bot_data["db_path"]
    lock = context.bot_data["db_write_lock"]

    async def _do():
        with session(db_path, immediate=True) as conn:
            return fn(conn)

    return await lock.run(_do)


# ---------------------------------------------------------------------
# Navegación
# ---------------------------------------------------------------------
async def _go_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    tctx: TimeContext = context.bot_data["tctx"]

    await _draft_write(
        context,
        lambda conn: drafts_repo.upsert(
            conn,
            chat_id,
            FLOW_MAIN_MENU,
            STEP_MENU,
            {"screen": "main"},
            tctx.now_iso(),
        ),
    )
    await reply_text_tracked(update, context, _menu_text(), parse_mode="Markdown")


async def _go_coord_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    tctx: TimeContext = context.bot_data["tctx"]

    await _draft_write(
        context,
        lambda conn: drafts_repo.upsert(
            conn,
            chat_id,
            FLOW_WORK_COORDINATOR,
            STEP_COORD_MENU,
            _new_coord_draft(),
            tctx.now_iso(),
        ),
    )
    await reply_text_tracked(update, context, _coord_menu_text(), parse_mode="Markdown")


async def start_service_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    tctx: TimeContext = context.bot_data["tctx"]

    await _draft_write(
        context,
        lambda conn: drafts_repo.upsert(
            conn,
            chat_id,
            FLOW_CREATE_SERVICE_INVOICE,
            STEP_CLIENT_NAME,
            _new_invoice_draft(),
            tctx.now_iso(),
        ),
    )

    await reply_text_tracked(
        update,
        context,
        "🧾 *Recibo por servicio*\n\n1️⃣ Escribe el *nombre del cliente*:",
        parse_mode="Markdown",
    )


async def crear_factura_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start_service_invoice(update, context)


# ---------------------------------------------------------------------
# Router de fotos para mantenimiento
# ---------------------------------------------------------------------
async def wizard_photo_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.photo:
        return

    chat_id = update.effective_chat.id
    tctx: TimeContext = context.bot_data["tctx"]
    db_path = context.bot_data["db_path"]

    draft = _draft_read(db_path, chat_id)
    if not draft:
        return

    if draft.flow != FLOW_SCHEDULE_MAINTENANCE or draft.step != STEP_MAINT_PHOTOS:
        return

    data = draft.data
    tmp = data.setdefault("tmp", {})
    expected = int(tmp.get("appliances_count", 1))
    photos: List[str] = list(tmp.get("photos", []))

    project_root = _resolve_project_root(context)
    inbox_dir = (project_root / "data" / "inbox").resolve()
    inbox_dir.mkdir(parents=True, exist_ok=True)

    photo = update.message.photo[-1]
    tg_file = await photo.get_file()

    idx = len(photos) + 1
    filename = f"maintenance_{chat_id}_{tctx.now_compact()}_{idx}.jpg"
    save_path = inbox_dir / filename

    await tg_file.download_to_drive(custom_path=str(save_path))
    photos.append(str(save_path))
    tmp["photos"] = photos

    await _draft_write(
        context,
        lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, draft.step, data, tctx.now_iso()),
    )

    if len(photos) < expected:
        await reply_text_tracked(
            update,
            context,
            f"📸 Foto recibida ✅ ({len(photos)}/{expected}).\n"
            f"Envía la siguiente foto ({len(photos)+1}/{expected}).",
        )
        return

    await _draft_write(
        context,
        lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_MAINT_START_DT, data, tctx.now_iso()),
    )
    await reply_text_tracked(
        update,
        context,
        "✅ Fotos completas.\n\n"
        "Ahora escribe la *fecha y hora del mantenimiento*:\n"
        "- Formato: `YYYY-MM-DD HH:MM`\n"
        "- Ejemplo: `2026-02-21 08:30`",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------
# Menú principal
# ---------------------------------------------------------------------
async def _handle_main_menu_choice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    choice: str,
    *,
    tctx: TimeContext,
    db_path: str | Path,
) -> bool:
    chat_id = update.effective_chat.id

    if choice == "1":
        await start_service_invoice(update, context)
        return True

    if choice == "2":
        await _go_coord_menu(update, context)
        return True

    if choice == "3":
        settings = Settings()
        dash_url = settings.TELEFINANCE_DASHBOARD_URL.rstrip("/")
        await reply_text_tracked(
            update,
            context,
            "📈 *Dashboard (Ingresos/Gastos)*\n"
            f"👉 {dash_url}\n\n"
            "Tip: expón Streamlit con túnel o reverse proxy para acceso externo.",
            parse_mode="Markdown",
        )
        return True

    if choice == "4":
        await reply_text_tracked(
            update,
            context,
            "⏳ Generando *Resumen Proveedores (Gastos)*…",
            parse_mode="Markdown",
        )
        try:
            pdf_path = build_vendor_summary_pdf(
                db_path=Path(db_path),
                tctx=_ensure_tctx(context),
                days=30,
            )
            await _send_pdf_doc(
                update,
                context,
                pdf_path,
                "🧾 Resumen Proveedores (Gastos) — últimos 30 días",
            )
        except Exception as exc:
            await reply_text_tracked(
                update,
                context,
                f"❌ No pude generar el PDF de proveedores.\n\nDetalle: `{exc}`",
                parse_mode="Markdown",
            )

        await reply_text_tracked(update, context, _menu_text(), parse_mode="Markdown")
        return True

    if choice == "5":
        await reply_text_tracked(
            update,
            context,
            "⏳ Generando *Resumen Servicios (Ingresos)*…",
            parse_mode="Markdown",
        )
        try:
            pdf_path = build_service_summary_pdf(
                db_path=Path(db_path),
                tctx=_ensure_tctx(context),
                days=30,
            )
            await _send_pdf_doc(
                update,
                context,
                pdf_path,
                "🧾 Resumen Servicios (Ingresos) — últimos 30 días",
            )
        except Exception as exc:
            await reply_text_tracked(
                update,
                context,
                f"❌ No pude generar el PDF de servicios.\n\nDetalle: `{exc}`",
                parse_mode="Markdown",
            )

        await reply_text_tracked(update, context, _menu_text(), parse_mode="Markdown")
        return True

    if choice == "6":
        deleted = await _clear_tracked_bot_messages(update, context)
        await _draft_write(context, lambda conn: drafts_repo.delete(conn, chat_id))

        msg = await update.message.reply_text(
            f"🧹 Limpieza completada. Mensajes del bot eliminados: *{deleted}*\n\n"
            "✅ Contexto reiniciado.",
            parse_mode="Markdown",
        )
        _track_bot_message(context, msg.message_id)

        menu_msg = await update.message.reply_text(_menu_text(), parse_mode="Markdown")
        _track_bot_message(context, menu_msg.message_id)
        return True

    if choice == "7":
        await reply_text_tracked(update, context, _help_text(), parse_mode="Markdown")
        await reply_text_tracked(update, context, _menu_text(), parse_mode="Markdown")
        return True

    return False


# ---------------------------------------------------------------------
# Router principal de texto
# ---------------------------------------------------------------------
async def wizard_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    choice = _choice(text)

    tctx: TimeContext = context.bot_data["tctx"]
    paths = context.bot_data["paths"]
    db_path = context.bot_data["db_path"]
    project_root = _resolve_project_root(context)

    draft = _draft_read(db_path, chat_id)

    if not draft:
        if choice in {"0", "1", "2", "3", "4", "5", "6", "7"}:
            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(
                    conn,
                    chat_id,
                    FLOW_MAIN_MENU,
                    STEP_MENU,
                    {"screen": "main"},
                    tctx.now_iso(),
                ),
            )
            handled = await _handle_main_menu_choice(
                update,
                context,
                choice,
                tctx=tctx,
                db_path=db_path,
            )
            if handled:
                return

        await _draft_write(
            context,
            lambda conn: drafts_repo.upsert(
                conn,
                chat_id,
                FLOW_MAIN_MENU,
                STEP_MENU,
                {"screen": "main"},
                tctx.now_iso(),
            ),
        )
        await reply_text_tracked(update, context, _menu_text(), parse_mode="Markdown")
        return

    # Cancelación global
    if choice == "0":
        await _draft_write(context, lambda conn: drafts_repo.delete(conn, chat_id))
        await _go_menu(update, context)
        return

    # -------------------------------------------------------------
    # MENÚ PRINCIPAL
    # -------------------------------------------------------------
    if draft.flow == FLOW_MAIN_MENU and draft.step == STEP_MENU:
        handled = await _handle_main_menu_choice(
            update,
            context,
            choice,
            tctx=tctx,
            db_path=db_path,
        )
        if handled:
            return

        await reply_text_tracked(
            update,
            context,
            "❌ Opción inválida.\n\n" + _menu_text(),
            parse_mode="Markdown",
        )
        return

    # -------------------------------------------------------------
    # SUBMENÚ COORDINADOR
    # -------------------------------------------------------------
    if draft.flow == FLOW_WORK_COORDINATOR and draft.step == STEP_COORD_MENU:
        data = draft.data
        tmp = data.setdefault("tmp", {})

        if choice == "1":
            data["flow"] = "work"
            tmp.clear()
            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(
                    conn,
                    chat_id,
                    FLOW_SCHEDULE_WORK,
                    STEP_WORK_CLIENT,
                    data,
                    tctx.now_iso(),
                ),
            )
            await reply_text_tracked(
                update,
                context,
                "📌 *Agendar trabajo*\n\n1️⃣ Escribe el *nombre del cliente*:",
                parse_mode="Markdown",
            )
            return

        if choice == "2":
            data["flow"] = "maint"
            tmp.clear()
            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(
                    conn,
                    chat_id,
                    FLOW_SCHEDULE_MAINTENANCE,
                    STEP_MAINT_CLIENT,
                    data,
                    tctx.now_iso(),
                ),
            )
            await reply_text_tracked(
                update,
                context,
                "🧰 *Agendar mantenimiento*\n\n1️⃣ Escribe el *nombre del cliente*:",
                parse_mode="Markdown",
            )
            return

        if choice == "3":
            with readonly_session(db_path) as conn:
                rows = list_upcoming_work_jobs(conn, tctx.now_iso(), days_ahead=14)

            if not rows:
                await reply_text_tracked(update, context, "📋 No hay trabajos pendientes agendados.")
                await reply_text_tracked(update, context, _coord_menu_text(), parse_mode="Markdown")
                return

            lines = []
            for row in rows[:25]:
                dt_show = (row.start_dt or "").replace("T", " ")
                lines.append(
                    f"• *{dt_show}* — {row.client} ({row.phone})\n"
                    f"  {row.address_text}\n"
                    f"  _{row.concept}_"
                )

            await reply_text_tracked(
                update,
                context,
                "📋 *Trabajos agendados (pendientes)*\n\n" + "\n\n".join(lines),
                parse_mode="Markdown",
            )
            await reply_text_tracked(update, context, _coord_menu_text(), parse_mode="Markdown")
            return

        if choice == "4":
            with readonly_session(db_path) as conn:
                rows = list_maintenances_next_12_months(conn, tctx.now_iso())

            if not rows:
                await reply_text_tracked(update, context, "🗓️ No hay mantenimientos activos programados.")
                await reply_text_tracked(update, context, _coord_menu_text(), parse_mode="Markdown")
                return

            lines = []
            for row in rows[:25]:
                due_show = (row.next_due_dt or "").replace("T", " ")
                lines.append(
                    f"• *Vence:* {due_show}\n"
                    f"  {row.client} ({row.phone}) — {row.ph_type}{(' - ' + row.ph_name) if row.ph_name else ''}\n"
                    f"  {row.address_text}\n"
                    f"  Waze: {row.waze_url or '—'}"
                )

            await reply_text_tracked(
                update,
                context,
                "🗓️ *Mantenimientos (próximos)*\n\n" + "\n\n".join(lines),
                parse_mode="Markdown",
            )
            await reply_text_tracked(update, context, _coord_menu_text(), parse_mode="Markdown")
            return

        if choice == "5":
            data["flow"] = "order"
            tmp.clear()
            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(
                    conn,
                    chat_id,
                    FLOW_ORDER_REMINDER,
                    STEP_ORDER_CLIENT,
                    data,
                    tctx.now_iso(),
                ),
            )
            await reply_text_tracked(
                update,
                context,
                "📦 *Pedido de pieza*\n\n1️⃣ Escribe el *nombre del cliente*:",
                parse_mode="Markdown",
            )
            return

        if choice == "6":
            with readonly_session(db_path) as conn:
                rows = list_due_order_reminders(conn, tctx.now_iso())

            if not rows:
                await reply_text_tracked(update, context, "🧾 No hay pedidos pendientes registrados.")
                await reply_text_tracked(update, context, _coord_menu_text(), parse_mode="Markdown")
                return

            lines = []
            for row in rows[:25]:
                total_show = f"${float(row.total_usd):.2f}" if row.total_usd is not None else "—"
                dt_show = (row.next_remind_dt or "").replace("T", " ")
                lines.append(
                    f"• 🆔 `{row.id}` — *{row.client}* (`{row.phone}`)\n"
                    f"  📍 {row.address_text}\n"
                    f"  🧩 _{row.part_desc}_\n"
                    f"  💵 Total: *{total_show}*\n"
                    f"  🚗 Waze: {row.waze_url or '—'}\n"
                    f"  ⏰ Próximo recordatorio: *{dt_show}*"
                )

            await reply_text_tracked(
                update,
                context,
                "🧾 *Pedidos pendientes (piezas)*\n\n" + "\n\n".join(lines),
                parse_mode="Markdown",
                disable_web_page_preview=False,
            )
            await reply_text_tracked(update, context, _coord_menu_text(), parse_mode="Markdown")
            return

        await reply_text_tracked(
            update,
            context,
            "❌ Opción inválida.\n\n" + _coord_menu_text(),
            parse_mode="Markdown",
        )
        return

    # -------------------------------------------------------------
    # FLOW: AGENDAR TRABAJO
    # -------------------------------------------------------------
    if draft.flow == FLOW_SCHEDULE_WORK:
        data = draft.data
        tmp = data.setdefault("tmp", {})

        STEP_WORK_PLACE_TYPE = "work_place_type"
        STEP_WORK_PLACE_NAME = "work_place_name"
        STEP_WORK_TOWER = "work_tower"
        STEP_WORK_APARTMENT = "work_apartment"
        STEP_WORK_WAZE_QUERY = "work_waze_query"
        STEP_WORK_DAY = "work_day"
        STEP_WORK_TIME = "work_time"
        STEP_WORK_APPLIANCE = "work_appliance"
        STEP_WORK_KIND = "work_kind"
        STEP_WORK_CONFIRM = "work_confirm"

        if draft.step == STEP_WORK_CLIENT:
            if not text:
                await reply_text_tracked(update, context, "❌ Escribe un nombre válido.")
                return
            tmp.clear()
            tmp["client"] = text
            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_WORK_PHONE, data, tctx.now_iso()),
            )
            await reply_text_tracked(update, context, "2️⃣ Escribe el teléfono del cliente:")
            return

        if draft.step == STEP_WORK_PHONE:
            if not text:
                await reply_text_tracked(update, context, "❌ Escribe un teléfono válido.")
                return
            tmp["phone"] = text
            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_WORK_PLACE_TYPE, data, tctx.now_iso()),
            )
            await reply_text_tracked(
                update,
                context,
                "3️⃣ Tipo de lugar:\n\n1️⃣ Casa\n\n2️⃣ PH\n\nResponde 1️⃣ o 2️⃣.",
                parse_mode="Markdown",
            )
            return

        if draft.step == STEP_WORK_PLACE_TYPE:
            if choice == "1":
                tmp["place_type"] = "Casa"
            elif choice == "2":
                tmp["place_type"] = "PH"
            else:
                await reply_text_tracked(update, context, "Responde 1️⃣ (Casa) o 2️⃣ (PH).")
                return

            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_WORK_PLACE_NAME, data, tctx.now_iso()),
            )
            await reply_text_tracked(
                update,
                context,
                "4️⃣ Escribe nombre del PH / barriada / referencia:\n\n"
                "Ej: `PH The Cosmopolitan` o `Brisas del Golf`",
                parse_mode="Markdown",
            )
            return

        if draft.step == STEP_WORK_PLACE_NAME:
            if not text:
                await reply_text_tracked(update, context, "❌ Escribe una referencia válida.")
                return
            tmp["place_name"] = text
            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_WORK_TOWER, data, tctx.now_iso()),
            )
            await reply_text_tracked(
                update,
                context,
                "5️⃣ Torre (opcional). Si no aplica escribe `-`.",
                parse_mode="Markdown",
            )
            return

        if draft.step == STEP_WORK_TOWER:
            tower = text.strip()
            tmp["tower"] = None if tower == "-" else tower
            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_WORK_APARTMENT, data, tctx.now_iso()),
            )
            await reply_text_tracked(
                update,
                context,
                "6️⃣ Apartamento (obligatorio):\n\nEj: `12A` / `305` / `A-17`",
                parse_mode="Markdown",
            )
            return

        if draft.step == STEP_WORK_APARTMENT:
            if not text:
                await reply_text_tracked(update, context, "❌ Apartamento inválido.")
                return
            tmp["apartment"] = text.strip()
            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_WORK_WAZE_QUERY, data, tctx.now_iso()),
            )
            await reply_text_tracked(
                update,
                context,
                "7️⃣ Ubicación para Waze:\n\nEj: `PH The Cosmopolitan Bella Vista`",
                parse_mode="Markdown",
            )
            return

        if draft.step == STEP_WORK_WAZE_QUERY:
            if not text:
                await reply_text_tracked(update, context, "❌ Ubicación inválida.")
                return
            tmp["waze_query"] = text.strip()
            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_WORK_DAY, data, tctx.now_iso()),
            )
            await reply_text_tracked(
                update,
                context,
                "8️⃣ Día del servicio (sin año):\n\nEj: `martes 3 marzo` / `3 marzo` / `03/03`",
                parse_mode="Markdown",
            )
            return

        if draft.step == STEP_WORK_DAY:
            ok, iso_date, err = _parse_day_no_year(text, tctx)
            if not ok or not iso_date:
                await reply_text_tracked(update, context, err or "❌ Fecha inválida.")
                return

            tmp["iso_date"] = iso_date
            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_WORK_TIME, data, tctx.now_iso()),
            )
            await reply_text_tracked(
                update,
                context,
                "9️⃣ Hora:\n\nEj: `16:25` / `4:25pm` / `08:30`",
                parse_mode="Markdown",
            )
            return

        if draft.step == STEP_WORK_TIME:
            ok, hm, err = _parse_time(text)
            if not ok or not hm:
                await reply_text_tracked(update, context, err or "❌ Hora inválida.")
                return

            hh, mm = hm
            iso_date = str(tmp["iso_date"])
            dt = datetime.fromisoformat(iso_date).replace(
                hour=hh,
                minute=mm,
                second=0,
                microsecond=0,
                tzinfo=tctx.tz,
            )
            tmp["start_dt"] = dt.isoformat(timespec="seconds")

            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_WORK_APPLIANCE, data, tctx.now_iso()),
            )
            await reply_text_tracked(
                update,
                context,
                "🔟 Electrodoméstico:\n\nEj: `Lavadora - LG` / `Nevera - Samsung`",
                parse_mode="Markdown",
            )
            return

        if draft.step == STEP_WORK_APPLIANCE:
            if not text:
                await reply_text_tracked(update, context, "❌ Escribe un electrodoméstico válido.")
                return
            tmp["appliance"] = text.strip()

            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_WORK_KIND, data, tctx.now_iso()),
            )
            await reply_text_tracked(
                update,
                context,
                "1️⃣1️⃣ Tipo:\n\n1️⃣ Falla\n\n2️⃣ Mantenimiento",
                parse_mode="Markdown",
            )
            return

        if draft.step == STEP_WORK_KIND:
            if choice == "1":
                tmp["kind"] = "falla"
            elif choice == "2":
                tmp["kind"] = "mantenimiento"
            else:
                await reply_text_tracked(update, context, "Responde 1️⃣ o 2️⃣.")
                return

            tmp["concept"] = f"{tmp['appliance']} | {tmp['kind']}"

            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_WORK_CONFIRM, data, tctx.now_iso()),
            )
            await reply_text_tracked(
                update,
                context,
                "✅ Confirma el agendamiento:\n\n"
                f"👤 Cliente: *{tmp['client']}* ({tmp['phone']})\n"
                f"🏠 Lugar: {tmp['place_type']} — {tmp['place_name']}\n"
                f"🏢 Torre: {tmp.get('tower') or '-'}\n"
                f"🚪 Apto: *{tmp['apartment']}*\n"
                f"📍 Waze: {tmp['waze_query']}\n"
                f"🗓️ Fecha/Hora: *{str(tmp['start_dt']).replace('T', ' ')}*\n"
                f"🧾 Equipo: {tmp['appliance']}\n"
                f"🛠️ Tipo: {tmp['kind']}\n\n"
                "1️⃣ Guardar\n"
                "2️⃣ Cancelar",
                parse_mode="Markdown",
            )
            return

        if draft.step == STEP_WORK_CONFIRM:
            if choice == "2":
                await _go_coord_menu(update, context)
                return

            if choice != "1":
                await reply_text_tracked(update, context, "Responde 1️⃣ (Guardar) o 2️⃣ (Cancelar).")
                return

            def _save(conn):
                insert_work_job(
                    conn,
                    chat_id=chat_id,
                    client=str(tmp["client"]),
                    phone=str(tmp["phone"]),
                    address_text=str(tmp["place_name"]),
                    concept=str(tmp["concept"]),
                    start_dt_iso=str(tmp["start_dt"]),
                    created_at=tctx.now_iso(),
                    place_type=str(tmp["place_type"]),
                    place_name=str(tmp["place_name"]),
                    tower=tmp.get("tower"),
                    apartment=str(tmp["apartment"]),
                    waze_query=str(tmp["waze_query"]),
                    appliance=str(tmp["appliance"]),
                    kind=str(tmp["kind"]),
                )
                drafts_repo.upsert(
                    conn,
                    chat_id,
                    FLOW_WORK_COORDINATOR,
                    STEP_COORD_MENU,
                    _new_coord_draft(),
                    tctx.now_iso(),
                )

            await _draft_write(context, _save)

            await reply_text_tracked(
                update,
                context,
                "✅ *Trabajo agendado*\n\n"
                f"Cliente: *{tmp['client']}* ({tmp['phone']})\n"
                f"Lugar: {tmp['place_type']} — {tmp['place_name']} | Torre: {tmp.get('tower') or '-'} | Apto: *{tmp['apartment']}*\n"
                f"Waze: {tmp['waze_query']}\n"
                f"Fecha/Hora: *{str(tmp['start_dt']).replace('T', ' ')}*\n"
                f"Equipo: {tmp['appliance']} | Tipo: {tmp['kind']}",
                parse_mode="Markdown",
            )
            await reply_text_tracked(update, context, _coord_menu_text(), parse_mode="Markdown")
            return

        await _draft_write(context, lambda conn: drafts_repo.delete(conn, chat_id))
        await _go_menu(update, context)
        return

    # -------------------------------------------------------------
    # FLOW: AGENDAR MANTENIMIENTO
    # -------------------------------------------------------------
    if draft.flow == FLOW_SCHEDULE_MAINTENANCE:
        data = draft.data
        tmp = data.setdefault("tmp", {})

        if draft.step == STEP_MAINT_CLIENT:
            if not text:
                await reply_text_tracked(update, context, "❌ Escribe un nombre válido.")
                return

            tmp.clear()
            tmp["client"] = text.strip()

            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_MAINT_PHONE, data, tctx.now_iso()),
            )
            await reply_text_tracked(update, context, "2️⃣ Escribe el *teléfono* del cliente:")
            return

        if draft.step == STEP_MAINT_PHONE:
            if not text:
                await reply_text_tracked(update, context, "❌ Escribe un teléfono válido.")
                return

            tmp["phone"] = text.strip()

            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_MAINT_PH_TYPE, data, tctx.now_iso()),
            )
            await reply_text_tracked(
                update,
                context,
                "3️⃣ ¿Es *PH* o *Casa*?\n\n1️⃣ PH\n2️⃣ Casa",
                parse_mode="Markdown",
            )
            return

        if draft.step == STEP_MAINT_PH_TYPE:
            if choice == "1":
                tmp["ph_type"] = "PH"
                await _draft_write(
                    context,
                    lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_MAINT_PH_NAME, data, tctx.now_iso()),
                )
                await reply_text_tracked(update, context, "4️⃣ Escribe el *nombre del PH*:")
                return

            if choice == "2":
                tmp["ph_type"] = "Casa"
                tmp["ph_name"] = None
                await _draft_write(
                    context,
                    lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_MAINT_ADDRESS, data, tctx.now_iso()),
                )
                await reply_text_tracked(update, context, "4️⃣ Escribe la *dirección*:")
                return

            await reply_text_tracked(update, context, "Responde 1️⃣ (PH) o 2️⃣ (Casa).")
            return

        if draft.step == STEP_MAINT_PH_NAME:
            if not text:
                await reply_text_tracked(update, context, "❌ Escribe un nombre de PH válido.")
                return

            tmp["ph_name"] = text.strip()

            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_MAINT_ADDRESS, data, tctx.now_iso()),
            )
            await reply_text_tracked(update, context, "5️⃣ Escribe la *dirección*:")
            return

        if draft.step == STEP_MAINT_ADDRESS:
            if not text:
                await reply_text_tracked(update, context, "❌ Escribe una dirección válida.")
                return

            tmp["address_text"] = text.strip()

            if str(tmp.get("ph_type") or "").upper() == "PH" and tmp.get("ph_name"):
                waze_query = f"{tmp.get('ph_name')} {tmp['address_text']}"
            else:
                waze_query = tmp["address_text"]

            tmp["waze_url"] = _waze_from_text(waze_query)

            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_MAINT_APPLIANCES_COUNT, data, tctx.now_iso()),
            )
            await reply_text_tracked(
                update,
                context,
                "✅ Dirección registrada.\n📍 Waze generado automáticamente.\n\n"
                "6️⃣ ¿Cuántos electrodomésticos se les hará mantenimiento?",
            )
            return

        if draft.step == STEP_MAINT_APPLIANCES_COUNT:
            try:
                n = int((text or "").strip())
            except Exception:
                await reply_text_tracked(update, context, "❌ Número inválido. Ejemplo: 2")
                return

            if n <= 0 or n > 10:
                await reply_text_tracked(update, context, "❌ Debe ser entre 1 y 10.")
                return

            tmp["appliances_count"] = n
            tmp["appliances"] = []
            tmp["appliance_idx"] = 0

            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_MAINT_APPLIANCE_ONE, data, tctx.now_iso()),
            )
            await reply_text_tracked(
                update,
                context,
                f"7️⃣ Equipo 1/{n}\n\n"
                "Escribe: *tipo - marca - modelo*\n\n"
                "Ej: `Lavadora - Samsung - WA13T5260BV`\n"
                "Si no sabes el modelo: `Lavadora - Samsung - (sin modelo)`",
                parse_mode="Markdown",
            )
            return

        if draft.step == STEP_MAINT_APPLIANCE_ONE:
            n = int(tmp.get("appliances_count", 1))
            idx = int(tmp.get("appliance_idx", 0))

            parts = [p.strip() for p in (text or "").split("-") if p.strip()]
            if len(parts) < 3:
                await reply_text_tracked(
                    update,
                    context,
                    "❌ Formato inválido.\n\nDebe ser: *tipo - marca - modelo*",
                    parse_mode="Markdown",
                )
                return

            appliance = {"type": parts[0], "brand": parts[1], "model": parts[2]}
            appliances = list(tmp.get("appliances", []))
            appliances.append(appliance)

            tmp["appliances"] = appliances
            tmp["appliance_idx"] = idx + 1

            if idx + 1 < n:
                await _draft_write(
                    context,
                    lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_MAINT_APPLIANCE_ONE, data, tctx.now_iso()),
                )
                await reply_text_tracked(
                    update,
                    context,
                    f"Equipo {idx+2}/{n}\n\nEscribe: *tipo - marca - modelo*",
                    parse_mode="Markdown",
                )
                return

            today = tctx.today()
            start_dt = datetime(
                today.year,
                today.month,
                today.day,
                8,
                30,
                0,
                tzinfo=tctx.tz,
            ).isoformat(timespec="seconds")

            next_due_dt = TimeContext.add_months_iso(start_dt, 12)

            def _save(conn):
                insert_maintenance_plan(
                    conn,
                    chat_id=chat_id,
                    client=str(tmp["client"]),
                    phone=str(tmp["phone"]),
                    ph_type=str(tmp.get("ph_type") or "Casa"),
                    ph_name=tmp.get("ph_name"),
                    address_text=str(tmp["address_text"]),
                    waze_url=tmp.get("waze_url"),
                    appliances_count=int(tmp.get("appliances_count", 1)),
                    appliances=list(tmp.get("appliances", [])),
                    photos=[],
                    start_dt_iso=start_dt,
                    next_due_dt_iso=next_due_dt,
                    created_at=tctx.now_iso(),
                )
                drafts_repo.upsert(
                    conn,
                    chat_id,
                    FLOW_WORK_COORDINATOR,
                    STEP_COORD_MENU,
                    _new_coord_draft(),
                    tctx.now_iso(),
                )

            await _draft_write(context, _save)

            await reply_text_tracked(
                update,
                context,
                "✅ *Mantenimiento programado*\n\n"
                f"👤 Cliente: *{tmp['client']}* (`{tmp['phone']}`)\n"
                f"🏠 Tipo: {tmp.get('ph_type')}{(' - ' + tmp.get('ph_name')) if tmp.get('ph_name') else ''}\n"
                f"🗺️ Dirección: {tmp.get('address_text')}\n"
                f"🚗 Waze: {tmp.get('waze_url') or '—'}\n\n"
                f"🧰 Equipos registrados: *{tmp.get('appliances_count')}*\n"
                f"📅 Fecha inicial: *{start_dt.replace('T', ' ')}*\n"
                f"🔔 Recordatorio anual: *{next_due_dt.replace('T', ' ')}*",
                parse_mode="Markdown",
            )
            await reply_text_tracked(update, context, _coord_menu_text(), parse_mode="Markdown")
            return

        await _draft_write(context, lambda conn: drafts_repo.delete(conn, chat_id))
        await _go_menu(update, context)
        return

    # -------------------------------------------------------------
    # FLOW: PEDIDOS ORDENADOS
    # -------------------------------------------------------------
    if draft.flow == FLOW_ORDER_REMINDER:
        data = draft.data
        tmp = data.setdefault("tmp", {})

        STEP_ORDER_WAZE_TEXT = "order_waze_text"
        STEP_ORDER_TOTAL_USD = "order_total_usd"
        STEP_ORDER_CONFIRM = "order_confirm"

        if draft.step == STEP_ORDER_CLIENT:
            if not text:
                await reply_text_tracked(update, context, "❌ Escribe un nombre válido.")
                return
            tmp.clear()
            tmp["client"] = text.strip()
            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_ORDER_PHONE, data, tctx.now_iso()),
            )
            await reply_text_tracked(update, context, "2️⃣ Escribe el *teléfono* del cliente:")
            return

        if draft.step == STEP_ORDER_PHONE:
            if not text:
                await reply_text_tracked(update, context, "❌ Escribe un teléfono válido.")
                return
            tmp["phone"] = text.strip()
            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_ORDER_WAZE_TEXT, data, tctx.now_iso()),
            )
            await reply_text_tracked(update, context, "3️⃣ Escribe la *dirección / edificio / calle*:")
            return

        if draft.step == STEP_ORDER_WAZE_TEXT:
            if not text:
                await reply_text_tracked(update, context, "❌ Dirección inválida.")
                return

            addr = text.strip()
            tmp["address_text"] = addr
            tmp["waze_url"] = _waze_from_text(addr)

            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_ORDER_DESC, data, tctx.now_iso()),
            )
            await reply_text_tracked(update, context, "4️⃣ Describe la *pieza / pedido*:")
            return

        if draft.step == STEP_ORDER_DESC:
            if not text:
                await reply_text_tracked(update, context, "❌ Escribe una descripción válida.")
                return

            tmp["part_desc"] = text.strip()
            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_ORDER_TOTAL_USD, data, tctx.now_iso()),
            )
            await reply_text_tracked(update, context, "5️⃣ Escribe el *TOTAL en USD* del pedido.")
            return

        if draft.step == STEP_ORDER_TOTAL_USD:
            raw = (text or "").strip().replace("$", "")
            try:
                total_usd = float(raw)
            except Exception:
                await reply_text_tracked(update, context, "❌ Total inválido. Ej: `85` o `85.50`.", parse_mode="Markdown")
                return

            if total_usd <= 0:
                await reply_text_tracked(update, context, "❌ El total debe ser mayor que 0.")
                return

            tmp["total_usd"] = total_usd

            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_ORDER_CONFIRM, data, tctx.now_iso()),
            )
            await reply_text_tracked(
                update,
                context,
                "✅ Confirma el pedido:\n\n"
                f"👤 Cliente: *{tmp['client']}* (`{tmp['phone']}`)\n"
                f"📍 Dirección: {tmp['address_text']}\n"
                f"🚗 Waze: {tmp.get('waze_url') or '—'}\n"
                f"🧩 Pieza: _{tmp['part_desc']}_\n"
                f"💵 Total USD: *${tmp['total_usd']:.2f}*\n\n"
                "1️⃣ Guardar\n"
                "2️⃣ Cancelar",
                parse_mode="Markdown",
                disable_web_page_preview=False,
            )
            return

        if draft.step == STEP_ORDER_CONFIRM:
            if choice == "2":
                await _go_coord_menu(update, context)
                return

            if choice != "1":
                await reply_text_tracked(update, context, "Responde 1️⃣ (Guardar) o 2️⃣ (Cancelar).")
                return

            ordered_at = tctx.now_iso()
            first_remind = TimeContext.add_days_iso(ordered_at, 7)
            next_remind = first_remind

            def _save(conn):
                insert_ordered_part(
                    conn,
                    chat_id=chat_id,
                    client=str(tmp["client"]),
                    phone=str(tmp["phone"]),
                    address_text=str(tmp["address_text"]),
                    part_desc=str(tmp["part_desc"]),
                    ordered_at_iso=ordered_at,
                    first_remind_dt_iso=first_remind,
                    next_remind_dt_iso=next_remind,
                    created_at=ordered_at,
                    waze_url=str(tmp.get("waze_url") or ""),
                    total_usd=float(tmp["total_usd"]),
                )
                drafts_repo.upsert(
                    conn,
                    chat_id,
                    FLOW_WORK_COORDINATOR,
                    STEP_COORD_MENU,
                    _new_coord_draft(),
                    tctx.now_iso(),
                )

            await _draft_write(context, _save)

            await reply_text_tracked(
                update,
                context,
                "✅ *Pedido registrado*\n\n"
                f"👤 Cliente: *{tmp['client']}* (`{tmp['phone']}`)\n"
                f"📍 Dirección: {tmp['address_text']}\n"
                f"🚗 Waze: {tmp.get('waze_url') or '—'}\n"
                f"🧩 Pedido: _{tmp['part_desc']}_\n"
                f"💵 Total USD: *${tmp['total_usd']:.2f}*\n\n"
                f"⏰ Primer recordatorio: *{first_remind.replace('T', ' ')}*",
                parse_mode="Markdown",
                disable_web_page_preview=False,
            )
            await reply_text_tracked(update, context, _coord_menu_text(), parse_mode="Markdown")
            return

        await _draft_write(context, lambda conn: drafts_repo.delete(conn, chat_id))
        await _go_menu(update, context)
        return

    # -------------------------------------------------------------
    # WIZARD RECIBO DE SERVICIO
    # -------------------------------------------------------------
    if draft.flow != FLOW_CREATE_SERVICE_INVOICE:
        await _draft_write(context, lambda conn: drafts_repo.delete(conn, chat_id))
        await _go_menu(update, context)
        return

    data = draft.data

    if draft.step == STEP_CLIENT_NAME:
        if not text:
            await reply_text_tracked(update, context, "❌ Escribe un nombre válido.")
            return

        data["client_name"] = text
        await _draft_write(
            context,
            lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_DATE_CHOICE, data, tctx.now_iso()),
        )

        await reply_text_tracked(
            update,
            context,
            "2️⃣ Fecha del servicio:\n"
            "1️⃣ Usar *fecha de hoy*\n"
            "2️⃣ Escribir fecha (YYYY-MM-DD)\n\n"
            "Responde 1️⃣ o 2️⃣.",
            parse_mode="Markdown",
        )
        return

    if draft.step == STEP_DATE_CHOICE:
        if choice == "1":
            data["service_date"] = tctx.today().isoformat()
            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_ITEM_DESC, data, tctx.now_iso()),
            )
            await reply_text_tracked(update, context, "3️⃣ Escribe la *descripción*:", parse_mode="Markdown")
            return

        if choice == "2":
            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_DATE_MANUAL, data, tctx.now_iso()),
            )
            await reply_text_tracked(update, context, "Escribe la fecha en formato YYYY-MM-DD:")
            return

        await reply_text_tracked(update, context, "Responde 1️⃣ o 2️⃣.")
        return

    if draft.step == STEP_DATE_MANUAL:
        if len(text) != 10 or text[4] != "-" or text[7] != "-":
            await reply_text_tracked(update, context, "❌ Formato inválido. Ejemplo: 2026-02-12")
            return

        data["service_date"] = text
        await _draft_write(
            context,
            lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_ITEM_DESC, data, tctx.now_iso()),
        )
        await reply_text_tracked(update, context, "3️⃣ Escribe la *descripción*:", parse_mode="Markdown")
        return

    if draft.step == STEP_ITEM_DESC:
        if not text:
            await reply_text_tracked(update, context, "❌ Escribe una descripción válida.")
            return

        data["current_item"] = {"description": text}
        await _draft_write(
            context,
            lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_ITEM_QTY, data, tctx.now_iso()),
        )
        await reply_text_tracked(update, context, "4️⃣ Cantidad (ej: 1):")
        return

    if draft.step == STEP_ITEM_QTY:
        try:
            qty = float(text)
        except Exception:
            await reply_text_tracked(update, context, "❌ Cantidad inválida. Ejemplo: 1")
            return

        if qty <= 0:
            await reply_text_tracked(update, context, "❌ La cantidad debe ser > 0.")
            return

        data["current_item"]["qty"] = qty
        await _draft_write(
            context,
            lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_ITEM_UNIT, data, tctx.now_iso()),
        )
        await reply_text_tracked(update, context, "5️⃣ Precio unitario (ej: 60):")
        return

    if draft.step == STEP_ITEM_UNIT:
        try:
            unit_price = float(text)
        except Exception:
            await reply_text_tracked(update, context, "❌ Precio inválido. Ejemplo: 60")
            return

        if unit_price < 0:
            await reply_text_tracked(update, context, "❌ El precio no puede ser negativo.")
            return

        qty = float(data["current_item"]["qty"])
        line_total = qty * unit_price

        item = {
            "description": data["current_item"]["description"],
            "qty": qty,
            "unit_price": unit_price,
            "line_total": line_total,
        }

        data["items"].append(item)
        data["current_item"] = {}

        subtotal = sum(float(i["line_total"]) for i in data["items"])

        await _draft_write(
            context,
            lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_ITEM_MORE, data, tctx.now_iso()),
        )

        await reply_text_tracked(
            update,
            context,
            f"✅ Concepto agregado. Subtotal: $ {subtotal:.2f}\n\n"
            "¿Agregar otro concepto?\n"
            "1️⃣ Sí\n"
            "2️⃣ No (finalizar y generar PDF)",
        )
        return

    if draft.step == STEP_ITEM_MORE:
        if choice == "1":
            await _draft_write(
                context,
                lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_ITEM_DESC, data, tctx.now_iso()),
            )
            await reply_text_tracked(update, context, "Escribe la *descripción*:", parse_mode="Markdown")
            return

        if choice == "2":
            if not data["items"]:
                await reply_text_tracked(update, context, "❌ No hay conceptos. Agrega al menos 1.")
                await _draft_write(
                    context,
                    lambda conn: drafts_repo.upsert(conn, chat_id, draft.flow, STEP_ITEM_DESC, data, tctx.now_iso()),
                )
                return

            total = sum(float(i["line_total"]) for i in data["items"])
            consecutivo = await _draft_write(context, lambda conn: next_consecutivo(conn))

            service_date_pdf = iso_to_ddmmyyyy(str(data["service_date"]))
            logo_uri = (project_root / "assets" / "logo_factura.png").resolve().as_uri()
            css_path = (project_root / "assets" / "factura.css").resolve()
            base_dir = (project_root / "assets").resolve()

            payload = ServiceInvoicePayload(
                consecutivo=consecutivo,
                vendor_name="Julio Vidal",
                vendor_phone="69483940",
                client_name=str(data["client_name"]),
                service_date=service_date_pdf,
                currency_label="$",
                items=data["items"],
                logo_path=logo_uri,
            )

            html, _ = build_service_invoice_html(payload)
            pdf_name = f"recibo_{consecutivo}.pdf"
            pdf_path = paths.invoices_dir / pdf_name

            render_pdf(
                html=html,
                output_path=pdf_path,
                base_dir=base_dir,
                css_path=css_path,
            )

            def _save(conn):
                insert_service_invoice(
                    conn,
                    chat_id=chat_id,
                    consecutivo=consecutivo,
                    client_name=str(data["client_name"]),
                    client_phone=None,
                    service_date=str(data["service_date"]),
                    currency="USD",
                    total=float(total),
                    pdf_path=str(pdf_path),
                    created_at=tctx.now_iso(),
                    items=data["items"],
                )
                drafts_repo.delete(conn, chat_id)

            await _draft_write(context, _save)

            lines = "\n".join(
                f"- {item['description']} x{item['qty']} = $ {item['line_total']:.2f}"
                for item in data["items"]
            )

            await reply_text_tracked(
                update,
                context,
                "🧾 Recibo generado ✅\n"
                f"No.: {consecutivo}\n"
                f"Cliente: {data['client_name']}\n"
                f"Fecha: {service_date_pdf}\n"
                f"{lines}\n"
                f"TOTAL: $ {total:.2f}",
            )

            with open(pdf_path, "rb") as file_obj:
                await reply_document_tracked(
                    update,
                    context,
                    document=file_obj,
                    filename=pdf_path.name,
                    caption="📎 Aquí tienes el Recibo en PDF listo para compartir.",
                )

            await reply_text_tracked(update, context, _menu_text(), parse_mode="Markdown")
            return

        await reply_text_tracked(update, context, "Responde 1️⃣ o 2️⃣.")
        return

    await _draft_write(context, lambda conn: drafts_repo.delete(conn, chat_id))
    await _go_menu(update, context)