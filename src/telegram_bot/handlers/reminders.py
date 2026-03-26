"""
reminders.py
------------
Recordatorios automáticos (JobQueue) para Telefinance.

Incluye:

1) ordered_parts (Pedidos)
   - Se dispara cuando next_remind_dt <= now y installed = 0
   - Envía recordatorio por Telegram
   - Reprograma next_remind_dt = now + 2 días
   - Anti-spam: no repite el mismo día usando last_reminded_at

2) maintenance_plans (Mantenimientos)
   - Se dispara cuando next_due_dt <= now y status = 'active'
   - Envía recordatorio para contactar al cliente
   - Anti-spam: no repite el mismo día usando last_reminded_at
   - Limpieza automática (TTL):
        borra mantenimientos 12 horas después de haber enviado el recordatorio

3) work_jobs (Trabajos agendados próximos)
   - Se dispara cuando el trabajo ocurrirá dentro de una ventana (90 min)
   - Envía resumen exacto + link directo de Waze
   - Anti-spam: no repite el mismo día usando last_reminded_at
   - Limpieza automática (TTL):
        borra trabajos cuya hora ya pasó y transcurrieron 12 horas

Regla anti-lock
---------------
- NO mantener conexión SQLite abierta durante awaits
- Lectura rápida primero
- Envío Telegram después
- Escritura bajo single-writer lock

Fix aplicado
------------
- Se corrigieron los SELECT que usaban COALESCE(...) sin alias.
  Eso era la causa del error:
      "No item with that key"
  al intentar acceder a sqlite3.Row con claves como:
      r["place_name"], r["ph_type"], etc.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from telegram.ext import ContextTypes

from src.core.utils_time import TimeContext
from src.db.connection import readonly_session, session
from src.db.repositories.maintenance_repo import mark_maintenance_reminded
from src.db.repositories.ordered_parts_repo import (
    list_due_order_reminders,
    mark_order_reminded,
    postpone_next_reminder,
)
from src.db.repositories.work_jobs_repo import mark_work_job_reminded


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------
WORK_REMIND_WINDOW_MINUTES = 90
WORK_FETCH_LOOKAHEAD_HOURS = 48
WORK_TTL_HOURS_AFTER_START = 12

MAINT_TTL_HOURS_AFTER_REMINDER = 12


# ---------------------------------------------------------------------
# Modelos locales
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class DueMaintenance:
    id: int
    chat_id: int
    client: str
    phone: str
    ph_type: str
    ph_name: Optional[str]
    address_text: str
    waze_url: Optional[str]
    appliances_json: str
    next_due_dt: str
    last_reminded_at: Optional[str]


@dataclass(frozen=True)
class DueWorkJob:
    id: int
    chat_id: int
    client: str
    phone: str
    address_text: str
    concept: str
    start_dt: str
    status: str
    place_type: str
    place_name: str
    tower: Optional[str]
    apartment: str
    waze_query: str
    appliance: str
    kind: str
    last_reminded_at: Optional[str]


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _same_day(a_iso: Optional[str], b_iso: str) -> bool:
    """
    Compara por día (YYYY-MM-DD) para evitar spam diario.
    """
    if not a_iso:
        return False
    return a_iso[:10] == b_iso[:10]


def _waze_url_from_query(query: str) -> str:
    """
    Genera link directo de Waze desde texto.
    """
    query = (query or "").strip()
    if not query:
        return "—"
    return f"https://waze.com/ul?q={quote_plus(query)}&navigate=yes"


def _fmt_dt_12h(iso_dt: str) -> str:
    """
    Formatea ISO datetime a texto 12h.
    """
    raw = (iso_dt or "").strip()
    if not raw:
        return "—"

    try:
        dt = datetime.fromisoformat(raw)
        return dt.strftime("%Y-%m-%d %I:%M %p")
    except Exception:
        return raw.replace("T", " ")


def _safe_json_list(raw: str) -> List[Dict[str, Any]]:
    """
    Parse seguro de JSON list.
    """
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _format_appliances(appliances: List[Dict[str, Any]]) -> str:
    """
    Formatea equipos tipo/marca/modelo para Telegram.
    """
    if not appliances:
        return "—"

    lines: List[str] = []
    for idx, appliance in enumerate(appliances, start=1):
        atype = (appliance.get("type") or "—").strip()
        brand = (appliance.get("brand") or "—").strip()
        model = (appliance.get("model") or "—").strip()
        lines.append(f"{idx}. {atype} | {brand} | {model}")

    return "\n".join(lines)


def _format_place(ph_type: str, ph_name: Optional[str]) -> str:
    """
    Formatea el lugar combinando tipo de PH y nombre.
    """
    ph_type = (ph_type or "—").strip()
    name = (ph_name or "").strip()
    return f"{ph_type}{(' - ' + name) if name else ''}"


def _parse_dt_flexible(raw: str) -> Optional[datetime]:
    """
    Intenta parsear datetimes guardados en distintos formatos razonables.
    """
    value = (raw or "").strip()
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except Exception:
        pass

    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


# ---------------------------------------------------------------------
# Fetchers (lectura rápida)
# ---------------------------------------------------------------------
def _fetch_due_maintenances(db_path: str, now_iso: str) -> List[DueMaintenance]:
    """
    Trae mantenimientos activos cuyo next_due_dt ya venció.

    Importante:
    - Se usan alias explícitos (AS ...) en expresiones COALESCE(...)
      para que sqlite3.Row exponga las claves esperadas.
    """
    with readonly_session(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                chat_id,
                client,
                phone,
                COALESCE(ph_type, '') AS ph_type,
                ph_name,
                COALESCE(address_text, '') AS address_text,
                waze_url,
                COALESCE(appliances_json, '[]') AS appliances_json,
                next_due_dt,
                last_reminded_at
            FROM maintenance_plans
            WHERE status = 'active'
              AND datetime(next_due_dt) <= datetime(?)
            ORDER BY next_due_dt ASC
            LIMIT 50
            """,
            (now_iso,),
        ).fetchall()

    return [
        DueMaintenance(
            id=int(r["id"]),
            chat_id=int(r["chat_id"]),
            client=str(r["client"]),
            phone=str(r["phone"]),
            ph_type=str(r["ph_type"]),
            ph_name=r["ph_name"],
            address_text=str(r["address_text"]),
            waze_url=r["waze_url"],
            appliances_json=str(r["appliances_json"]),
            next_due_dt=str(r["next_due_dt"]),
            last_reminded_at=r["last_reminded_at"],
        )
        for r in rows
    ]


