# src/db/repositories/maintenance_repo.py
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def _normalize_text(value: Optional[str], default: str = "") -> str:
    """
    Normaliza un valor nullable a texto limpio.
    """
    if value is None:
        return default
    return str(value).strip()


@dataclass(frozen=True)
class MaintenancePlan:
    id: int
    chat_id: int
    client: str
    phone: str
    ph_type: str
    ph_name: Optional[str]
    address_text: str
    waze_url: Optional[str]
    appliances_count: int
    appliances_json: str
    photos_json: str
    start_dt: str
    next_due_dt: str
    status: str
    created_at: str
    last_reminded_at: Optional[str]
    updated_at: Optional[str]

    def appliances(self) -> List[Dict[str, Any]]:
        return json.loads(self.appliances_json or "[]")

    def photos(self) -> List[str]:
        return json.loads(self.photos_json or "[]")


def insert_maintenance_plan(
    conn: sqlite3.Connection,
    *,
    chat_id: int,
    client: str,
    phone: str,
    ph_type: str,
    ph_name: Optional[str],
    address_text: str,
    waze_url: Optional[str],
    appliances_count: int,
    appliances: List[Dict[str, Any]],
    photos: List[str],
    start_dt_iso: str,
    next_due_dt_iso: str,
    created_at: str,
) -> int:
    """
    Inserta un plan de mantenimiento.

    Notas:
    - No hace commit; lo controla el caller.
    - `created_at` y `updated_at` se inicializan con el mismo valor.
    """
    normalized_client = _normalize_text(client, default="Cliente no identificado")
    normalized_phone = _normalize_text(phone)
    normalized_ph_type = _normalize_text(ph_type, default="PH")
    normalized_ph_name = _normalize_text(ph_name) or None
    normalized_address = _normalize_text(address_text)
    normalized_waze_url = _normalize_text(waze_url) or None
    normalized_start_dt = _normalize_text(start_dt_iso)
    normalized_next_due_dt = _normalize_text(next_due_dt_iso)

    normalized_appliances_count = int(appliances_count or 1)
    if normalized_appliances_count < 1:
        normalized_appliances_count = 1

    cur = conn.execute(
        """
        INSERT INTO maintenance_plans (
            chat_id,
            client,
            phone,
            ph_type,
            ph_name,
            address_text,
            waze_url,
            appliances_count,
            appliances_json,
            photos_json,
            start_dt,
            next_due_dt,
            status,
            created_at,
            last_reminded_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, NULL, ?)
        """,
        (
            int(chat_id),
            normalized_client,
            normalized_phone,
            normalized_ph_type,
            normalized_ph_name,
            normalized_address,
            normalized_waze_url,
            normalized_appliances_count,
            json.dumps(appliances or [], ensure_ascii=False),
            json.dumps(photos or [], ensure_ascii=False),
            normalized_start_dt,
            normalized_next_due_dt,
            created_at,
            created_at,
        ),
    )
    return int(cur.lastrowid)


def list_maintenances_next_12_months(
    conn: sqlite3.Connection,
    now_iso: str,
) -> List[MaintenancePlan]:
    """
    Lista mantenimientos activos dentro de los próximos 12 meses.
    """
    rows = conn.execute(
        """
        SELECT
            id,
            chat_id,
            client,
            phone,
            ph_type,
            ph_name,
            address_text,
            waze_url,
            appliances_count,
            appliances_json,
            photos_json,
            start_dt,
            next_due_dt,
            status,
            created_at,
            last_reminded_at,
            updated_at
        FROM maintenance_plans
        WHERE status = 'active'
          AND next_due_dt >= ?
          AND next_due_dt < datetime(?, '+365 days')
        ORDER BY next_due_dt ASC
        """,
        (now_iso, now_iso),
    ).fetchall()

    return [
        MaintenancePlan(
            id=int(r["id"]),
            chat_id=int(r["chat_id"]),
            client=str(r["client"]),
            phone=str(r["phone"]),
            ph_type=str(r["ph_type"]),
            ph_name=r["ph_name"],
            address_text=str(r["address_text"]),
            waze_url=r["waze_url"],
            appliances_count=int(r["appliances_count"]),
            appliances_json=str(r["appliances_json"]),
            photos_json=str(r["photos_json"]),
            start_dt=str(r["start_dt"]),
            next_due_dt=str(r["next_due_dt"]),
            status=str(r["status"]),
            created_at=str(r["created_at"]),
            last_reminded_at=r["last_reminded_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


def list_due_maintenance_reminders(
    conn: sqlite3.Connection,
    now_iso: str,
) -> List[MaintenancePlan]:
    """
    Devuelve mantenimientos activos cuyo `next_due_dt` ya llegó o venció.
    """
    rows = conn.execute(
        """
        SELECT
            id,
            chat_id,
            client,
            phone,
            ph_type,
            ph_name,
            address_text,
            waze_url,
            appliances_count,
            appliances_json,
            photos_json,
            start_dt,
            next_due_dt,
            status,
            created_at,
            last_reminded_at,
            updated_at
        FROM maintenance_plans
        WHERE status = 'active'
          AND next_due_dt <= ?
        ORDER BY next_due_dt ASC
        """,
        (now_iso,),
    ).fetchall()

    return [
        MaintenancePlan(
            id=int(r["id"]),
            chat_id=int(r["chat_id"]),
            client=str(r["client"]),
            phone=str(r["phone"]),
            ph_type=str(r["ph_type"]),
            ph_name=r["ph_name"],
            address_text=str(r["address_text"]),
            waze_url=r["waze_url"],
            appliances_count=int(r["appliances_count"]),
            appliances_json=str(r["appliances_json"]),
            photos_json=str(r["photos_json"]),
            start_dt=str(r["start_dt"]),
            next_due_dt=str(r["next_due_dt"]),
            status=str(r["status"]),
            created_at=str(r["created_at"]),
            last_reminded_at=r["last_reminded_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


def mark_maintenance_reminded(
    conn: sqlite3.Connection,
    plan_id: int,
    reminded_at_iso: str,
) -> None:
    """
    Marca la fecha del último recordatorio enviado.
    """
    conn.execute(
        """
        UPDATE maintenance_plans
        SET last_reminded_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (reminded_at_iso, reminded_at_iso, int(plan_id)),
    )


def mark_maintenance_done(
    conn: sqlite3.Connection,
    plan_id: int,
    updated_at_iso: str,
) -> None:
    """
    Marca el plan como completado.
    """
    conn.execute(
        """
        UPDATE maintenance_plans
        SET status = 'done',
            updated_at = ?
        WHERE id = ?
        """,
        (updated_at_iso, int(plan_id)),
    )


def cancel_maintenance_plan(
    conn: sqlite3.Connection,
    plan_id: int,
    updated_at_iso: str,
) -> None:
    """
    Cancela un plan de mantenimiento.
    """
    conn.execute(
        """
        UPDATE maintenance_plans
        SET status = 'cancelled',
            updated_at = ?
        WHERE id = ?
        """,
        (updated_at_iso, int(plan_id)),
    )


def reactivate_maintenance_plan(
    conn: sqlite3.Connection,
    plan_id: int,
    updated_at_iso: str,
) -> None:
    """
    Reactiva un plan de mantenimiento cancelado o completado.
    """
    conn.execute(
        """
        UPDATE maintenance_plans
        SET status = 'active',
            updated_at = ?
        WHERE id = ?
        """,
        (updated_at_iso, int(plan_id)),
    )