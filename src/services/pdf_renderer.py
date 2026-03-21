"""
pdf_renderer.py
---------------
Renderizador PDF (WeasyPrint) robusto y verificable.

Garantías:
- Si css_path no existe o está vacío => ERROR (no continúa silenciosamente).
- Inyecta el CSS inline en <head> (evita problemas de rutas).
- base_url siempre es URI (file://) para soportar rutas con espacios.

Debug:
- Escribe un HTML debug junto al PDF para inspección rápida.
- Puede inyectar un "marker" visual SOLO en debug para confirmar que el CSS se aplica.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from weasyprint import HTML

from src.core.errors import PDFRenderError


def _inject_css_inline(html: str, css_text: str) -> str:
    """
    Inserta el CSS inline dentro de <head>. Si no existe <head>, lo crea.
    """
    style_tag = f"<style>\n{css_text}\n</style>"

    if "<head>" in html:
        return html.replace("<head>", "<head>\n" + style_tag, 1)

    # Si por alguna razón no hay <head>, lo creamos
    return f"<!doctype html><html><head>{style_tag}</head><body>{html}</body></html>"


def _build_debug_marker_css(marker_selector: str = ".report") -> str:
    """
    CSS marcador para confirmar visualmente que el CSS está aplicándose.
    Se usa SOLO en debug.
    """
    return f"""
    {marker_selector} {{
      outline: 3px solid #ff0000 !important;
      outline-offset: 2px !important;
    }}
    """


def render_pdf(
    *,
    html: str,
    output_path: Path,
    base_dir: Path,
    css_path: Optional[Path] = None,
    debug_html: bool = True,
    debug_css_marker: bool = False,
    marker_selector: str = ".report",
) -> None:
    """
    Renderiza HTML a PDF con WeasyPrint.

    Parameters
    ----------
    html:
        HTML completo.
    output_path:
        Ruta destino del PDF.
    base_dir:
        Carpeta base para resolver recursos relativos (assets/).
        Se convertirá a URI (file://) para soportar rutas con espacios.
    css_path:
        Ruta al CSS a inyectar inline (OBLIGATORIO en producción).
    debug_html:
        Si True, guarda un .debug.html junto al PDF para inspección.
    debug_css_marker:
        Si True, inyecta un marcador visual (outline rojo) para confirmar CSS.
        Útil cuando sospechas que el CSS no está aplicando.
    marker_selector:
        Selector CSS que recibirá el outline del marcador (por defecto .report).
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not css_path:
            raise PDFRenderError("css_path es obligatorio y no fue provisto.")

        css_path = css_path.resolve()
        if not css_path.exists():
            raise PDFRenderError(f"CSS no existe: {css_path}")

        css_text = css_path.read_text(encoding="utf-8", errors="ignore").strip()
        if not css_text:
            raise PDFRenderError(f"CSS está vacío: {css_path}")

        # Marker SOLO en debug cuando se solicita explícitamente
        if debug_css_marker:
            css_text = _build_debug_marker_css(marker_selector=marker_selector) + "\n" + css_text

        # Inyectar CSS inline
        html = _inject_css_inline(html, css_text)

        # Guardar HTML debug
        if debug_html:
            debug_path = output_path.with_suffix(".debug.html")
            debug_path.write_text(html, encoding="utf-8")

        # base_url como URI (paths con espacios)
        base_url = base_dir.resolve().as_uri()

        # Render PDF
        HTML(string=html, base_url=base_url).write_pdf(target=str(output_path))

    except Exception as e:
        raise PDFRenderError(f"Error renderizando PDF: {e}") from e