"""
bot.py
------
Arranque principal del bot de Telegram para Telefinance.

Responsabilidades
-----------------
- Cargar configuración del proyecto
- Resolver rutas críticas de forma determinística
- Inicializar SQLite y aplicar migraciones
- Compartir objetos globales en `bot_data`
- Registrar handlers de comandos, texto, fotos y recordatorios
- Proveer un error handler global

Diseño
------
- La IA NO se usa aquí directamente.
- El OCR de proveedor se activa únicamente en el handler de foto correspondiente.
- Las fotos de mantenimiento se enrutan al wizard si el draft activo así lo indica.
- El bot comparte una única ruta de DB y un lock de escritura para evitar conflictos.

Notas operativas
----------------
- `project_root` se valida internamente y no depende del caller externo.
- `JobQueue` se usa para recordatorios periódicos.
- El sistema está preparado para convivir con Streamlit y SQLite en WAL.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from src.core.config import Settings
from src.core.logger import setup_logger
from src.core.utils_time import TimeContext
from src.db.connection import readonly_session, session
from src.db.migrations import apply_schema


def _resolve_project_root(proposed: Path | None = None) -> Path:
    """
    Resuelve y valida la raíz real del proyecto.

    Prioridad:
    1. `proposed`, si fue suministrado y es válido
    2. Derivación determinística desde este archivo

    Returns
    -------
    Path
        Ruta válida a la raíz del proyecto.

    Raises
    ------
    RuntimeError
        Si no se puede validar una raíz que contenga los assets requeridos.
    """
    candidates: list[Path] = []

    if proposed is not None:
        candidates.append(Path(proposed).expanduser().resolve())

    # bot.py está en: telefinance/src/telegram_bot/bot.py
    # parents[2] = telefinance/
    candidates.append(Path(__file__).resolve().parents[2])

    for root in candidates:
        css = root / "assets" / "factura.css"
        logo = root / "assets" / "logo_factura.png"
        if css.exists() and logo.exists():
            return root

    diag = "\n".join(f"- {candidate}" for candidate in candidates)
    raise RuntimeError(
        "PROJECT_ROOT inválido. No se encontró assets/factura.css y assets/logo_factura.png.\n"
        f"Candidatos probados:\n{diag}"
    )


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Error handler global del bot.

    Comportamiento:
    - registra la excepción completa en logs
    - responde de forma amigable al usuario si existe mensaje efectivo
    """
    logger.exception("Unhandled exception in Telegram bot: {}", context.error)

    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Ocurrió un error interno y ya quedó registrado en logs.\n"
            "Puedes intentar de nuevo o usar /cancelar para reiniciar."
        )


def build_app(project_root: Path | None = None) -> Application:
    """
    Construye y devuelve la aplicación principal del bot.

    Parameters
    ----------
    project_root:
        Ruta raíz opcional del proyecto. Si viene mal o no viene,
        se resuelve automáticamente desde este módulo.

    Returns
    -------
    Application
        Instancia lista para correr con python-telegram-bot.
    """
    # -------------------------------------------------------------
    # Resolver paths y configuración
    # -------------------------------------------------------------
    resolved_project_root = _resolve_project_root(project_root)
    assets_dir = (resolved_project_root / "assets").resolve()

    settings = Settings()
    paths = settings.project_paths(resolved_project_root)
    setup_logger(paths.logs_dir, level=settings.log_level)

    db_path = settings.resolved_db_path(resolved_project_root)

    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN no está configurado en .env")

    tctx = TimeContext(settings.tz())

    inbox_dir = (resolved_project_root / "data" / "inbox").resolve()
    inbox_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------
    # Asegurar schema de base de datos
    # -------------------------------------------------------------
    with session(db_path) as conn:
        apply_schema(conn)

    # -------------------------------------------------------------
    # Logging de arranque
    # -------------------------------------------------------------
    logger.info("PROJECT_ROOT={}", resolved_project_root)
    logger.info("ASSETS_DIR={}", assets_dir)
    logger.info("CSS={}", assets_dir / "factura.css")
    logger.info("LOGO={}", assets_dir / "logo_factura.png")
    logger.info("DB_PATH={}", db_path)
    logger.info("INVOICES_DIR={}", getattr(paths, "invoices_dir", None))
    logger.info("INBOX_DIR={}", inbox_dir)

    # -------------------------------------------------------------
    # Crear aplicación
    # -------------------------------------------------------------
    app = Application.builder().token(settings.telegram_bot_token).build()

    # -------------------------------------------------------------
    # Compartir estado global
    # -------------------------------------------------------------
    app.bot_data["settings"] = settings
    app.bot_data["paths"] = paths
    app.bot_data["project_root"] = resolved_project_root
    app.bot_data["assets_dir"] = assets_dir
    app.bot_data["db_path"] = db_path
    app.bot_data["tctx"] = tctx
    app.bot_data["inbox_dir"] = inbox_dir

    from src.db.db_lock import DBWriteLock

    app.bot_data["db_write_lock"] = DBWriteLock()

    # -------------------------------------------------------------
    # Imports de handlers
    # -------------------------------------------------------------
    from src.db.repositories import drafts_repo
    from src.telegram_bot.handlers.reminders import reminders_tick
    from src.telegram_bot.handlers.service_wizard import (
        crear_factura_cmd,
        wizard_photo_router,
        wizard_text_router,
    )
    from src.telegram_bot.handlers.start import cancelar_cmd, estado_cmd, start_cmd
    from src.telegram_bot.handlers.vendor_invoice_photo import vendor_invoice_photo_handler
    from src.telegram_bot.state.wizard_state import FLOW_SCHEDULE_MAINTENANCE, STEP_MAINT_PHOTOS

    # -------------------------------------------------------------
    # Router inteligente para fotos
    # -------------------------------------------------------------
    async def photo_dispatch_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Router único para mensajes con foto.

        Reglas:
        - Si el draft actual corresponde al flujo de mantenimiento y está
          esperando fotos, se enruta a `wizard_photo_router`.
        - En cualquier otro caso, la foto se interpreta como factura
          de proveedor y se procesa con OCR.
        """
        if not update.message or not update.message.photo:
            return

        chat_id = update.effective_chat.id
        local_db_path = context.bot_data["db_path"]

        with readonly_session(local_db_path) as conn:
            draft = drafts_repo.get(conn, chat_id)

        if draft and draft.flow == FLOW_SCHEDULE_MAINTENANCE and draft.step == STEP_MAINT_PHOTOS:
            await wizard_photo_router(update, context)
            return

        await vendor_invoice_photo_handler(update, context)

    # -------------------------------------------------------------
    # Registro de handlers
    # -------------------------------------------------------------
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("cancelar", cancelar_cmd))
    app.add_handler(CommandHandler("estado", estado_cmd))
    app.add_handler(CommandHandler("crear_factura", crear_factura_cmd))

    app.add_handler(MessageHandler(filters.PHOTO, photo_dispatch_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_text_router))

    # -------------------------------------------------------------
    # JobQueue: recordatorios periódicos
    # -------------------------------------------------------------
    if app.job_queue is None:
        raise RuntimeError("JobQueue no está disponible en la aplicación de Telegram.")

    app.job_queue.run_repeating(reminders_tick, interval=60, first=10)

    # -------------------------------------------------------------
    # Error handler global
    # -------------------------------------------------------------
    app.add_error_handler(_on_error)

    return app