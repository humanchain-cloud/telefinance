"""
errors.py
---------
Excepciones de dominio y de infraestructura.

Objetivo:
- Errores explícitos y fáciles de rastrear.
- Diferenciar fallos de validación / DB / OCR / PDF.
"""


class TelefinanceError(Exception):
    """Base de excepciones del proyecto."""


class ConfigError(TelefinanceError):
    """Error de configuración (variables de entorno faltantes, rutas, etc.)."""


class DatabaseError(TelefinanceError):
    """Error relacionado a SQLite / queries / integridad."""


class OCRExtractionError(TelefinanceError):
    """Error al extraer datos desde imagen (OpenAI OCR/vision)."""


class PDFRenderError(TelefinanceError):
    """Error al renderizar PDF."""
