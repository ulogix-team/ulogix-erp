<img src="https://raw.githubusercontent.com/ulogix-team/assets/main/banners/header-dark.svg" width="100%"/>

<img src="https://raw.githubusercontent.com/ulogix-team/assets/main/dividers/divider-dark.svg" width="100%"/>

<p align="center">
  <img src="https://raw.githubusercontent.com/ulogix-team/assets/main/logos/ulogix-icon-transparent-dark.svg" height="58" alt="ULogix"/>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/ERP-Streamlit_%2B_Odoo-000000?style=flat-square" alt="ERP"/>
  &nbsp;
  <img src="https://img.shields.io/badge/UNS-Coreflux_MQTT-000000?style=flat-square" alt="UNS MQTT"/>
  &nbsp;
  <img src="https://img.shields.io/badge/QA-17%2F17-000000?style=flat-square" alt="QA"/>
  &nbsp;
  <img src="https://img.shields.io/badge/CAPEX-COP_9.166B-000000?style=flat-square" alt="CAPEX"/>
  &nbsp;
  <img src="https://img.shields.io/badge/VPN-COP_11.032B-000000?style=flat-square" alt="VPN"/>
</p>

# ULogix · Suite Fontibón v4 — KOF / INDEGA

ERP de planeación y ejecución para la planta Coca-Cola FEMSA Fontibón (Bogotá),
colgado del **UNS FEMSA** e integrado con **Odoo** (XML-RPC) y **Google Sheets**
(cuenta de servicio): pronóstico sobre los **datos reales KOF 2021T1–2026T1** →
escenarios → inventario/MRP → órdenes de compra → producción vía UNS →
finanzas del retrofit (ROI/VPN/TIR).

**Modelo de negocio (retrofit brownfield de las 3 líneas existentes):**
+11% throughput · OEE base L1/L2/L3 77,12%/76,50%/75,37% → fase 1 con
**+5% relativo exacto por línea** (meta aspiracional ≥86% separada) ·
+5% flujo de caja · encajonadora custom L1 · GANTRY ABB compartido L1-L2 ·
robot ABB para garrafones L3 · llenadoras KRONES usadas L1/L2 · Variopac
usada L2 · gemelos digitales, SCADA, MES/UNS y ERP/Odoo.

<img src="https://raw.githubusercontent.com/ulogix-team/assets/main/dividers/divider-section-dark.svg" width="100%"/>

## Arquitectura

```text
 Ignition 8.1 (OPC-UA) ──► Node-RED ──► MQTT · UNS  FEMSA/Linea1..3/...
        ▲                                  │   MES/KPI/#  MES/Maintance/#  Process/#
 Tecnomatix Plant Simulation               ▼
 (gemelos digitales)                 MIDDLEWARE Ulogix ────────► Odoo API (XML-RPC)
                                       │        ▲ publica         productos·BOM·POs
                                       ▼        │ FEMSA/…/ERP/#   (tools/bootstrap_odoo.py)
                                  SQLite ERP    │ (retained)
                     pronosticos · plan_compras · inventario_politicas ·
                     po_tracking · eventos_produccion · kpi_uns
                                       │
                                       ▼
                    DASHBOARD Streamlit ◄──► Google Sheets (libro en Drive)
                    10 páginas               Modelo_FEMSA_Ulogix_2026 (repo aparte)
```

Regla de red del stack: fuera de Docker, conectarse por la **IP LAN del host**
(no `localhost` ni hostnames de servicios Docker).

## Trazabilidad del uso de IA

El proyecto utiliza asistencia de inteligencia artificial para análisis,
documentación y revisión de código. Las decisiones de ingeniería, cifras,
validaciones y publicaciones son revisadas por el equipo humano. Las herramientas
de IA no figuran como autoras, coautoras ni colaboradoras de los commits.

## Arranque

```bash
docker compose -f docker-compose.dashboard.yml up -d --build
# dashboard: http://localhost:8501   ·   middleware: servicio aparte con la BD en volumen
```

Sin Docker: `pip install -r requirements.txt` →
`streamlit run app/Inicio.py` + `python middleware/run_middleware.py`.

## Configuración (`.env`)

Copia `.env.example` a `.env` y completa `MQTT_HOST`, `ODOO_URL`/`ODOO_DB`/
`ODOO_USER`/`ODOO_API_KEY` y `SHEETS_SPREADSHEET_ID` con tus valores reales —
**nunca** los pegues en archivos versionados (repo público). La credencial de
Google (`config/google_service_account.json`) tampoco se versiona.

