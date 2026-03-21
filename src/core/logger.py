"""
logger.py
---------
Logging profesional y consistente para todo el proyecto.

Usamos loguru para:
- logs legibles en consola
- rotación a archivo
- nivel configurable desde .env
"""

from __future__ import annotations

import sys
from pathlib import Path
from loguru import logger


def setup_logger(logs_dir: Path, level: str = "INFO") -> None:
    """
    Configura loguru (stdout + archivo con rotación).

    Parameters
    ----------
    logs_dir:
        Directorio donde se guardan logs.
    level:
        Nivel de log (INFO, DEBUG, WARNING, ERROR).
    """
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()  # limpia handlers default

    # Consola
    logger.add(
        sys.stdout,
        level=level.upper(),
        enqueue=True,
        backtrace=False,
        diagnose=False,
        colorize=True,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - {message}",
    )

    # Archivo rotativo
    logger.add(
        str(logs_dir / "telefinance.log"),
        level=level.upper(),
        rotation="10 MB",
        retention="14 days",
        compression="zip",
        enqueue=True,
        backtrace=False,
        diagnose=False,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
    )
