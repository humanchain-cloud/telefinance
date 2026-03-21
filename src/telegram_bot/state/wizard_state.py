# src/telegram_bot/state/wizard_state.py
"""
wizard_state.py
---------------
Estados (flow + steps) para el bot de Telegram (Telefinance).

Objetivo:
- Centralizar constantes para el router (service_wizard.py) y evitar strings mágicos.
- Mantener compatibilidad con flujos existentes.
- Permitir que algunos flujos usen "steps locales" cuando convenga (ej: pedidos),
  sin obligar a inflar este archivo con cada micro-variación.

Convenciones:
- FLOW_* define el flujo activo del usuario.
- STEP_* define el paso dentro de ese flujo.
- Los valores son strings estables (no cambiar nombres a la ligera).
"""

from __future__ import annotations

# ---------------------------------------------------------------------
# FLOWS (máquina de estados)
# ---------------------------------------------------------------------
FLOW_MAIN_MENU = "main_menu"
FLOW_CREATE_SERVICE_INVOICE = "create_service_invoice"

# Coordinador de trabajo (menú + subflujos)
FLOW_WORK_COORDINATOR = "work_coordinator"
FLOW_SCHEDULE_WORK = "schedule_work"
FLOW_SCHEDULE_MAINTENANCE = "schedule_maintenance"
FLOW_ORDER_REMINDER = "order_reminder"


# ---------------------------------------------------------------------
# STEPS - Menús
# ---------------------------------------------------------------------
STEP_MENU = "menu"                 # menú principal
STEP_COORD_MENU = "coord_menu"     # menú coordinador


# ---------------------------------------------------------------------
# STEPS - Recibo de servicio (factura/recibo por chat)
# ---------------------------------------------------------------------
STEP_CLIENT_NAME = "client_name"
STEP_DATE_CHOICE = "date_choice"
STEP_DATE_MANUAL = "date_manual"
STEP_ITEM_DESC = "item_desc"
STEP_ITEM_QTY = "item_qty"
STEP_ITEM_UNIT = "item_unit"
STEP_ITEM_MORE = "item_more"


# ---------------------------------------------------------------------
# STEPS - Agendar trabajo (work_jobs)
# ---------------------------------------------------------------------
STEP_WORK_CLIENT = "work_client"
STEP_WORK_PHONE = "work_phone"

# NOTA:
# En service_wizard.py este flujo usa steps locales adicionales (place_type, etc.)
# para no inflar este archivo y mantener flexibilidad. Los pasos base se declaran aquí.
STEP_WORK_ADDRESS = "work_address"         # (legacy / reservado)
STEP_WORK_START_DT = "work_start_dt"       # (legacy / reservado)
STEP_WORK_CONCEPT = "work_concept"         # (legacy / reservado)


# ---------------------------------------------------------------------
# STEPS - Agendar mantenimiento (maintenance_plans)
# ---------------------------------------------------------------------
STEP_MAINT_CLIENT = "maint_client"
STEP_MAINT_PHONE = "maint_phone"
STEP_MAINT_PH_TYPE = "maint_ph_type"               # 1=PH, 2=Casa
STEP_MAINT_PH_NAME = "maint_ph_name"               # si PH
STEP_MAINT_ADDRESS = "maint_address"
STEP_MAINT_WAZE = "maint_waze"                     # (legacy: antes se pedía link)
STEP_MAINT_APPLIANCES_COUNT = "maint_appliances_count"
STEP_MAINT_APPLIANCE_ONE = "maint_appliance_one"

# Legacy (antes se pedían fotos y fecha manual):
STEP_MAINT_PHOTOS = "maint_photos"
STEP_MAINT_START_DT = "maint_start_dt"


# ---------------------------------------------------------------------
# STEPS - Pedidos ordenados (ordered_parts)
# ---------------------------------------------------------------------
STEP_ORDER_CLIENT = "order_client"
STEP_ORDER_PHONE = "order_phone"
STEP_ORDER_ADDRESS = "order_address"          # legacy (antes se pedía dirección aquí)
STEP_ORDER_DESC = "order_desc"
STEP_ORDER_AWAIT_STATUS = "order_await_status"  # legacy (antes: llego/no/instalado)

# Nota:
# El flujo NUEVO de pedidos usa steps locales dentro de service_wizard.py:
# - order_waze_text
# - order_total_usd
# - order_confirm
# Esto es intencional para permitir iteración rápida sin romper compatibilidad.


# ---------------------------------------------------------------------
# Export explícito
# ---------------------------------------------------------------------
__all__ = [
    # flows
    "FLOW_MAIN_MENU",
    "FLOW_CREATE_SERVICE_INVOICE",
    "FLOW_WORK_COORDINATOR",
    "FLOW_SCHEDULE_WORK",
    "FLOW_SCHEDULE_MAINTENANCE",
    "FLOW_ORDER_REMINDER",
    # menu steps
    "STEP_MENU",
    "STEP_COORD_MENU",
    # invoice steps
    "STEP_CLIENT_NAME",
    "STEP_DATE_CHOICE",
    "STEP_DATE_MANUAL",
    "STEP_ITEM_DESC",
    "STEP_ITEM_QTY",
    "STEP_ITEM_UNIT",
    "STEP_ITEM_MORE",
    # work steps
    "STEP_WORK_CLIENT",
    "STEP_WORK_PHONE",
    "STEP_WORK_ADDRESS",
    "STEP_WORK_START_DT",
    "STEP_WORK_CONCEPT",
    # maintenance steps
    "STEP_MAINT_CLIENT",
    "STEP_MAINT_PHONE",
    "STEP_MAINT_PH_TYPE",
    "STEP_MAINT_PH_NAME",
    "STEP_MAINT_ADDRESS",
    "STEP_MAINT_WAZE",
    "STEP_MAINT_APPLIANCES_COUNT",
    "STEP_MAINT_APPLIANCE_ONE",
    "STEP_MAINT_PHOTOS",
    "STEP_MAINT_START_DT",
    # order steps (legacy + base)
    "STEP_ORDER_CLIENT",
    "STEP_ORDER_PHONE",
    "STEP_ORDER_ADDRESS",
    "STEP_ORDER_DESC",
    "STEP_ORDER_AWAIT_STATUS",
]