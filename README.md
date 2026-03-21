# Telefinance

**Telefinance** es un sistema unificado para la operación financiera y logística de un negocio de servicios técnicos.

Su objetivo es centralizar en una sola plataforma:

- 📸 **Captura de gastos de proveedores** desde fotos de facturas usando OCR con OpenAI
- 🧾 **Emisión de recibos de servicio** desde Telegram con PDF listo para compartir
- 🗓️ **Coordinación de trabajos, mantenimientos y pedidos**
- 🔔 **Recordatorios automáticos** por agenda operativa
- 📊 **Dashboard financiero en Streamlit** para consulta y análisis

---

## Resumen funcional

Telefinance integra tres capas principales:

### 1. Bot de Telegram
Permite operar el sistema desde chat:

- crear recibos de servicio
- registrar facturas de proveedores por foto
- agendar trabajos
- programar mantenimientos
- registrar pedidos de piezas
- generar PDFs ejecutivos
- consultar el dashboard

### 2. Base de datos SQLite
Centraliza toda la persistencia operativa y financiera en:

- gastos
- ingresos
- borradores conversacionales
- agenda de trabajos
- mantenimientos
- pedidos

### 3. Dashboard Streamlit
Visualiza la información financiera en modo solo lectura:

- gastos
- ingresos
- neto
- series temporales
- rankings
- exportación CSV

---

## Estado actual del proyecto

### Bot Telegram
El bot ya opera con un **menú principal numérico** y flujo tipo empresa.

Menú principal actual:

- `1️⃣` Crear recibo de servicio
- `2️⃣` Coordinador de trabajo
- `3️⃣` Dashboard
- `4️⃣` PDF resumen proveedores
- `5️⃣` PDF resumen servicios
- `6️⃣` Limpiar mensajes del bot
- `7️⃣` Ayuda
- `0️⃣` Cancelar / volver al menú principal durante un flujo activo

### Recibo de servicio
El wizard de recibo ya permite:

1. Capturar cliente
2. Definir fecha
3. Agregar uno o varios conceptos
4. Calcular total
5. Generar PDF
6. Guardar en SQLite
7. Enviar el PDF por Telegram

### OCR de facturas de proveedor
Cuando llega una foto al bot fuera de un flujo de mantenimiento:

1. La imagen se descarga en `data/inbox/`
2. Se procesa con OpenAI Vision
3. Se extraen datos estructurados
4. Se guarda el resultado en SQLite
5. Se responde con un resumen al usuario

### Coordinador de trabajo
El submenú del coordinador ya contempla:

- 📌 Agendar trabajo
- 🧰 Agendar mantenimiento
- 📋 Resumen de trabajos agendados
- 🗓️ Resumen de mantenimientos programados
- 📦 Registrar pedido de pieza
- 🧾 Resumen de pedidos

### Recordatorios automáticos
Actualmente el sistema tiene recordatorios para:

- **Pedidos**
  - primer recordatorio a 7 días
  - luego cada 2 días mientras siga pendiente
  - control anti-spam diario por `last_reminded_at`

- **Mantenimientos**
  - recordatorio cuando llega `next_due_dt`
  - control anti-spam diario por `last_reminded_at`
  - limpieza automática por TTL después del recordatorio

- **Trabajos agendados**
  - recordatorio cuando el trabajo está próximo a ocurrir
  - incluye resumen completo y Waze
  - limpieza automática por TTL después de la hora programada

---

## Arquitectura del sistema

Telefinance está organizado como un proyecto modular.

### Capas principales

#### `src/core`
Contiene utilidades compartidas del sistema:

- configuración
- logger
- paths
- utilidades de tiempo
- errores base

#### `src/db`
Contiene la capa de persistencia:

- conexión SQLite
- migraciones
- schema
- repositorios

#### `src/services`
Contiene la lógica de negocio reutilizable:

- OCR
- construcción de HTML para facturas
- renderizado de PDF
- analíticas
- reportes PDF ejecutivos
- consecutivos

#### `src/telegram_bot`
Contiene la lógica del bot:

- arranque del bot
- handlers
- estado del wizard
- routers de texto y foto
- recordatorios

#### `streamlit_app`
Contiene el dashboard financiero.

---

## Estructura del proyecto

