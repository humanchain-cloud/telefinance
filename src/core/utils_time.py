"""
utils_time.py
-------------
Funciones de tiempo, formateo y timezone.

Convención:
- Internamente usamos ISO8601 cuando sea posible.
- Para UI (Telegram/Streamlit) podemos mostrar formatos amigables.

Notas:
- Este módulo NO depende de librerías externas (sin python-dateutil).
- La suma de meses se implementa de forma segura:
  - Si el día no existe en el mes destino (ej. 31), se ajusta al último día del mes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo


# ---------------------------------------------------------------------
# Helpers de calendario (internos)
# ---------------------------------------------------------------------
def _is_leap_year(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


def _days_in_month(year: int, month: int) -> int:
    if month in (1, 3, 5, 7, 8, 10, 12):
        return 31
    if month in (4, 6, 9, 11):
        return 30
    # Febrero
    return 29 if _is_leap_year(year) else 28


def _add_months(dt: datetime, months: int) -> datetime:
    """
    Suma 'months' meses a dt conservando el día si existe.
    Si el día no existe en el mes destino, ajusta al último día del mes.

    Ej:
    - 2026-01-31 + 1 mes => 2026-02-28
    - 2024-01-31 + 1 mes => 2024-02-29 (año bisiesto)
    """
    y = dt.year
    m = dt.month + months

    # Normalizar año/mes
    while m > 12:
        y += 1
        m -= 12
    while m < 1:
        y -= 1
        m += 12

    last_day = _days_in_month(y, m)
    d = min(dt.day, last_day)

    return dt.replace(year=y, month=m, day=d)


# ---------------------------------------------------------------------
# TimeContext
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class TimeContext:
    """
    Contexto de tiempo con timezone.
    """
    tz: ZoneInfo

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def today(self) -> date:
        return self.now().date()

    def now_iso(self) -> str:
        """
        Timestamp ISO con segundos.
        """
        return self.now().isoformat(timespec="seconds")

    def now_compact(self) -> str:
        """
        Timestamp compacto para nombres de archivo.
        Ej: 20260213_164649
        """
        return self.now().strftime("%Y%m%d_%H%M%S")

    @staticmethod
    def parse_iso(iso_str: str) -> datetime:
        """
        Parsea un ISO8601 producido por datetime.isoformat().
        """
        return datetime.fromisoformat(iso_str)

    @staticmethod
    def to_iso(dt: datetime) -> str:
        """
        Normaliza datetime a ISO8601 con segundos.
        """
        return dt.isoformat(timespec="seconds")

    @staticmethod
    def add_days_iso(base_iso: str, days: int) -> str:
        """
        Suma días a un timestamp ISO y retorna ISO con segundos.
        """
        dt = TimeContext.parse_iso(base_iso)
        return TimeContext.to_iso(dt + timedelta(days=days))

    @staticmethod
    def add_months_iso(base_iso: str, months: int) -> str:
        """
        Suma meses a un timestamp ISO (sin librerías externas).
        - Si el día no existe en el mes destino, ajusta al último día del mes.
        """
        dt = TimeContext.parse_iso(base_iso)
        return TimeContext.to_iso(_add_months(dt, months))
    
    @staticmethod
    def add_minutes_iso(base_iso: str, minutes: int) -> str:
        """
        Suma/resta minutos a un timestamp ISO y retorna ISO con segundos.

        - Preserva timezone si base_iso ya lo incluye (ej: -05:00).
        - Si base_iso no incluye timezone, se mantiene naive (igual que datetime.fromisoformat()).
        """
        dt = TimeContext.parse_iso(base_iso)
        return TimeContext.to_iso(dt + timedelta(minutes=int(minutes)))

    @staticmethod
    def add_hours_iso(base_iso: str, hours: int) -> str:
        """
        Suma/resta horas a un timestamp ISO y retorna ISO con segundos.

        - Preserva timezone si base_iso ya lo incluye (ej: -05:00).
        - Si base_iso no incluye timezone, se mantiene naive.
        """
        dt = TimeContext.parse_iso(base_iso)
        return TimeContext.to_iso(dt + timedelta(hours=int(hours)))

    @staticmethod
    def start_of_day(d: date) -> datetime:
        """
        Devuelve el inicio del día (00:00:00) en timezone local.
        """
        return datetime(d.year, d.month, d.day, 0, 0, 0)

    @staticmethod
    def end_of_day(d: date) -> datetime:
        """
        Devuelve el final del día (23:59:59) en timezone local.
        """
        return datetime(d.year, d.month, d.day, 23, 59, 59)

    @staticmethod
    def week_range(reference: date) -> tuple[date, date]:
        """
        Rango de semana (lunes a domingo) para una fecha dada.
        """
        start = reference - timedelta(days=reference.weekday())
        end = start + timedelta(days=6)
        return start, end

    @staticmethod
    def month_range(reference: date) -> tuple[date, date]:
        """
        Rango de mes (primer día al último día) para una fecha dada.
        """
        start = date(reference.year, reference.month, 1)
        if reference.month == 12:
            next_month = date(reference.year + 1, 1, 1)
        else:
            next_month = date(reference.year, reference.month + 1, 1)
        end = next_month - timedelta(days=1)
        return start, end

    @staticmethod
    def year_range(reference: date) -> tuple[date, date]:
        """
        Rango de año (1 enero a 31 diciembre).
        """
        return date(reference.year, 1, 1), date(reference.year, 12, 31)