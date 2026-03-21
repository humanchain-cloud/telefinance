"""
ocr_openai.py
-------------
Extracción OCR con OpenAI Vision para Telefinance.

Responsabilidad
---------------
- Recibir una imagen de factura de proveedor
- Enviarla a OpenAI Vision
- Obtener una respuesta estructurada en JSON
- Normalizar y devolver un diccionario consistente para el resto del sistema

Reglas
------
- La IA SOLO se activa cuando llega una imagen.
- Este módulo NO escribe en base de datos.
- Este módulo NO genera analíticas.
- Este módulo devuelve datos limpios y predecibles.

Compatibilidad
--------------
- Soporta `client.responses` cuando está disponible.
- Mantiene compatibilidad con `client.chat.completions`.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI

from src.core.config import Settings
from src.core.errors import OCRExtractionError


# ---------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------
def _img_to_data_uri(image_path: Path) -> str:
    """
    Convierte una imagen local a data URI base64.

    Parameters
    ----------
    image_path:
        Ruta absoluta a la imagen.

    Returns
    -------
    str
        Data URI lista para enviar a OpenAI Vision.
    """
    suffix = image_path.suffix.lower().lstrip(".")
    mime = "image/jpeg" if suffix in ("jpg", "jpeg") else "image/png"
    b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _extract_json_object(text: str) -> str:
    """
    Extrae el primer objeto JSON válido dentro de una respuesta de texto.

    Acepta respuestas que vengan:
    - como JSON puro
    - dentro de fences markdown
    - con texto extra accidental alrededor

    Raises
    ------
    ValueError
        Si no se encuentra un objeto JSON.
    """
    raw = (text or "").strip()

    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)

    if raw.startswith("{") and raw.endswith("}"):
        return raw

    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if match:
        return match.group(0).strip()

    raise ValueError("No se encontró objeto JSON en la respuesta del modelo.")


def _normalize_text(value: Any) -> Optional[str]:
    """
    Normaliza texto nullable.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: Any, default: float = 0.0) -> float:
    """
    Convierte un valor a float de forma segura.
    """
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _normalize_date_iso(date_str: Optional[str]) -> Optional[str]:
    """
    Normaliza fechas comunes a formato YYYY-MM-DD cuando es posible.
    """
    if not date_str:
        return None

    s = str(date_str).strip()

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s

    # dd/mm/yyyy o dd-mm-yyyy
    match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", s)
    if match:
        dd, mm, yyyy = match.group(1), match.group(2), match.group(3)
        return f"{yyyy}-{int(mm):02d}-{int(dd):02d}"

    # yyyy/mm/dd o yyyy-mm-dd
    match = re.fullmatch(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", s)
    if match:
        yyyy, mm, dd = match.group(1), match.group(2), match.group(3)
        return f"{yyyy}-{int(mm):02d}-{int(dd):02d}"

    return s


def _normalize_currency(value: Any) -> str:
    """
    Normaliza el código de moneda.

    Convención actual:
    - default: PAB
    - si viene vacío o inválido: PAB
    - se devuelve en uppercase
    """
    text = _normalize_text(value)
    if not text:
        return "PAB"

    code = text.upper()

    # Mantenerlo simple por ahora.
    if code in {"PAB", "USD", "EUR"}:
        return code

    return code


def _normalize_items(items: Any) -> List[Dict[str, Any]]:
    """
    Normaliza la lista de ítems del OCR.

    Reglas:
    - description nunca vacía
    - qty mínimo 1 si viene inválido o <= 0
    - unit_price nunca negativo
    - line_total nunca negativo
    """
    if not isinstance(items, list):
        return []

    normalized: List[Dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        description = _normalize_text(item.get("description")) or "Item"

        qty = _to_float(item.get("qty", 1), 1.0)
        if qty <= 0:
            qty = 1.0

        unit_price = _to_float(item.get("unit_price", 0), 0.0)
        if unit_price < 0:
            unit_price = 0.0

        raw_line_total = item.get("line_total")
        if raw_line_total in (None, ""):
            line_total = qty * unit_price
        else:
            line_total = _to_float(raw_line_total, qty * unit_price)

        if line_total < 0:
            line_total = 0.0

        normalized.append(
            {
                "description": description,
                "qty": qty,
                "unit_price": unit_price,
                "line_total": line_total,
            }
        )

    return normalized


def _build_prompt() -> str:
    """
    Construye el prompt de extracción estructurada para el modelo.
    """
    return (
        "Eres un sistema OCR especializado en facturas de proveedor.\n"
        "Debes leer la imagen y devolver SOLO un objeto JSON válido.\n"
        "No escribas markdown. No expliques nada. No agregues texto fuera del JSON.\n"
        "No inventes datos: si un valor no aparece claramente, usa null.\n"
        "Si no puedes detectar items, devuelve items = [].\n"
        "El campo total debe ser numérico.\n"
        "El campo raw_text debe contener el texto visible más relevante de la factura.\n\n"
        "Formato JSON exacto esperado:\n"
        "{"
        '"vendor_name": null,'
        '"vendor_id": null,'
        '"invoice_number": null,'
        '"invoice_date": null,'
        '"currency": "PAB",'
        '"total": 0,'
        '"items": [{"description": "", "qty": 1, "unit_price": 0, "line_total": 0}],'
        '"raw_text": ""'
        "}"
    )


def _call_openai_vision(client: OpenAI, model: str, prompt: str, data_uri: str) -> str:
    """
    Ejecuta la llamada a OpenAI Vision y devuelve texto crudo.

    Usa `client.responses` si está disponible; de lo contrario,
    usa `client.chat.completions`.
    """
    if hasattr(client, "responses"):
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": data_uri},
                    ],
                }
            ],
        )
        return (getattr(response, "output_text", "") or "").strip()

    response = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ],
    )
    return (response.choices[0].message.content or "").strip()


