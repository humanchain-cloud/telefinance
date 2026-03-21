"""
init_db.py
----------
CLI para inicializar la base de datos SQLite de Telefinance.

Uso:
    python -m src.cli.init_db
"""

from __future__ import annotations

from loguru import logger

from src.core.config import Settings
from src.core.logger import setup_logger
from src.core.paths import detect_project_root
from src.db.connection import session
from src.db.migrations import apply_schema


def main() -> None:
    """
    Inicializa la base de datos y aplica el schema/migraciones.
    """
    project_root = detect_project_root()
    settings = Settings()

    paths = settings.project_paths(project_root)
    setup_logger(paths.logs_dir, level=settings.log_level)

    db_path = settings.resolved_db_path(project_root)

    logger.info("Inicializando DB en: {}", db_path)

    with session(db_path) as conn:
        apply_schema(conn)

    logger.success("DB inicializada y schema aplicado correctamente.")


if __name__ == "__main__":
    main()