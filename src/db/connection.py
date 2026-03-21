"""
connection.py
-------------
Gestión de conexiones SQLite para Telefinance.

Objetivos:
- Permitir escrituras seguras desde el bot de Telegram
- Permitir lecturas concurrentes desde Streamlit
- Reducir bloqueos usando WAL + busy_timeout
- Preparar la base para despliegue en VPS con dashboard expuesto por túnel o proxy

Estrategia:
- `connect()` para lectura/escritura
- `connect_readonly()` para dashboards y reportes
- `session()` para transacciones controladas
- `readonly_session()` para consultas seguras de solo lectura
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Union

from src.core.errors import DatabaseError

DbPath = Union[str, Path]


def _normalize_db_path(db_path: DbPath) -> Path:
    """
    Normaliza la ruta de la base de datos y asegura que el directorio padre exista.

    Parameters
    ----------
    db_path:
        Ruta al archivo SQLite.

    Returns
    -------
    Path
        Ruta absoluta y normalizada.
    """
    path = Path(db_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """
    Aplica los PRAGMA recomendados para Telefinance.

    PRAGMAs elegidos:
    - journal_mode=WAL:
        Permite lecturas concurrentes mientras el bot escribe.
    - foreign_keys=ON:
        Activa integridad referencial real.
    - synchronous=NORMAL:
        Buen equilibrio entre durabilidad y rendimiento en WAL.
    - temp_store=MEMORY:
        Mejora operaciones temporales.
    - busy_timeout=5000:
        Espera hasta 5 segundos antes de fallar por lock.
    """
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA busy_timeout = 5000;")


def connect(db_path: DbPath) -> sqlite3.Connection:
    """
    Abre una conexión SQLite de lectura/escritura.

    Esta conexión está pensada para:
    - handlers del bot
    - repositorios que escriben
    - migraciones
    - procesos internos del sistema

    Parameters
    ----------
    db_path:
        Ruta al archivo SQLite.

    Returns
    -------
    sqlite3.Connection
        Conexión configurada para Telefinance.

    Raises
    ------
    DatabaseError
        Si no se pudo abrir la conexión.
    """
    try:
        path = _normalize_db_path(db_path)

        conn = sqlite3.connect(
            str(path),
            timeout=5.0,
            check_same_thread=False,
            isolation_level=None,  # transacciones manuales: BEGIN / COMMIT / ROLLBACK
        )
        conn.row_factory = sqlite3.Row
        _apply_pragmas(conn)
        return conn

    except sqlite3.Error as e:
        raise DatabaseError(f"No se pudo conectar a SQLite: {e}") from e
    except Exception as e:
        raise DatabaseError(f"Error inesperado conectando a SQLite: {e}") from e


def connect_readonly(db_path: DbPath) -> sqlite3.Connection:
    """
    Abre una conexión SQLite en modo solo lectura.

    Ideal para:
    - Streamlit
    - dashboards
    - reportes
    - consultas analíticas
    - vistas administrativas sin escritura

    Parameters
    ----------
    db_path:
        Ruta al archivo SQLite.

    Returns
    -------
    sqlite3.Connection
        Conexión readonly configurada para Telefinance.

    Raises
    ------
    DatabaseError
        Si no se pudo abrir la conexión.
    """
    try:
        path = _normalize_db_path(db_path)
        uri = f"file:{path}?mode=ro"

        conn = sqlite3.connect(
            uri,
            uri=True,
            timeout=5.0,
            check_same_thread=False,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        _apply_pragmas(conn)
        return conn

    except sqlite3.Error as e:
        raise DatabaseError(f"No se pudo conectar a SQLite en modo solo lectura: {e}") from e
    except Exception as e:
        raise DatabaseError(f"Error inesperado en conexión readonly: {e}") from e


@contextmanager
def session(db_path: DbPath, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
    """
    Maneja una sesión transaccional de lectura/escritura.

    Parameters
    ----------
    db_path:
        Ruta al archivo SQLite.

    immediate:
        Si es True, usa `BEGIN IMMEDIATE` para reservar temprano el lock de escritura.
        Útil en operaciones críticas del bot.
        Si es False, usa `BEGIN`.

    Yields
    ------
    sqlite3.Connection
        Conexión activa dentro de una transacción.

    Behaviour
    ---------
    - Hace COMMIT si todo sale bien
    - Hace ROLLBACK si ocurre una excepción
    - Siempre cierra la conexión al final
    """
    conn = connect(db_path)
    try:
        if immediate:
            conn.execute("BEGIN IMMEDIATE;")
        else:
            conn.execute("BEGIN;")

        yield conn
        conn.commit()

    except Exception:
        try:
            conn.rollback()
        except sqlite3.OperationalError:
            pass
        raise

    finally:
        conn.close()


@contextmanager
def readonly_session(db_path: DbPath) -> Iterator[sqlite3.Connection]:
    """
    Maneja una sesión de solo lectura.

    Ideal para:
    - Streamlit
    - consultas de dashboards
    - reportes PDF
    - análisis

    Parameters
    ----------
    db_path:
        Ruta al archivo SQLite.

    Yields
    ------
    sqlite3.Connection
        Conexión activa readonly.
    """
    conn = connect_readonly(db_path)
    try:
        yield conn
    finally:
        conn.close()