```text
telefinance/
├── assets/
│   ├── factura.css
│   ├── logo_factura.png
│   └── report.css
├── data/
│   ├── inbox/
│   ├── exports/
│   ├── samples/
│   └── telefinance.db
├── logs/
│   └── telefinance.log
├── output/
│   ├── invoices/
│   └── reports/
├── streamlit_app/
│   └── app.py
├── src/
│   ├── cli/
│   │   ├── init_db.py
│   │   ├── run_bot.py
│   │   └── run_streamlit.py
│   ├── core/
│   ├── db/
│   │   ├── connection.py
│   │   ├── migrations.py
│   │   ├── schema.py
│   │   └── repositories/
│   ├── services/
│   └── telegram_bot/
├── tests/
├── README.md
└── requirements.txt


--------------------------------------------------------------------------------------------------------------------------------

.
├── assets
│   ├── factura.css
│   ├── logo_factura.png
│   ├── README.md
│   └── report.css
├── data
│   ├── exports
│   │   └── README.md
│   ├── inbox
│   │   ├── maintenance_8405049743_20260303_200414_1.jpg
│   │   ├── maintenance_8405049743_20260303_200435_2.jpg
│   │   ├── maintenance_8405049743_20260303_202850_1.jpg
│   │   ├── maintenance_8405049743_20260304_113258_1.jpg
│   │   ├── maintenance_8405049743_20260304_113310_2.jpg
│   │   ├── vendor_8405049743_20260213_165426.jpg
│   │   ├── vendor_8405049743_20260213_170204.jpg
│   │   ├── vendor_8405049743_20260213_171537.jpg
│   │   ├── vendor_8405049743_20260213_172114.jpg
│   │   ├── vendor_8405049743_20260216_193633.jpg
│   │   ├── vendor_8405049743_20260303_195942.jpg
│   │   └── vendor_896625231_20260216_204457.jpg
│   ├── samples
│   │   ├── factura.jpg
│   │   └── README.md
│   └── telefinance.db
├── logs
│   └── telefinance.log
├── Makefile
├── output
│   ├── invoices
│   │   ├── recibo_10.debug.html
│   │   ├── recibo_10.pdf
│   │   ├── recibo_11.debug.html
│   │   ├── recibo_11.pdf
│   │   ├── recibo_1.debug.html
│   │   ├── recibo_1.pdf
│   │   ├── recibo_2.debug.html
│   │   ├── recibo_2.pdf
│   │   ├── recibo_3.debug.html
│   │   ├── recibo_3.pdf
│   │   ├── recibo_4.debug.html
│   │   ├── recibo_4.pdf
│   │   ├── recibo_5.debug.html
│   │   ├── recibo_5.pdf
│   │   ├── recibo_6.debug.html
│   │   ├── recibo_6.pdf
│   │   ├── recibo_7.debug.html
│   │   ├── recibo_7.pdf
│   │   ├── recibo_8.debug.html
│   │   ├── recibo_8.pdf
│   │   ├── recibo_9.debug.html
│   │   └── recibo_9.pdf
│   └── reports
│       ├── _assets
│       │   ├── service_daily_2026-02-16.png
│       │   ├── service_daily_2026-03-04.png
│       │   ├── service_daily_2026-03-06.png
│       │   ├── service_top_clients_2026-02-16.png
│       │   ├── service_top_clients_2026-03-04.png
│       │   ├── service_top_clients_2026-03-06.png
│       │   ├── service_top_items_2026-02-16.png
│       │   ├── service_top_items_2026-03-04.png
│       │   ├── service_top_items_2026-03-06.png
│       │   ├── vendor_daily_2026-02-16.png
│       │   ├── vendor_daily_2026-03-03.png
│       │   ├── vendor_daily_2026-03-04.png
│       │   ├── vendor_daily_2026-03-06.png
│       │   ├── vendor_top_items_2026-02-16.png
│       │   ├── vendor_top_items_2026-03-03.png
│       │   ├── vendor_top_items_2026-03-04.png
│       │   ├── vendor_top_items_2026-03-06.png
│       │   ├── vendor_top_vendors_2026-02-16.png
│       │   ├── vendor_top_vendors_2026-03-03.png
│       │   ├── vendor_top_vendors_2026-03-04.png
│       │   └── vendor_top_vendors_2026-03-06.png
│       ├── resumen_proveedores_2026-02-16.pdf
│       ├── resumen_proveedores_20260216.pdf
│       ├── resumen_proveedores_2026-03-03.pdf
│       ├── resumen_proveedores_2026-03-04.debug.html
│       ├── resumen_proveedores_2026-03-04.pdf
│       ├── resumen_proveedores_2026-03-06.debug.html
│       ├── resumen_proveedores_2026-03-06.pdf
│       ├── resumen_servicios_2026-02-16.pdf
│       ├── resumen_servicios_20260216.pdf
│       ├── resumen_servicios_2026-03-04.pdf
│       ├── resumen_servicios_2026-03-06.debug.html
│       └── resumen_servicios_2026-03-06.pdf
├── README.md
├── requirements.txt
├── src
│   ├── cli
│   │   ├── init_db.py
│   │   ├── __init__.py
│   │   ├── __pycache__
│   │   │   ├── __init__.cpython-311.pyc
│   │   │   ├── init_db.cpython-311.pyc
│   │   │   ├── run_bot.cpython-311.pyc
│   │   │   └── run_streamlit.cpython-311.pyc
│   │   ├── run_bot.py
│   │   └── run_streamlit.py
│   ├── core
│   │   ├── config.py
│   │   ├── errors.py
│   │   ├── __init__.py
│   │   ├── logger.py
│   │   ├── paths.py
│   │   ├── __pycache__
│   │   │   ├── config.cpython-311.pyc
│   │   │   ├── errors.cpython-311.pyc
│   │   │   ├── __init__.cpython-311.pyc
│   │   │   ├── logger.cpython-311.pyc
│   │   │   ├── paths.cpython-311.pyc
│   │   │   └── utils_time.cpython-311.pyc
│   │   └── utils_time.py
│   ├── db
│   │   ├── connection.py
│   │   ├── db_lock.py
│   │   ├── __init__.py
│   │   ├── migrations.py
│   │   ├── __pycache__
│   │   │   ├── connection.cpython-311.pyc
│   │   │   ├── db_lock.cpython-311.pyc
│   │   │   ├── __init__.cpython-311.pyc
│   │   │   ├── migrations.cpython-311.pyc
│   │   │   └── schema.cpython-311.pyc
│   │   ├── repositories
│   │   │   ├── analytics_repo.py
│   │   │   ├── drafts_repo.py
│   │   │   ├── __init__.py
│   │   │   ├── maintenance_repo.py
│   │   │   ├── ordered_parts_repo.py
│   │   │   ├── __pycache__
│   │   │   ├── service_invoices_repo.py
│   │   │   ├── supplier_invoices_repo.py
│   │   │   ├── vendor_invoices_repo.py
│   │   │   └── work_jobs_repo.py
│   │   └── schema.py
│   ├── domain
│   │   ├── enums.py
│   │   ├── __init__.py
│   │   └── models.py
│   ├── __init__.py
│   ├── main.py
│   ├── __pycache__
│   │   └── __init__.cpython-311.pyc
│   ├── services
│   │   ├── analytics.py
│   │   ├── consecutivo.py
│   │   ├── __init__.py
│   │   ├── invoice_builder.py
│   │   ├── invoice_parser.py
│   │   ├── ocr_openai.py
│   │   ├── pdf_renderer.py
│   │   ├── __pycache__
│   │   │   ├── analytics.cpython-311.pyc
│   │   │   ├── consecutivo.cpython-311.pyc
│   │   │   ├── __init__.cpython-311.pyc
│   │   │   ├── invoice_builder.cpython-311.pyc
│   │   │   ├── invoice_parser.cpython-311.pyc
│   │   │   ├── ocr_openai.cpython-311.pyc
│   │   │   ├── pdf_renderer.cpython-311.pyc
│   │   │   └── report_pdf.cpython-311.pyc
│   │   └── report_pdf.py
│   └── telegram_bot
│       ├── bot.py
│       ├── handlers
│       │   ├── admin.py
│       │   ├── __init__.py
│       │   ├── __pycache__
│       │   ├── reminders.py
│       │   ├── service_wizard.py
│       │   ├── start.py
│       │   ├── supplier_invoice_photo.py
│       │   └── vendor_invoice_photo.py
│       ├── __init__.py
│       ├── keyboards
│       │   ├── __init__.py
│       │   └── menus.py
│       ├── __pycache__
│       │   ├── bot.cpython-311.pyc
│       │   └── __init__.cpython-311.pyc
│       └── state
│           ├── __init__.py
│           ├── __pycache__
│           └── wizard_state.py
├── streamlit_app
│   └── app.py
├── tests
│   ├── __init__.py
│   ├── test_analytics.py
│   ├── test_db_schema.py
│   └── test_parser.py
├── tree.txt
├── venv
│   ├── bin
│   │   ├── activate
│   │   ├── activate.csh
│   │   ├── activate.fish
│   │   ├── Activate.ps1
│   │   ├── choreo_diagnose
│   │   ├── choreo_get_chrome
│   │   ├── coverage
│   │   ├── coverage3
│   │   ├── coverage-3.11
│   │   ├── distro
│   │   ├── dotenv
│   │   ├── f2py
│   │   ├── fonttools
│   │   ├── httpx
│   │   ├── jsonschema
│   │   ├── kaleido_get_chrome
│   │   ├── kaleido_mocker
│   │   ├── markdown-it
│   │   ├── normalizer
│   │   ├── numpy-config
│   │   ├── openai
│   │   ├── pip
│   │   ├── pip3
│   │   ├── pip3.11
│   │   ├── plotly_get_chrome
│   │   ├── pyftmerge
│   │   ├── pyftsubset
│   │   ├── pygmentize
│   │   ├── py.test
│   │   ├── pytest
│   │   ├── python -> python3
│   │   ├── python3 -> /usr/bin/python3
│   │   ├── python3.11 -> python3
│   │   ├── streamlit
│   │   ├── streamlit.cmd
│   │   ├── tqdm
│   │   ├── ttx
│   │   ├── watchmedo
│   │   └── weasyprint
│   ├── etc
│   │   └── jupyter
│   │       └── nbconfig
│   ├── include
│   │   └── python3.11
│   ├── lib
│   │   └── python3.11
│   │       └── site-packages
│   ├── lib64 -> lib
│   ├── pyvenv.cfg
│   └── share
│       ├── jupyter
│       │   ├── labextensions
│       │   └── nbextensions
│       └── man
│           └── man1
└── venv_broken_20260216_183809
    ├── bin
    │   ├── activate
    │   ├── activate.csh
    │   ├── activate.fish
    │   ├── Activate.ps1
    │   ├── coverage
    │   ├── coverage3
    │   ├── coverage-3.11
    │   ├── distro
    │   ├── dotenv
    │   ├── f2py
    │   ├── fonttools
    │   ├── httpx
    │   ├── jsonschema
    │   ├── markdown-it
    │   ├── normalizer
    │   ├── numpy-config
    │   ├── openai
    │   ├── pip
    │   ├── pip3
    │   ├── pip3.11
    │   ├── pyftmerge
    │   ├── pyftsubset
    │   ├── pygmentize
    │   ├── py.test
    │   ├── pytest
    │   ├── python -> python3
    │   ├── python3 -> /usr/bin/python3
    │   ├── python3.11 -> python3
    │   ├── streamlit
    │   ├── streamlit.cmd
    │   ├── tqdm
    │   ├── ttx
    │   ├── watchmedo
    │   └── weasyprint
    ├── etc
    │   └── jupyter
    │       └── nbconfig
    ├── include
    │   └── python3.11
    ├── lib
    │   └── python3.11
    │       └── site-packages
    ├── lib64 -> lib
    ├── pyvenv.cfg
    └── share
        ├── jupyter
        │   └── nbextensions
        └── man
            └── man1

66 directories, 236 files

--------------------------------------------------------------------------------------------------------------------------------

Componentes clave
1. Facturas de proveedor

Flujo actual:

el usuario envía una foto

el bot decide si esa foto corresponde a:

mantenimiento

factura proveedor

si es factura proveedor:

ejecuta OCR

guarda cabecera

guarda detalle

responde con resumen

------------------------------------------------------------
2. Recibos de servicio

Flujo actual:

wizard por chat

armado de conceptos

generación de HTML

renderizado PDF con WeasyPrint

persistencia en SQLite

envío inmediato por Telegram

-----------------------------------------------------------
3. Coordinador de trabajo

Permite registrar:

trabajos próximos

mantenimientos periódicos

pedidos de piezas

y luego usar esa data para:

recordatorios

resúmenes operativos

trazabilidad del trabajo
-----------------------------------------------------------
4. Dashboard financiero

Permite visualizar:

gastos por proveedores

ingresos por servicios

neto

rankings

series diarias

exportación CSV

----------------------------------------------------------
5. PDFs ejecutivos

Telefinance puede generar reportes PDF corporativos para:

proveedores / gastos

servicios / ingresos

Estos PDFs incluyen:

logo corporativo

KPIs

rankings

charts

estructura lista para compartir

----------------------------------------------------------
Base de datos

La base de datos activa es SQLite.

Ruta por defecto:

data/telefinance.db
Tablas principales
vendor_invoices

Cabecera de gastos de proveedores.

service_invoices

Cabecera de recibos / ingresos por servicios.

invoice_items

Detalle de conceptos asociados a facturas o recibos.

drafts

Estado del wizard por chat para no perder el flujo conversacional.

work_jobs

Agenda de trabajos próximos.

maintenance_plans

Planes de mantenimiento con vencimiento futuro y recordatorio.

ordered_parts

Pedidos de piezas con control de recordatorio e instalación.

-----------------------------
Migraciones

El sistema usa migraciones seguras e idempotentes.

Estrategia actual

CREATE TABLE IF NOT EXISTS

ALTER TABLE ... ADD COLUMN ... solo si falta la columna

sin borrado automático de datos

sin cambios destructivos de tipo

Principios

no romper datos existentes

permitir evolución incremental del schema

mantener compatibilidad con entornos ya usados

------------------------------------

Concurrencia y robustez SQLite

Telefinance fue ajustado para convivir correctamente con:

Telegram Bot

Streamlit

recordatorios automáticos
------------------------------------

Medidas implementadas
WAL

La base se abre en modo:

PRAGMA journal_mode=WAL;

para permitir lectura concurrente con escritura.

busy_timeout

Se usa timeout y espera de locks antes de fallar.
-------------------------------------

Single writer lock

Las escrituras del bot pasan por:

DBWriteLock

para evitar colisiones de escritura.

--------------------------------------
Regla crítica

Nunca se debe mantener una conexión SQLite abierta durante un await.

Patrón recomendado:

leer rápido

cerrar conexión

hacer await

volver a abrir conexión para escribir bajo lock

-----------------------------------------------------------
-----------------------------------------------------------

OCR con OpenAI

El OCR está encapsulado en un módulo de servicio.

Responsabilidades

tomar una imagen local

enviarla a OpenAI Vision

obtener un JSON estructurado

normalizar salida

devolver datos listos para persistencia

Campos esperados

La extracción estructurada devuelve:

vendor_name

vendor_id

invoice_number

invoice_date

currency

total

items

raw_text

Regla de activación

La IA solo se activa cuando llega una imagen al flujo de proveedor.

-----------------------------------------------------------
-----------------------------------------------------------

PDFs

El sistema genera dos tipos principales de PDF.

1. Recibos de servicio

Generados por el wizard del bot.

Salida:

output/invoices/
2. Reportes ejecutivos

Generados desde el menú principal del bot.

Salida:

output/reports/

También puede generar:

assets temporales PNG

HTML debug de apoyo

-----------------------------------------------------------
-----------------------------------------------------------

Dashboard Streamlit

El dashboard es de lectura y está diseñado para visualizar los datos del sistema sin modificar la DB.

Módulos visibles

Gastos

Ingresos

Neto

Funciones

KPIs por rango

rankings

gráficos diarios

exportación CSV

diagnóstico de DB

-----------------------------------------------------------
-----------------------------------------------------------

Instalación
Requisitos

Python 3.11+

SQLite 3.x

Token de Telegram

API Key de OpenAI

Dependencias importantes

Para recordatorios automáticos con JobQueue:

pip install "python-telegram-bot[job-queue]"
Preparación del entorno
cd ~/Desktop/telefinance
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
Variables de entorno

Crear un archivo .env con los valores necesarios.

Ejemplo mínimo:

TELEGRAM_BOT_TOKEN=TU_TOKEN_AQUI
OPENAI_API_KEY=TU_API_KEY_AQUI
TZ=America/Panama

Opcionalmente pueden existir otras variables como:

TELEFINANCE_DASHBOARD_URL=http://localhost:8501
LOG_LEVEL=INFO
Inicialización de la base de datos
python -m src.cli.init_db

Esto:

detecta el root del proyecto

resuelve la DB activa

aplica schema

aplica migraciones

Ejecución del bot
python -m src.cli.run_bot

Este runner:

detecta el root real del proyecto

inicializa logging

construye la app de Telegram

aplica schema si hace falta

arranca en polling

Ejecución del dashboard
python -m src.cli.run_streamlit

Este runner:

fija el CWD correcto

exporta PYTHONPATH

ejecuta Streamlit como proceso limpio

evita conflictos con st.set_page_config()

-----------------------------------------------------------
-----------------------------------------------------------

Menú principal del bot
Menú principal

1️⃣ Crear recibo de servicio

2️⃣ Coordinador de trabajo

3️⃣ Dashboard (Ingresos/Gastos)

4️⃣ PDF resumen proveedores

5️⃣ PDF resumen servicios

6️⃣ Limpiar mensajes del bot

7️⃣ Ayuda

Durante un flujo activo:

0️⃣ cancelar y volver al menú principal

Submenú coordinador

1️⃣ Agendar trabajo

2️⃣ Agendar mantenimiento

3️⃣ Resumen de trabajos

4️⃣ Resumen de mantenimientos

5️⃣ Registrar pedido de pieza

6️⃣ Resumen de pedidos

0️⃣ Volver al menú principal


---------------------------------------------------------------
---------------------------------------------------------------

Dispatch inteligente de fotos

El sistema diferencia entre fotos de mantenimiento y fotos de proveedor.

Regla

Si el draft activo indica que el wizard está esperando fotos de mantenimiento:

la foto se guarda como parte del mantenimiento

Si no:

la foto se procesa como factura proveedor usando OCR

Esto evita cruces de flujo y reduce errores operativos.

----------------------------------------------------------

Recordatorios automáticos
Pedidos

Se notifican cuando:

next_remind_dt <= now

Luego el sistema:

envía el mensaje

marca last_reminded_at

reprograma next_remind_dt a +2 días

----------------------------------------------------------

Mantenimientos

Se notifican cuando:

next_due_dt <= now

Luego el sistema:

envía el recordatorio

marca last_reminded_at

elimina el mantenimiento por TTL 12 horas después

----------------------------------------------------------

Trabajos agendados

Se notifican cuando el trabajo entra en ventana próxima de ejecución.

Además:

incluye resumen completo

incluye link de Waze

limpia automáticamente trabajos vencidos por TTL

----------------------------------------------------------

Logging

Telefinance usa loguru.

La salida principal se guarda en:

logs/telefinance.log

El logger se inicializa desde los runners CLI y desde el arranque del bot.

----------------------------------------------------------

Tests

Ejecutar:

pytest

Los tests actuales cubren principalmente:

parser

analytics

schema DB

-----------------------------------------------------------

Estado técnico del upgrade

Durante la actualización reciente del proyecto se reforzaron estas áreas:

conexión SQLite más robusta

uso de WAL

control de locks

runners CLI más sólidos

OCR desacoplado

dashboard en modo lectura

handlers mejor organizados

recordatorios más claros

documentación más consistente

----------------------------------------------------------
Notas operativas
Assets críticos

Estos archivos deben existir:

assets/factura.css
assets/logo_factura.png
assets/report.css

----------------------------------------------------------
Carpeta de entrada OCR

Las imágenes proveedor y mantenimiento se descargan en:

data/inbox/
Salidas PDF

Recibos:

output/invoices/

Reportes:

output/reports/

-----------------------------------------------------------
Roadmap sugerido

Posibles siguientes pasos del proyecto:

separar completamente items de proveedor y servicio en tablas dedicadas

consolidar eliminación definitiva de módulos legacy supplier_*

mejorar panel administrativo web

agregar backup automático de SQLite

exportación contable más formal

soporte multiempresa

métricas avanzadas en dashboard

autenticación y perfiles de operador

------------------------------------------------------------

Convenciones del proyecto

Telefinance sigue estas reglas de desarrollo:

cambios mínimos y seguros

nada de romper datos existentes

migraciones incrementales

código prolijo y documentado

rutas robustas sin depender del cwd

evitar mantener SQLite abierto durante await

preferir lectura readonly cuando corresponda
