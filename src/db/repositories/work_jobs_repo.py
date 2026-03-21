# src/db/repositories/work_jobs_repo.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import List, Optional


def _normalize_text(value: Optional[str], default: str = "") -> str:
    """
    Normaliza un valor nullable a texto limpio.
    """
    if value is None:
        return default
    return str(value).strip()


@dataclass(frozen=True)
class WorkJob:
    id: int
    chat_id: int
    client: str
    phone: str
    address_text: str
    concept: str
    start_dt: str
    status: str
    created_at: str
    place_type: Optional[str]
    place_name: Optional[str]
    tower: Optional[str]
    apartment: Optional[str]
    waze_query: Optional[str]
    appliance: Optional[str]
    kind: Optional[str]
    last_reminded_at: Optional[str]
    updated_at: Optional[str]


def insert_work_job(
    conn: sqlite3.Connection,
    *,
    chat_id: int,
    client: str,
    phone: str,
    address_text: str,
    concept: str,
    start_dt_iso: str,
    created_at: str,
    place_type: Optional[str] = None,
    place_name: Optional[str] = None,
    tower: Optional[str] = None,
    apartment: Optional[str] = None,
    waze_query: Optional[str] = None,
    appliance: Optional[str] = None,
    kind: Optional[str] = None,
) -> int:
    """
    Inserta un trabajo agendado en `work_jobs`.

    Notas:
    - No hace commit; lo controla el caller.
    - `created_at` y `updated_at` se inicializan con el mismo valor.
    - Los campos opcionales se limpian antes de persistir.
    """
    normalized_client = _normalize_text(client, default="Cliente no identificado")
    normalized_phone = _normalize_text(phone)
    normalized_address = _normalize_text(address_text)
    normalized_concept = _normalize_text(concept, default="Trabajo")
    normalized_start_dt = _normalize_text(start_dt_iso)

    cur = conn.execute(
        """
        INSERT INTO work_jobs (
            chat_id,
            client,
            phone,
            address_text,
            concept,
            start_dt,
            status,
            created_at,
            place_type,
            place_name,
            tower,
            apartment,
            waze_query,
            appliance,
            kind,
            last_reminded_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
        """,
        (
            int(chat_id),
            normalized_client,
            normalized_phone,
            normalized_address,
            normalized_concept,
            normalized_start_dt,
            created_at,
            _normalize_text(place_type) or None,
            _normalize_text(place_name) or None,
            _normalize_text(tower) or None,
            _normalize_text(apartment) or None,
            _normalize_text(waze_query) or None,
            _normalize_text(appliance) or None,
            _normalize_text(kind) or None,
            created_at,
        ),
    )
    return int(cur.lastrowid)


def list_upcoming_work_jobs(
    conn: sqlite3.Connection,
    now_iso: str,
    days_ahead: int = 14,
) -> List[WorkJob]:
    """
    Lista trabajos pendientes dentro de la ventana indicada.
    """
    rows = conn.execute(
        """
        SELECT
            id,
            chat_id,
            client,
            phone,
            address_text,
            concept,
            start_dt,
            status,
            created_at,
            place_type,
            place_name,
            tower,
            apartment,
            waze_query,
            appliance,
            kind,
            last_reminded_at,
            updated_at
        FROM work_jobs
        WHERE status = 'pending'
          AND start_dt >= ?
          AND start_dt < datetime(?, printf('+%d days', ?))
        ORDER BY start_dt ASC
        """,
        (now_iso, now_iso, int(days_ahead)),
    ).fetchall()

    return [
        WorkJob(
            id=int(r["id"]),
            chat_id=int(r["chat_id"]),
            client=str(r["client"]),
            phone=str(r["phone"]),
            address_text=str(r["address_text"]),
            concept=str(r["concept"]),
            start_dt=str(r["start_dt"]),
            status=str(r["status"]),
            created_at=str(r["created_at"]),
            place_type=r["place_type"],
            place_name=r["place_name"],
            tower=r["tower"],
            apartment=r["apartment"],
            waze_query=r["waze_query"],
            appliance=r["appliance"],
            kind=r["kind"],
            last_reminded_at=r["last_reminded_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


def list_due_work_job_reminders(
    conn: sqlite3.Connection,
    now_iso: str,
) -> List[WorkJob]:
    """
    Devuelve trabajos pendientes cuya fecha/hora ya está vencida o llegó.

    Esta función es útil para el scheduler de recordatorios.
    """
    rows = conn.execute(
        """
        SELECT
            id,
            chat_id,
            client,
            phone,
            address_text,
            concept,
            start_dt,
            status,
            created_at,
            place_type,
            place_name,
            tower,
            apartment,
            waze_query,
            appliance,
            kind,
            last_reminded_at,
            updated_at
        FROM work_jobs
        WHERE status = 'pending'
          AND start_dt <= ?
        ORDER BY start_dt ASC
        """,
        (now_iso,),
    ).fetchall()

    return [
        WorkJob(
            id=int(r["id"]),
            chat_id=int(r["chat_id"]),
            client=str(r["client"]),
            phone=str(r["phone"]),
            address_text=str(r["address_text"]),
            concept=str(r["concept"]),
            start_dt=str(r["start_dt"]),
            status=str(r["status"]),
            created_at=str(r["created_at"]),
            place_type=r["place_type"],
            place_name=r["place_name"],
            tower=r["tower"],
            apartment=r["apartment"],
            waze_query=r["waze_query"],
            appliance=r["appliance"],
            kind=r["kind"],
            last_reminded_at=r["last_reminded_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


def mark_work_job_reminded(
    conn: sqlite3.Connection,
    job_id: int,
    reminded_at_iso: str,
) -> None:
    """
    Marca la fecha del último recordatorio enviado para un trabajo.
    """
    conn.execute(
        """
        UPDATE work_jobs
        SET last_reminded_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (reminded_at_iso, reminded_at_iso, int(job_id)),
    )


def mark_work_job_done(
    conn: sqlite3.Connection,
    job_id: int,
    updated_at_iso: str,
) -> None:
    """
    Marca un trabajo como realizado.
    """
    conn.execute(
        """
        UPDATE work_jobs
        SET status = 'done',
            updated_at = ?
        WHERE id = ?
        """,
        (updated_at_iso, int(job_id)),
    )


def mark_work_job_cancelled(
    conn: sqlite3.Connection,
    job_id: int,
    updated_at_iso: str,
) -> None:
    """
    Marca un trabajo como cancelado.
    """
    conn.execute(
        """
        UPDATE work_jobs
        SET status = 'cancelled',
            updated_at = ?
        WHERE id = ?
        """,
        (updated_at_iso, int(job_id)),
    )