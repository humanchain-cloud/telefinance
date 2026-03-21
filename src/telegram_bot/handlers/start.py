"""
start.py
--------
Comandos base del bot.

- /start: muestra el menú principal (fuente única: service_wizard._menu_text)
- /cancelar: reinicia (borra draft y vuelve al menú)
- /estado: muestra flow/step actuales (debug)

Nota de arquitectura:
- El menú y su router viven en service_wizard.py.
- start.py solo “pinta” el menú y resetea el draft.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from src.core.utils_time import TimeContext
from src.db.connection import session
from src.db.repositories import drafts_repo
from src.telegram_bot.state.wizard_state import FLOW_MAIN_MENU, STEP_MENU


async def _set_main_menu_draft(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """
    Escribe (bajo lock) el draft de menú principal.
    """
    db_path: str = context.bot_data["db_path"]
    tctx: TimeContext = context.bot_data["tctx"]
    lock = context.bot_data["db_write_lock"]

    async def _write():
        with session(db_path, immediate=True) as conn:
            drafts_repo.upsert(conn, chat_id, FLOW_MAIN_MENU, STEP_MENU, {"screen": "main"}, tctx.now_iso())

    await lock.run(_write)


async def _delete_draft(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """
    Borra draft bajo lock.
    """
    db_path: str = context.bot_data["db_path"]
    lock = context.bot_data["db_write_lock"]

    async def _write():
        with session(db_path, immediate=True) as conn:
            drafts_repo.delete(conn, chat_id)

    await lock.run(_write)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /start -> pinta menú principal (el nuevo, con íconos)
    """
    if not update.effective_chat:
        return

    chat_id = update.effective_chat.id

    # Draft de menú
    await _set_main_menu_draft(context, chat_id)

    # Menú: fuente única desde service_wizard (evita duplicidad)
    from src.telegram_bot.handlers.service_wizard import _menu_text

    await update.message.reply_text(_menu_text(), parse_mode="Markdown")


async def cancelar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /cancelar -> resetea draft y vuelve al menú principal.
    """
    if not update.effective_chat:
        return

    chat_id = update.effective_chat.id

    await _delete_draft(context, chat_id)
    await _set_main_menu_draft(context, chat_id)

    from src.telegram_bot.handlers.service_wizard import _menu_text

    await update.message.reply_text("🧹 Listo. Reiniciado.\n\n" + _menu_text(), parse_mode="Markdown")


async def estado_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /estado -> debug: muestra flow y step actuales.
    """
    if not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    db_path: str = context.bot_data["db_path"]

    with session(db_path) as conn:
        d = drafts_repo.get(conn, chat_id)

    if not d:
        await update.message.reply_text("✅ No hay flujo activo. Escribe /start para ver el menú.")
        return

    await update.message.reply_text(f"📌 Flujo activo:\n• flow: {d.flow}\n• step: {d.step}")

