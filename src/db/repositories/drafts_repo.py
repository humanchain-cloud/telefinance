"""
drafts_repo.py
--------------
Repositorio para manejar el estado conversacional del wizard en Telegram.

Propósito:
- Guardar el borrador actual por chat
- Recuperarlo para continuar el flujo
- Eliminarlo al finalizar o cancelar

Notas:
- No hace commit; lo controla el caller.
- Mantiene un retry corto para escrituras ante bloqueos transitorios de SQLite.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Draft:
    chat_id: int
    flow: str
    step: str
    data: Dict[str, Any]


def get(conn: sqlite3.Connection, chat_id: int) -> Optional[Draft]:
    """
    Obtiene el draft actual de un chat.

    Returns
    -------
    Draft | None
        Retorna el draft si existe; de lo contrario None.
    """
    row = conn.execute(
        """
        SELECT chat_id, flow, step, data_json
        FROM drafts
        WHERE chat_id = ?
        """,
        (int(chat_id),),
    ).fetchone()

    if not row:
        return None

    try:
        data = json.loads(row["data_json"] or "{}")
        if not isinstance(data, dict):
            data = {}
    except (TypeError, ValueError, json.JSONDecodeError):
        data = {}

    return Draft(
        chat_id=int(row["chat_id"]),
        flow=str(row["flow"]),
        step=str(row["step"]),
        data=data,
    )


def _retry_write(
    fn: Callable[[], T],
    *,
    retries: int = 5,
    base_sleep: float = 0.08,
) -> T:
    """
    Reintenta una operación de escritura si SQLite responde con lock transitorio.

    Estrategia:
    - backoff lineal: 80ms, 160ms, 240ms, ...
    - solo intercepta OperationalError relacionados con locks
    """
    last_exc: Optional[sqlite3.OperationalError] = None

    for i in range(retries):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "database is locked" in msg or "database locked" in msg:
                last_exc = e
                time.sleep(base_sleep * (i + 1))
                continue
            raise

    if last_exc is not None:
        raise last_exc

    raise sqlite3.OperationalError("Write retry failed without captured exception.")


def upsert(
    conn: sqlite3.Connection,
    chat_id: int,
    flow: str,
    step: str,
    data: Dict[str, Any],
    updated_at: str,
) -> None:
    """
    Inserta o actualiza el draft de un chat.
    """
    def _do() -> None:
        conn.execute(
            """
            INSERT INTO drafts (chat_id, flow, step, data_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                flow = excluded.flow,
                step = excluded.step,
                data_json = excluded.data_json,
                updated_at = excluded.updated_at
            """,
            (
                int(chat_id),
                str(flow).strip(),
                str(step).strip(),
                json.dumps(data or {}, ensure_ascii=False),
                updated_at,
            ),
        )

    _retry_write(_do)


def delete(conn: sqlite3.Connection, chat_id: int) -> None:
    """
    Elimina el draft asociado a un chat.
    """
    def _do() -> None:
        conn.execute(
            "DELETE FROM drafts WHERE chat_id = ?",
            (int(chat_id),),
        )

    _retry_write(_do)