def _fetch_due_work_jobs(db_path: str, now_iso: str) -> List[DueWorkJob]:
    """
    Trae trabajos próximos dentro de la ventana de recordatorio.

    Regla:
    - status = 'pending'
    - start_dt debe estar entre now y now + WORK_REMIND_WINDOW_MINUTES
    - además se descartan trabajos muy lejanos usando lookahead
    """
    now = datetime.fromisoformat(now_iso)
    window_end = now + timedelta(minutes=WORK_REMIND_WINDOW_MINUTES)
    lookahead_end = now + timedelta(hours=WORK_FETCH_LOOKAHEAD_HOURS)

    with readonly_session(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                chat_id,
                client,
                phone,
                COALESCE(address_text, '') AS address_text,
                COALESCE(concept, '') AS concept,
                COALESCE(start_dt, '') AS start_dt,
                COALESCE(status, '') AS status,
                COALESCE(place_type, '') AS place_type,
                COALESCE(place_name, '') AS place_name,
                tower,
                COALESCE(apartment, '') AS apartment,
                COALESCE(waze_query, '') AS waze_query,
                COALESCE(appliance, '') AS appliance,
                COALESCE(kind, '') AS kind,
                last_reminded_at
            FROM work_jobs
            WHERE status = 'pending'
            ORDER BY start_dt ASC
            LIMIT 200
            """
        ).fetchall()

    due: List[DueWorkJob] = []

    for r in rows:
        parsed_start = _parse_dt_flexible(str(r["start_dt"] or ""))
        if parsed_start is None:
            continue

        if parsed_start < now:
            continue
        if parsed_start > lookahead_end:
            continue
        if parsed_start > window_end:
            continue

        due.append(
            DueWorkJob(
                id=int(r["id"]),
                chat_id=int(r["chat_id"]),
                client=str(r["client"]),
                phone=str(r["phone"]),
                address_text=str(r["address_text"]),
                concept=str(r["concept"]),
                start_dt=str(r["start_dt"]),
                status=str(r["status"]),
                place_type=str(r["place_type"]),
                place_name=str(r["place_name"]),
                tower=r["tower"],
                apartment=str(r["apartment"]),
                waze_query=str(r["waze_query"]),
                appliance=str(r["appliance"]),
                kind=str(r["kind"]),
                last_reminded_at=r["last_reminded_at"],
            )
        )

    return due


# ---------------------------------------------------------------------
# Limpieza automática (TTL)
# ---------------------------------------------------------------------
def _delete_expired_work_jobs(conn, *, cutoff_iso: str) -> int:
    """
    Borra trabajos cuya hora ya pasó y han transcurrido
    >= WORK_TTL_HOURS_AFTER_START.
    """
    cur = conn.execute(
        """
        DELETE FROM work_jobs
        WHERE datetime(start_dt) <= datetime(?)
        """,
        (cutoff_iso,),
    )
    return int(cur.rowcount)


def _delete_expired_maintenances(conn, *, now_iso: str) -> int:
    """
    Borra mantenimientos 12 horas después del último recordatorio.
    """
    now = datetime.fromisoformat(now_iso)
    cutoff = (
        now - timedelta(hours=MAINT_TTL_HOURS_AFTER_REMINDER)
    ).isoformat(timespec="seconds")

    cur = conn.execute(
        """
        DELETE FROM maintenance_plans
        WHERE last_reminded_at IS NOT NULL
          AND datetime(last_reminded_at) <= datetime(?)
        """,
        (cutoff,),
    )
    return int(cur.rowcount)


# ---------------------------------------------------------------------
# Tick principal
# ---------------------------------------------------------------------
async def reminders_tick(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Tick del JobQueue. Recomendado: cada 60s.

    Flujo:
    1) Limpia registros expirados
    2) Procesa pedidos
    3) Procesa mantenimientos
    4) Procesa trabajos próximos
    """
    tctx: TimeContext = context.bot_data["tctx"]
    db_path: str = context.bot_data["db_path"]
    lock = context.bot_data["db_write_lock"]

    now_iso = tctx.now_iso()

    logger.debug("reminders_tick iniciado | now_iso=%s", now_iso)

    # =========================================================
    # 0) Limpiezas automáticas
    # =========================================================
    cutoff_dt = datetime.fromisoformat(now_iso) - timedelta(hours=WORK_TTL_HOURS_AFTER_START)
    cutoff_iso = cutoff_dt.isoformat(timespec="seconds")

    async def _cleanup() -> None:
        with session(db_path, immediate=True) as conn:
            deleted_jobs = _delete_expired_work_jobs(conn, cutoff_iso=cutoff_iso)
            deleted_maints = _delete_expired_maintenances(conn, now_iso=now_iso)

            logger.debug(
                "cleanup reminders | deleted_jobs=%s deleted_maintenances=%s",
                deleted_jobs,
                deleted_maints,
            )

    await lock.run(_cleanup)

    # =========================================================
    # 1) Pedidos
    # =========================================================
    with readonly_session(db_path) as conn:
        due_orders = list_due_order_reminders(conn, now_iso)

    logger.debug("due_orders encontrados=%s", len(due_orders))

    for order in due_orders:
        if _same_day(order.last_reminded_at, now_iso):
            continue

        try:
            await context.bot.send_message(
                chat_id=order.chat_id,
                text=(
                    "📦 *RECORDATORIO — PEDIDO DE PIEZA*\n\n"
                    f"🆔 ID: `{order.id}`\n\n"
                    f"👤 Cliente: *{order.client}*\n"
                    f"📞 Tel: `{order.phone}`\n"
                    f"📍 Dirección: {order.address_text}\n"
                    f"🚗 Waze: {(order.waze_url or '—')}\n\n"
                    f"🧾 Pedido: _{order.part_desc}_\n"
                    f"💵 Total USD: *{f'${order.total_usd:.2f}' if order.total_usd is not None else '—'}*\n\n"
                    f"⏰ Próximo aviso programado: *{_fmt_dt_12h(order.next_remind_dt)}*\n"
                    "✅ Acción: contactar al cliente para coordinar entrega/instalación."
                ),
                parse_mode="Markdown",
                disable_web_page_preview=False,
            )
        except Exception as exc:
            logger.exception(
                "Error enviando recordatorio de pedido | order_id=%s chat_id=%s error=%s",
                getattr(order, "id", "—"),
                getattr(order, "chat_id", "—"),
                exc,
            )
            continue

        async def _write_order() -> None:
            with session(db_path, immediate=True) as conn:
                cur = conn.execute(
                    "SELECT remind_count FROM ordered_parts WHERE id = ?",
                    (order.id,),
                ).fetchone()

                current_count = int(cur[0] or 0)
                new_count = current_count + 1

                conn.execute(
                    """
                    UPDATE ordered_parts
                    SET remind_count = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (new_count, now_iso, int(order.id)),
                )

                mark_order_reminded(conn, order.id, now_iso)

                if new_count < 2:
                    next_iso = TimeContext.add_days_iso(now_iso, 2)
                    postpone_next_reminder(conn, order.id, next_iso, now_iso)
                else:
                    logger.info(
                        "Pedido %s alcanzó límite de recordatorios (%s). Detenido.",
                        order.id,
                        new_count,
                    )
        await lock.run(_write_order)

    # =========================================================
    # 2) Mantenimientos
    # =========================================================
    due_maintenances = _fetch_due_maintenances(db_path, now_iso)
    logger.debug("due_maintenances encontrados=%s", len(due_maintenances))

    for maint in due_maintenances:
        if _same_day(maint.last_reminded_at, now_iso):
            continue

        place = _format_place(maint.ph_type, maint.ph_name)
        appliances = _safe_json_list(maint.appliances_json)
        appliances_txt = _format_appliances(appliances)
        waze = (maint.waze_url or "—").strip()

        message = (
            "🧰 *RECORDATORIO — MANTENIMIENTO ANUAL*\n\n"
            "⏰ Hoy se cumple 1 año. Contacta al cliente para agendar.\n\n"
            f"🆔 ID: `{maint.id}`\n"
            f"👤 Cliente: *{maint.client}*\n"
            f"📞 Tel: `{maint.phone}`\n\n"
            f"🏠 Tipo/Lugar: *{place}*\n"
            f"🗺️ Dirección: {maint.address_text}\n"
            f"🚗 Waze: {waze}\n\n"
            f"🧰 Equipos:\n{appliances_txt}\n\n"
            f"⏰ Recordatorio programado: *{_fmt_dt_12h(maint.next_due_dt)}*"
        )

        try:
            await context.bot.send_message(
                chat_id=maint.chat_id,
                text=message,
                parse_mode="Markdown",
                disable_web_page_preview=False,
            )
        except Exception as exc:
            logger.exception(
                "Error enviando recordatorio de mantenimiento | maintenance_id=%s chat_id=%s error=%s",
                getattr(maint, "id", "—"),
                getattr(maint, "chat_id", "—"),
                exc,
            )
            continue

        async def _write_maint() -> None:
            with session(db_path, immediate=True) as conn:
                mark_maintenance_reminded(conn, maint.id, now_iso)

        await lock.run(_write_maint)

    # =========================================================
    # 3) Trabajos agendados próximos
    # =========================================================
    due_jobs = _fetch_due_work_jobs(db_path, now_iso)
    logger.debug("due_jobs encontrados=%s", len(due_jobs))

    for job in due_jobs:
        if _same_day(job.last_reminded_at, now_iso):
            continue

        waze_url = _waze_url_from_query(job.waze_query)
        tower = job.tower or "—"
        apt = job.apartment or "—"
        place_type = job.place_type or "—"
        place_name = job.place_name or "—"
        address = job.address_text or place_name or "—"
        start_show = _fmt_dt_12h(job.start_dt)

        message = (
            "🔔 *RECORDATORIO — TRABAJO AGENDADO*\n\n"
            f"🆔 ID: `{job.id}`\n\n"
            f"👤 Cliente: *{job.client}*\n"
            f"📞 Tel: `{job.phone}`\n\n"
            f"🏠 Tipo: *{place_type}*\n"
            f"📍 Lugar/PH/Ref: *{place_name}*\n"
            f"🏢 Torre: *{tower}*\n"
            f"🚪 Apto: *{apt}*\n"
            f"🗺️ Dirección: {address}\n\n"
            f"🧰 Equipo: *{job.appliance}*\n"
            f"🛠️ Tipo: *{job.kind}*\n"
            f"🧾 Concepto: _{job.concept}_\n\n"
            f"⏰ Fecha/Hora: *{start_show}*\n\n"
            f"🚗 Waze (navegar): {waze_url}\n"
        )

        try:
            await context.bot.send_message(
                chat_id=job.chat_id,
                text=message,
                parse_mode="Markdown",
                disable_web_page_preview=False,
            )
        except Exception as exc:
            logger.exception(
                "Error enviando recordatorio de trabajo | job_id=%s chat_id=%s error=%s",
                getattr(job, "id", "—"),
                getattr(job, "chat_id", "—"),
                exc,
            )
            continue

        async def _write_job() -> None:
            with session(db_path, immediate=True) as conn:
                mark_work_job_reminded(conn, job.id, now_iso)

        await lock.run(_write_job)