| Variable | Qué poner |
|---|---|
| `ODOO_USER` | tu **correo de login** en tu instancia Odoo |
| `SHEETS_SPREADSHEET_ID` | el ID del libro una vez subido a Drive y compartido |

Guía completa paso a paso: **`docs/INTEGRACION_APIS.md`**.

## Páginas

1. **Pronóstico** — v4 sobre datos reales: HW amortiguado (m=4), garrafón con
   combinación **óptima Bates-Granger** (MAPE 4,58% → **2,11%**), diferenciación
   P1/P2 (deriva de mezcla retornable + perfil de formato), históricos
   2021-2026 + bandas MC N=10.000, validación un-paso 2026T1.
2. **Escenarios** — 6 presets del script 13 con **elasticidades diferenciadas
   por producto** + editor personalizado por P1/P2/P3; al activar, la demanda
   queda en la BD ERP.
3. **Inventario** — política (s,Q) Monte Carlo + MRP; política y plan de
   compras persisten en el ERP.
4. **Órdenes (Odoo)** — genera POs de insumos y MOs ligadas a BOM desde el
   plan (dry-run o real), con idempotencia por referencia.
5. **Producción (UNS)** — estado vivo del middleware, KPIs MES por línea,
   publicador de prueba y contrato completo del UNS.
6. **Finanzas** — P&L del libro de producción + **caso de negocio conectado
   a la demanda** (base vs escenario activo, sin supuesto de crecimiento —
   sigue siempre la demanda que manda el ERP): CAPEX $9.166M COP · EBITDA
   incremental $9.406M (12 m op.) · **VPN $11.032M · TIR 78,2% E.A. · ROI
   226,7% · payback 22/25 m** + sincronización al libro de Drive.
7. **Pruebas** — diagnóstico en vivo: eco MQTT al UNS, Odoo
   (authenticate + PO de prueba), Sheets (escribir/releer + leer Parámetros).
8. **Base de datos** — navegador de las 10 tablas ERP con exportación CSV y
   tablero de KPIs del UNS.
9. **Ventas y Facturación** — reparte lotes terminados entre clientes, crea
   `sale.order`, entrega y factura en Odoo.
10. **RRHH** — roster individual (hoja `RRHH`), reconciliado contra el
    agregado por rol que gobierna la nómina del caso de negocio.

## UNS

El árbol vive en `config/uns_femsa.yaml`. El middleware se suscribe a KPI y
mantenimiento por línea y planta, y a `FEMSA/LineaX/ERP/AvailableQuantity`.
El ERP **publica retained** en `FEMSA/LineaX/ERP/…` una sola MO activa por
línea; el MES escribe `AvailableQuantity` como avance absoluto. `GoodCount`
continúa únicamente como contrato legado de prueba. Simulador:
`python tools/simulador_produccion.py` (UNS) · `--legacy` (contrato v1) ·
`--offline` (sin broker).

## Odoo desde cero

```bash
python tools/bootstrap_odoo.py --dry   # plan
python tools/bootstrap_odoo.py         # apps + P1/P2/P3 con EAN-13 + 16 componentes
                                       # + proveedores/tarifas + listas de materiales
```

## Verificación

```bash
python tools/verificacion.py   # 17 pasos: datos, modelos, MRP, Odoo, MQTT,
                               # Sheets, UNS, ERP, Tiempos/OEE (auditados:
                               # U>1 con 2 turnos -> 3er turno), ROI/VPN/TIR,
                               # produccion (orden activa), inventario en vivo
```

## Repositorio hermano

[`ulogix-data-finance`](https://github.com/ulogix-team/ulogix-data-finance)
publica **`Modelo_FEMSA_Ulogix_2026.xlsx`** y documenta la arquitectura,
gobernanza, CAPEX, APU, licencias, tiempos, OEE y viabilidad. Google Sheets
continúa siendo la fuente viva; el repositorio conserva snapshots auditables.

## Documentación

- [Reporte técnico-ejecutivo para presentación](docs/REPORTE_PRESENTACION_ULOGIX_FONTIBON.md)
- [Índice técnico](docs/README.md)
- [Integración de APIs](docs/INTEGRACION_APIS.md)
- [Pipeline de demanda](docs/PIPELINE_DEMANDA.md)
- [Referencias](docs/REFERENCIAS.md)

<img src="https://raw.githubusercontent.com/ulogix-team/assets/main/banners/footer-dark.svg" width="100%"/>
