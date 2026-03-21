"""
run_bot.py
----------
CLI para ejecutar el bot de Telegram.

Uso:
    python -m src.cli.run_bot
"""

from __future__ import annotations

from loguru import logger

from src.core.config import Settings
from src.core.logger import setup_logger
from src.core.paths import detect_project_root
from src.telegram_bot.bot import build_app


def main() -> None:
    """
    Arranca el bot de Telegram en modo polling.
    """

    project_root = detect_project_root()
    settings = Settings()

    paths = settings.project_paths(project_root)
    setup_logger(paths.logs_dir, level=settings.log_level)

    logger.info("Iniciando Telegram bot...")

    app = build_app(project_root)

    logger.success("Bot iniciado. Esperando mensajes...")

    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()