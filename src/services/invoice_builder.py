"""
invoice_builder.py
------------------
Constructor oficial de HTML para recibos Telefinance.

Objetivo (Feb 2026):
- Replicar EXACTAMENTE la presentación corporativa tipo "tarjeta" (como el screenshot).
- WeasyPrint-friendly: HTML simple, sin dependencias, sin JS.
- Compatible con factura.css (blue card layout).

Notas:
- `logo_path` debe venir como URI absoluta (file:///...) para soportar rutas con espacios.
- `items` es una lista de dicts con: description, qty, unit_price, line_total.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple


# ---------------------------------------------------------------------
# Dataclass de entrada
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class ServiceInvoicePayload:
    consecutivo: int
    vendor_name: str
    vendor_phone: Optional[str]
    client_name: str
    service_date: str
    currency_label: str
    items: List[Dict[str, Any]]
    logo_path: Optional[str]


# ---------------------------------------------------------------------
# Util: escape HTML mínimo (evita romper el PDF con &, <, >, ")
# ---------------------------------------------------------------------
def _escape_html(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


# ---------------------------------------------------------------------
# Util formateo dinero
# ---------------------------------------------------------------------
def _money(amount: float, currency: str) -> str:
    return f"{currency}{float(amount):.2f}"


# ---------------------------------------------------------------------
# Builder principal
# ---------------------------------------------------------------------
def build_service_invoice_html(payload: ServiceInvoicePayload) -> Tuple[str, float]:
    """
    Retorna (html, subtotal).

    El HTML está diseñado para funcionar con factura.css estilo "Recibo" corporativo:
    - Header con logo (izq) + Recibo N° (der)
    - Línea azul
    - 2 cajas grises: Vendedor/Cliente
    - Tabla con header azul + zebra rows
    - Barra azul final con Total
    """
    rows_html: list[str] = []
    subtotal = 0.0

    for it in payload.items:
        desc = _escape_html(str(it.get("description", "")).strip())
        qty = float(it.get("qty", 1))
        unit_price = float(it.get("unit_price", 0))
        line_total = float(it.get("line_total", qty * unit_price))

        subtotal += line_total

        rows_html.append(
            f"""
            <tr>
              <td class="t-desc">{desc}</td>
              <td class="t-center">{qty:g}</td>
              <td class="t-right">{_money(unit_price, payload.currency_label)}</td>
              <td class="t-right">{_money(line_total, payload.currency_label)}</td>
            </tr>
            """.strip()
        )

    if rows_html:
        productos_html = "\n".join(rows_html)
    else:
        productos_html = """
        <tr>
          <td colspan="4" style="text-align:center; padding:16px; opacity:0.7;">
            Sin ítems
          </td>
        </tr>
        """.strip()

    # Logo opcional
    logo_html = ""
    if payload.logo_path:
        logo_html = f'<img class="logo" src="{_escape_html(payload.logo_path)}" alt="Logo">'

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Recibo</title>
</head>
<body>
  <div class="page">
    <div class="receipt">

      <div class="header">
        <div>{logo_html}</div>
        <div class="title">Recibo N°{payload.consecutivo}</div>
      </div>

      <div class="hr"></div>

      <div class="info-row">
        <div class="info-box">
          <div class="info-line"><b>Vendedor:</b> {_escape_html(payload.vendor_name)}</div>
          {"<div class='info-line'><b>Teléfono:</b> " + _escape_html(payload.vendor_phone) + "</div>" if payload.vendor_phone else ""}
        </div>

        <div class="info-box">
          <div class="info-line"><b>Cliente:</b> {_escape_html(payload.client_name)}</div>
          <div class="info-line"><b>Fecha:</b> {_escape_html(payload.service_date)}</div>
        </div>
      </div>

      <table class="table">
        <thead>
          <tr>
            <th class="t-desc">Descripción</th>
            <th class="t-center">Cantidad</th>
            <th class="t-center">Precio<br>Unitario</th>
            <th class="t-center">Total</th>
          </tr>
        </thead>

        <tbody>
          {productos_html}
        </tbody>
      </table>

      <div class="total-bar">
        <div class="total-label">Total:</div>
        <div class="total-value">{_money(subtotal, payload.currency_label)}</div>
      </div>

    </div>
  </div>
</body>
</html>
"""
    return html, subtotal
