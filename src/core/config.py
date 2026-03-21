"""
config.py
---------
Carga de configuración central desde variables de entorno (opcional .env).

Diseño:
- Pydantic Settings para validación y defaults.
- Las rutas se construyen desde el root del proyecto.
"""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.paths import ProjectPaths, detect_project_root


class Settings(BaseSettings):
    """
    Configuración global del proyecto.

    Nota:
    - .env no debe versionarse (usa .env.example)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # streamlit_app.py necesita esta URL para comunicarse con el backend (httpx)
    TELEFINANCE_DASHBOARD_URL: str = "http://localhost:8501"

    # --- App ---
    timezone: str = Field(default="America/Panama", alias="TIMEZONE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # --- DB ---
    db_path: str = Field(default="data/telefinance.db", alias="DB_PATH")

    # --- Assets/Output (se resuelven con ProjectPaths, pero se dejan configurables) ---
    assets_dir: str = Field(default="assets", alias="ASSETS_DIR")
    output_dir: str = Field(default="output/invoices", alias="OUTPUT_DIR")

    # --- Integraciones ---
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def project_paths(self, project_root: Path) -> ProjectPaths:
        """
        Construye rutas del proyecto desde el root.
        """
        paths = ProjectPaths.from_root(project_root)
        paths.ensure_dirs()
        return paths

    def resolved_db_path(self, project_root: Path) -> Path:
        """
        Devuelve DB_PATH como Path absoluto/normalizado.
        """
        return (project_root / self.db_path).resolve()

    def resolved_assets_dir(self, project_root: Path) -> Path:
        return (project_root / self.assets_dir).resolve()

    def resolved_output_dir(self, project_root: Path) -> Path:
        return (project_root / self.output_dir).resolve()

    def project_root(self) -> Path:
        """
        Root del proyecto detectado de forma robusta.
        Evita depender del CWD (ej: ejecutar desde ~/Desktop).
        """
        return detect_project_root()

    def resolved_db_path_auto(self) -> Path:
        """
        DB path resuelto usando el root detectado automáticamente.
        """
        return (self.project_root() / self.db_path).resolve()

    def project_paths_auto(self) -> ProjectPaths:
        """
        ProjectPaths usando el root detectado automáticamente.
        """
        paths = ProjectPaths.from_root(self.project_root())
        paths.ensure_dirs()
        return paths