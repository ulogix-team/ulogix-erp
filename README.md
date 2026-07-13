# Ulogix · Suite Fontibón v4 — KOF / INDEGA

ERP de planeación y ejecución para la planta Coca-Cola FEMSA Fontibón (Bogotá),
colgado del **UNS FEMSA** e integrado con **Odoo** (XML-RPC) y **Google Sheets**
(cuenta de servicio): pronóstico sobre los **datos reales KOF 2021T1–2026T1** →
escenarios → inventario/MRP → órdenes de compra → producción vía UNS →
finanzas del retrofit (ROI/VPN/TIR).

**Modelo de negocio (retrofit brownfield de las 3 líneas existentes):**
+11% throughput · OEE 83% → ≥86% (fase 1: **+5% relativo justificado**) ·
+5% flujo de caja · celdas robóticas de paletizado (BOM real USD 239.889) ·
modernización de llenadoras únicamente · gemelo digital por equipo ·
trazabilidad MES/Cloud.

---

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
                    8 páginas                Modelo_FEMSA_Ulogix_2026 (repo aparte)
```

Regla de red del stack: fuera de Docker, conectarse por la **IP LAN del host**
(no `localhost` ni hostnames de servicios Docker).

## Arranque

```bash
docker compose -f docker-compose.dashboard.yml up -d --build
# dashboard: http://localhost:8501   ·   middleware: servicio aparte con la BD en volumen
```

Sin Docker: `pip install -r requirements.txt` →
`streamlit run app/Inicio.py` + `python middleware/run_middleware.py`.

## Configuración (`.env`)

Ya trae el broker (`100.123.104.31`), la credencial de Google
(`config/google_service_account.json`) y la API key de Odoo. Pendientes tuyos:

| Variable | Qué poner |
|---|---|
| `ODOO_USER` | tu **correo de login** en ulogix-admin.odoo.com |
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
4. **Órdenes (Odoo)** — genera POs desde el plan (dry-run o real).
5. **Producción (UNS)** — estado vivo del middleware, KPIs MES por línea,
   publicador de prueba y contrato completo del UNS.
6. **Finanzas** — P&L del libro de producción + **caso de negocio conectado
   a la demanda** (base vs escenario activo): CAPEX $12.188M COP · EBITDA
   incremental $13.182M (12 m op.) · **VPN $16.661M · TIR 85,7% E.A. · ROI
   253,1% · payback 21/24 m** + sincronización al libro de Drive.
7. **Pruebas** — diagnóstico en vivo: eco MQTT al UNS, Odoo
   (authenticate + PO de prueba), Sheets (escribir/releer + leer Parámetros).
8. **Base de datos** — navegador de las 7 tablas ERP con exportación CSV y
   tablero de KPIs del UNS.

## UNS

El árbol es tu YAML (`config/uns_femsa.yaml`, intacto). El middleware se
suscribe a `FEMSA/+/MES/KPI/#`, `FEMSA/+/MES/Maintance/#`, `FEMSA/+/Process/#`
(convención de conteo: `GoodCount/Count/Produccion/value`) y **publica retained**
la rama `FEMSA/LineaX/ERP/…` con la PO activa. Simulador:
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
python tools/verificacion.py   # 13 pasos: datos, modelos, MRP, Odoo, MQTT,
                               # Sheets, UNS, ERP, Tiempos/OEE (auditados:
                               # U>1 con 2 turnos -> 3er turno), ROI/VPN/TIR
```

## Repositorio hermano

`femsa-modelo-financiero/` genera **`Modelo_FEMSA_Ulogix_2026.xlsx`** (el libro
que se sube a Drive y se conecta por API): Parámetros, Tiempos, OEE base vs
+5%, CAPEX con BOM real de celdas, modelo financiero de 60 meses con fórmulas
vivas y las hojas que escribe la app.