# ---------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------
def extract_vendor_invoice_from_image(
    image_path: Path,
    *,
    model: str = "gpt-4o-mini",
) -> Dict[str, Any]:
    """
    Extrae información estructurada de una factura de proveedor.

    Parameters
    ----------
    image_path:
        Ruta a la imagen local.
    model:
        Modelo por defecto si no se especifica uno en Settings.

    Returns
    -------
    dict
        Estructura normalizada con:
        - vendor_name
        - vendor_id
        - invoice_number
        - invoice_date
        - currency
        - total
        - items
        - raw_text

    Raises
    ------
    OCRExtractionError
        Si falla la lectura de imagen, la llamada al modelo o el parseo.
    """
    try:
        path = Path(image_path).expanduser().resolve()
        if not path.exists():
            raise OCRExtractionError(f"Imagen no existe: {path}")

        settings = Settings()
        if not settings.openai_api_key:
            raise OCRExtractionError("OPENAI_API_KEY no está configurado en .env")

        client = OpenAI(api_key=settings.openai_api_key)
        selected_model = settings.openai_model or model

        data_uri = _img_to_data_uri(path)
        prompt = _build_prompt()

        output_text = _call_openai_vision(
            client=client,
            model=selected_model,
            prompt=prompt,
            data_uri=data_uri,
        )

        json_str = _extract_json_object(output_text)
        data = json.loads(json_str)

        vendor_name = _normalize_text(data.get("vendor_name"))
        vendor_id = _normalize_text(data.get("vendor_id"))
        invoice_number = _normalize_text(data.get("invoice_number"))
        invoice_date = _normalize_date_iso(_normalize_text(data.get("invoice_date")))
        currency = _normalize_currency(data.get("currency"))
        total = _to_float(data.get("total", 0), 0.0)
        if total < 0:
            total = 0.0

        items = _normalize_items(data.get("items"))
        raw_text = _normalize_text(data.get("raw_text")) or ""

        return {
            "vendor_name": vendor_name,
            "vendor_id": vendor_id,
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "currency": currency,
            "total": total,
            "items": items,
            "raw_text": raw_text,
        }

    except OCRExtractionError:
        raise
    except Exception as exc:
        raise OCRExtractionError(f"OCR IA falló: {exc}") from exc