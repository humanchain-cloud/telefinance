# src/db/repositories/ordered_parts_repo.py
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


def _normalize_float(value: Optional[float], default: float = 0.0) -> float:
    """
    Normaliza un valor numérico nullable a float seguro.
    """
    if value is None:
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


@dataclass(frozen=True)
class OrderedPart:
    id: int
    chat_id: int
    client: str
    phone: str
    address_text: str
    part_desc: str
    ordered_at: str
    first_remind_dt: str
    next_remind_dt: str
    remind_count: int  # 👈 NUEVO
    arrived: int
    installed: int
    legend: Optional[str]
    closed_at: Optional[str]
    created_at: str
    last_reminded_at: Optional[str]
    waze_url: Optional[str]
    total_usd: Optional[float]
    updated_at: Optional[str]


def insert_ordered_part(
    conn: sqlite3.Connection,
    *,
    chat_id: int,
    client: str,
    phone: str,
    address_text: str,
    part_desc: str,
    ordered_at_iso: str,
    first_remind_dt_iso: str,
    next_remind_dt_iso: str,
    created_at: str,
    waze_url: Optional[str] = None,
    total_usd: Optional[float] = None,
) -> int:
    """
    Inserta un pedido de repuesto.

    Notas:
    - No hace commit; lo controla el caller.
    - `created_at` y `updated_at` se inicializan con el mismo valor.
    """
    normalized_total_usd = None
    if total_usd is not None:
        normalized_total_usd = _normalize_float(total_usd, default=0.0)
        if normalized_total_usd < 0:
            normalized_total_usd = 0.0

    cur = conn.execute(
        """
        INSERT INTO ordered_parts (
            chat_id,
            client,
            phone,
            address_text,
            part_desc,
            ordered_at,
            first_remind_dt,
            next_remind_dt,
            arrived,
            installed,
            legend,
            closed_at,
            created_at,
            last_reminded_at,
            waze_url,
            total_usd,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, NULL, ?, NULL, ?, ?, ?)
        """,
        (
            int(chat_id),
            _normalize_text(client, default="Cliente no identificado"),
            _normalize_text(phone),
            _normalize_text(address_text),
            _normalize_text(part_desc, default="Repuesto"),
            _normalize_text(ordered_at_iso),
            _normalize_text(first_remind_dt_iso),
            _normalize_text(next_remind_dt_iso),
            created_at,
            _normalize_text(waze_url) or None,
            normalized_total_usd,
            created_at,
        ),
    )
    return int(cur.lastrowid)


def list_due_order_reminders(
    conn: sqlite3.Connection,
    now_iso: str,
) -> List[OrderedPart]:
    """
    Lista pedidos no instalados cuyo próximo recordatorio ya llegó o venció.

    Reglas:
    - installed = 0 → solo pedidos activos
    - remind_count < 2 → máximo 2 recordatorios
    - next_remind_dt <= now → ya es momento de avisar
    """
    rows = conn.execute(
        """
        SELECT
            id,
            chat_id,
            client,
            phone,
            address_text,
            part_desc,
            ordered_at,
            first_remind_dt,
            next_remind_dt,
            remind_count,
            arrived,
            installed,
            legend,
            closed_at,
            created_at,
            last_reminded_at,
            waze_url,
            total_usd,
            updated_at
        FROM ordered_parts
        WHERE installed = 0
          AND remind_count < 2
          AND next_remind_dt <= ?
        ORDER BY next_remind_dt ASC
        """,
        (now_iso,),
    ).fetchall()

    return [
        OrderedPart(
            id=int(r["id"]),
            chat_id=int(r["chat_id"]),
            client=str(r["client"]),
            phone=str(r["phone"]),
            address_text=str(r["address_text"]),
            part_desc=str(r["part_desc"]),
            ordered_at=str(r["ordered_at"]),
            first_remind_dt=str(r["first_remind_dt"]),
            next_remind_dt=str(r["next_remind_dt"]),
            remind_count=int(r["remind_count"] or 0),
            arrived=int(r["arrived"]),
            installed=int(r["installed"]),
            legend=r["legend"],
            closed_at=r["closed_at"],
            created_at=str(r["created_at"]),
            last_reminded_at=r["last_reminded_at"],
            waze_url=r["waze_url"],
            total_usd=float(r["total_usd"]) if r["total_usd"] is not None else None,
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


def mark_order_reminded(
    conn: sqlite3.Connection,
    order_id: int,
    reminded_at_iso: str,
) -> None:
    """
    Marca la fecha del último recordatorio enviado.
    """
    conn.execute(
        """
        UPDATE ordered_parts
        SET last_reminded_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (reminded_at_iso, reminded_at_iso, int(order_id)),
    )


def mark_arrived(
    conn: sqlite3.Connection,
    order_id: int,
    updated_at_iso: str,
) -> None:
    """
    Marca el pedido como llegado.
    """
    conn.execute(
        """
        UPDATE ordered_parts
        SET arrived = 1,
            updated_at = ?
        WHERE id = ?
        """,
        (updated_at_iso, int(order_id)),
    )


def mark_installed_and_close(
    conn: sqlite3.Connection,
    order_id: int,
    legend: str,
    closed_at_iso: str,
) -> None:
    """
    Marca el pedido como instalado y lo cierra.
    """
    conn.execute(
        """
        UPDATE ordered_parts
        SET installed = 1,
            legend = ?,
            closed_at = ?,
            next_remind_dt = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            _normalize_text(legend),
            closed_at_iso,
            closed_at_iso,
            closed_at_iso,
            int(order_id),
        ),
    )


def postpone_next_reminder(
    conn: sqlite3.Connection,
    order_id: int,
    next_remind_dt_iso: str,
    updated_at_iso: str,
) -> None:
    """
    Reprograma el próximo recordatorio del pedido.
    """
    conn.execute(
        """
        UPDATE ordered_parts
        SET next_remind_dt = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (next_remind_dt_iso, updated_at_iso, int(order_id)),
    )