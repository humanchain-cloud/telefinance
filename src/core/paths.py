"""
paths.py
--------
Centraliza rutas del proyecto (telefinance) de forma consistente.

Objetivo:
- Evitar strings hardcodeadas de rutas en todo el sistema.
- Permitir que config y servicios obtengan rutas normalizadas.

Notas de diseño:
- `ProjectPaths` es una estructura inmutable con las rutas principales.
- `detect_project_root()` resuelve el root del repo de forma robusta
  (no depende del CWD).
- `get_project_paths()` expone un singleton de rutas ya normalizadas y
  con carpetas creadas.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    """
    Rutas base del proyecto.

    Attributes
    ----------
    root:
        Directorio raíz del proyecto.
    assets_dir:
        Directorio de assets (logo, css, etc.).
    data_dir:
        Directorio de datos (DB, exports, samples).
    logs_dir:
        Directorio de logs.
    output_dir:
        Directorio de salida general.
    invoices_dir:
        PDFs generados de facturas.
    reports_dir:
        Reportes generados (PDF/CSV/Excel, etc.).
    """

    root: Path
    assets_dir: Path
    data_dir: Path
    logs_dir: Path
    output_dir: Path
    invoices_dir: Path
    reports_dir: Path

    @staticmethod
    def from_root(root: Path) -> "ProjectPaths":
        """
        Construye ProjectPaths desde un root dado.
        """
        root = root.resolve()
        assets_dir = root / "assets"
        data_dir = root / "data"
        logs_dir = root / "logs"
        output_dir = root / "output"
        invoices_dir = output_dir / "invoices"
        reports_dir = output_dir / "reports"

        return ProjectPaths(
            root=root,
            assets_dir=assets_dir,
            data_dir=data_dir,
            logs_dir=logs_dir,
            output_dir=output_dir,
            invoices_dir=invoices_dir,
            reports_dir=reports_dir,
        )

    def ensure_dirs(self) -> None:
        """
        Crea directorios requeridos si no existen.
        """
        for p in (
            self.assets_dir,
            self.data_dir,
            self.logs_dir,
            self.output_dir,
            self.invoices_dir,
            self.reports_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------
# Root detection (robusto)
# ---------------------------------------------------------------------
def detect_project_root(start: Path | None = None) -> Path:
    """
    Detecta el directorio raíz del proyecto.

    Estrategia:
    - Subir desde `start` (o desde la ubicación de este archivo) buscando un folder que contenga:
        - src/
        - assets/
        - data/
    - Si no se encuentra, fallback al patrón estándar asumido por el repo:
      telefinance/src/core/paths.py  -> parents[2] == telefinance

    Esto evita bugs cuando el comando se ejecuta desde otro CWD
    (ej: ~/Desktop en lugar de ~/Desktop/telefinance).
    """
    if start is None:
        start = Path(__file__).resolve()

    cur = start if start.is_dir() else start.parent

    for parent in (cur, *cur.parents):
        if (parent / "src").is_dir() and (parent / "assets").is_dir() and (parent / "data").is_dir():
            return parent.resolve()

    # Fallback: paths.py (core) -> src -> telefinance
    return Path(__file__).resolve().parents[2].resolve()


# Singleton interno
_PROJECT_PATHS: ProjectPaths | None = None


def get_project_paths() -> ProjectPaths:
    """
    Devuelve ProjectPaths singleton con root detectado y carpetas aseguradas.
    """
    global _PROJECT_PATHS
    if _PROJECT_PATHS is None:
        root = detect_project_root()
        _PROJECT_PATHS = ProjectPaths.from_root(root)
        _PROJECT_PATHS.ensure_dirs()
    return _PROJECT_PATHS