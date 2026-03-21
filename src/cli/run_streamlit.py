"""
run_streamlit.py
----------------
CLI oficial para ejecutar el Dashboard Streamlit de Telefinance.

Objetivo:
- Ejecutar `streamlit_app/app.py` de forma reproducible
- Garantizar CWD correcto
- Garantizar imports `src.*`
- Evitar problemas con `st.set_page_config()`

Diseño:
- NO usar `streamlit.web.cli` embebido en el mismo proceso
- Usar `os.execvpe()` para reemplazar el proceso actual por Streamlit
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from loguru import logger

from src.core.config import Settings
from src.core.logger import setup_logger
from src.core.paths import detect_project_root


def main() -> None:
    """
    Arranca el dashboard Streamlit de Telefinance.
    """
    project_root = detect_project_root()
    settings = Settings()

    paths = settings.project_paths(project_root)
    setup_logger(paths.logs_dir, level=settings.log_level)

    app_path = project_root / "streamlit_app" / "app.py"

    if not app_path.exists():
        raise SystemExit(f"No existe el dashboard: {app_path}")

    logger.info("Iniciando Streamlit dashboard...")
    logger.info("PROJECT_ROOT={}", project_root)
    logger.info("APP_PATH={}", app_path)

    # CWD estable para rutas relativas, .env, assets, etc.
    os.chdir(project_root)

    # Asegurar imports `src.*`
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )

    argv = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--logger.level=info",
    ]

    # Reemplaza el proceso actual por Streamlit
    os.execvpe(sys.executable, argv, env)


if __name__ == "__main__":
    main()