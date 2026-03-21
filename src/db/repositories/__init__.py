"""
repositories package
--------------------
Capa de persistencia (queries y escritura) aislada del resto del sistema.

Regla:
- Ningún handler de Telegram debe escribir SQL directo.
- Todo acceso a SQLite se hace vía repositorios.
"""
