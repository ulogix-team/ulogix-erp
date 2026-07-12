# Ulogix Fontibón Suite — contexto del proyecto

> Claude Code lee este archivo automáticamente al iniciar sesión. Contiene todo
> lo que necesitas saber para trabajar en el repo sin re-explicar la
> arquitectura. **Responde siempre en español.**

## Qué es esto

ERP ligero + MES para la planta **Coca-Cola FEMSA / INDEGA Fontibón** (Bogotá).
Tres líneas: **L1** Coca-Cola 350 ml vidrio retornable, **L2** QuAtro 1.5 L PET,
**L3** garrafón 25 L retornable.

Flujo completo: pronóstico de demanda → escenarios → inventario (s,Q) / MRP →
órdenes de compra en Odoo → producción confirmada vía MQTT/UNS → estados
financieros conectados a la demanda.

**Repositorio hermano:** `../femsa-modelo-financiero` genera el libro Excel de 23
hojas que se conecta al ERP por la API de Google Sheets. Los dos repos comparten
**fuente única de verdad**: el generador del libro importa `CAPEX_FILAS`, `VIDAS`
de `core/finanzas_negocio.py` y las tablas de `core/tiempos_oee.py` de este repo.

## Arquitectura

```
 Ignition 8.1 (OPC-UA) → Node-RED → MQTT · UNS  FEMSA/Linea1..3/...
        ▲                             │  MES/KPI/#  MES/Maintance/#  Process/#
 Tecnomatix Plant Sim                 ▼
                              MIDDLEWARE Ulogix ────► Odoo API (XML-RPC)
                                │      ▲ publica retained FEMSA/…/ERP/#
                                ▼      │
                           SQLite ERP (8 tablas)
                                │
                                ▼
              DASHBOARD Streamlit ◄──► Google Sheets (libro en Drive)
```

**Regla de red:** fuera de Docker se usa la **IP LAN del host** (broker MQTT,
puerto `1883` — ver `MQTT_HOST` en `.env`, no versionado), nunca `localhost`
ni hostnames de servicios Docker. Dentro de docker-compose sí resuelven los
nombres de servicio.

## Estructura

| Ruta | Contenido |
|---|---|
| `app/Inicio.py` + `app/pages/1..9` | Dashboard Streamlit (9 páginas) |
| `app/ui/theme.py` | Tema, helpers (`datos_pronostico()`, `demanda_activa()`, `plotly_layout()`), supresión de warnings |
| `core/forecast.py` | Holt-Winters amortiguado + Bates-Granger óptimo + Monte Carlo |
| `core/escenarios.py` | 6 presets + escenario personalizado (elasticidades **por producto**) |
| `core/inventario.py` | Política (s,Q) Monte Carlo + MRP |
| `core/tiempos_oee.py` | Tiempos y OEE **documentales** (auditoría corregida) |
| `core/finanzas_negocio.py` | **Motor financiero demand-driven** + `CAPEX_FILAS` (fuente única) |
| `core/sensibilidad.py` | Tornado paramétrico |
| `integrations/uns.py` | Interpreta `config/uns_femsa.yaml` (63 tópicos) |
| `integrations/mqtt_middleware.py` | Suscribe UNS, cumple POs, publica rama ERP retained |
| `integrations/odoo_client.py` | XML-RPC; `LineaPedido(nombre, default_code, cantidad, precio_unitario)`; compras+fabricación+**ventas+facturación** (cliente y proveedor), todo idempotente por referencia |
| `integrations/sheets_client.py` | gspread + **fallback a Excel local** |
| `integrations/state_store.py` | SQLite WAL, 8 tablas ERP |
| `tools/verificacion.py` | **QA de 14 pasos — correr siempre antes de dar algo por bueno** |
| `tools/bootstrap_odoo.py` | Puebla Odoo desde cero (idempotente) |
| `tools/simulador_produccion.py` | Publica KPIs y GoodCount al UNS |

## Decisiones de diseño que NO se deben romper

1. **El ERP no gestiona OEE/TEEP.** Esos KPIs llegan **solo** por MQTT según el
   UNS (`FEMSA/+/MES/KPI/#`) → tabla `kpi_uns` → hoja `KPIs_UNS`. Las hojas
   `Tiempos` y `OEE_TEEP` del libro son **documentales** (referencia de
   ingeniería), no están conectadas.
2. **Rangos fijos en Sheets.** La app escribe `Demanda` y `DemandaEscenario` en
   `A4:F16` e `Inventarios` en `A4:I8` **posicionalmente** (`_escribir_rango()`),
   porque las hojas financieras referencian esas celdas con fórmulas. Un
   clear+append las rompería.
3. **Fuente única del CAPEX.** `CAPEX_FILAS` vive en `core/finanzas_negocio.py`;
   el generador del Excel la importa. No duplicar cifras.
4. **`t_ciclo_ideal` ≠ `t_ciclo`** y **takt ≠ tiempo de ciclo**. Errores
   conceptuales ya corregidos; no reintroducirlos.
5. **Hilos BLAS en 1** (`OPENBLAS_NUM_THREADS=1` etc. en Dockerfile y compose):
   evita los segfaults `exit 139` de statsmodels en WSL/Docker.
6. **⚠ GRP001**: dos grippers distintos con el mismo código en las BOM de
   paletizado. Se mantienen **separados y marcados**, no consolidar.
7. **Órdenes de fabricación (mrp.production) ligadas a la BOM.** La página
   *Órdenes Odoo* crea, por línea del plan MRP, una `purchase.order` de
   insumos (concentrados, etiquetas, tapas, ...) y **una `mrp.production` por
   producto y mes** (compartida entre proveedores de ese lote), ligada a la
   `mrp.bom` del SKU. La PO de insumos se **confirma y recibe de inmediato**
   al crearse (`crear_orden_compra(recibir=True)`) — la suite no modela el
   lead time real del proveedor — para que la MO pueda reservar contra ese
   stock. El middleware valida la MO (`button_mark_done`) cuando la
   producción real reportada por MQTT cubre la cantidad objetivo del lote;
   ahí Odoo descuenta la BOM y da entrada al producto terminado. El vínculo
   PO↔MO vive en `state_store.po_tracking` (`mo_id`/`mo_name`).
8. **Idempotencia por referencia.** `crear_orden_compra`, `crear_orden_fabricacion`
   y `crear_orden_venta` buscan primero una orden **no cancelada** con la misma
   referencia (`origin` en PO/MO, `client_order_ref` en SO —
   `OdooClient._buscar_orden_existente`) antes de crear otra. Evita duplicados
   si el usuario reintenta o hace doble clic en el dashboard — nos pasó de
   verdad probando contra Odoo real (~21 POs duplicadas en una sesión). No
   quitar esta búsqueda previa aunque parezca redundante.
9. **Ventas y cuentas por pagar/cobrar.** El flujo completo del ERP es
   compra-insumo → fabricación → **venta → factura → cobro**. Cuando una MO
   queda `recibida_odoo` (producto terminado disponible), la página *Ventas y
   Facturación* la reparte entre los clientes de `data/clientes.csv` (según
   `participacion`) y crea una `sale.order` por cliente: confirma, entrega
   (`stock.picking` de salida) y factura (`account.move` `out_invoice`). Del
   lado de compras, `crear_orden_compra(facturar=True)` genera además la
   factura de **proveedor** (`account.move` `in_invoice`) sobre la PO ya
   recibida — la cuenta por pagar, no solo el movimiento de inventario. El
   vínculo lote↔ventas vive en `state_store.venta_tracking` (`mo_name`).

## Estado actual (validado)

- Pronóstico v4 sobre 21 trimestres reales de KOF: MAPE 2.9/2.9/2.1 %.
- Tiempos auditados: OEE base 77.1/76.5/75.4 %, TEEP 40.3/40.0/8.3 %.
  **Hallazgo:** con 2 turnos U=1.25 (L1) y 1.30 (L2) → **infactible**, el 3er
  turno la devuelve a 0.83/0.86.
- Caso de negocio (demanda v4): CAPEX $22.216 M · EBITDA incremental $13.182 M
  (12 m operativos) · **VPN $8.033 M · TIR 36.6 % E.A. · ROI 103.8 % · payback
  33/42 m**.
- Libro Excel: 23 hojas, 3.741 fórmulas, **0 errores** tras recalcular.
- `tools/verificacion.py`: **13/13 en verde**.

## Comandos

```bash
# Levantar todo (reconstruye con las variables anti-segfault)
docker compose -f docker-compose.dashboard.yml up -d --build
docker compose -f docker-compose.dashboard.yml logs -f dashboard

# QA completo (13 pasos) — obligatorio antes de cerrar cualquier cambio
python tools/verificacion.py

# Poblar Odoo desde cero
python tools/bootstrap_odoo.py --dry    # plan
python tools/bootstrap_odoo.py          # ejecuta

# Middleware + simulador de producción (UNS)
python middleware/run_middleware.py
python tools/simulador_produccion.py --n 20

# Regenerar el libro financiero (repo hermano) y recalcular
cd ../femsa-modelo-financiero
python tools/generar_modelo.py
# recalcular con LibreOffice hasta 0 errores antes de subir a Drive
```

## Credenciales (`.env`, ya configuradas — NO versionado)

Variables: `ODOO_URL`, `ODOO_DB`, `ODOO_USER`, `ODOO_API_KEY`, `MQTT_HOST`,
`GOOGLE_SA_JSON` (ruta al JSON de la cuenta de servicio, `config/`, no
versionado), `SHEETS_SPREADSHEET_ID`. Ver `.env.example` para el formato;
los valores reales viven solo en `.env` local de cada desarrollador.

**Nunca** commitear `.env` ni `config/google_service_account.json`, ni pegar
sus valores (URLs, correos, IPs, IDs) en archivos versionados como este.
Estas credenciales son de desarrollo y se rotarán.

## Convenciones de código

- Python 3.12, sin type-checker estricto; docstrings en español al inicio de cada
  módulo explicando el **porqué** (no solo el qué).
- Nombres de funciones y variables en español (`publicar_demanda`,
  `flujos_desde_demanda`, `nombre_esc`), consistente con el resto del repo.
- Los módulos de `core/` son **puros** (sin Streamlit): reciben DataFrames y
  devuelven DataFrames/dicts. La UI vive solo en `app/`.
- Cada módulo de `core/` tiene un bloque `if __name__ == "__main__":` que imprime
  un resumen — útil para probar sin levantar la app.
- Excel: azul = entrada editable, negro = fórmula, verde = referencia entre
  hojas, amarillo = palanca clave. Fuente Arial. **Siempre recalcular** con
  LibreOffice antes de entregar un `.xlsx` con fórmulas.

## Pendientes

- Flujo de Node-RED que puentee Ignition → UNS con el contrato del middleware.
- Write-path completo a Odoo (POST desde la GUI → MES Engine → MQTT → Node-RED →
  OPC UA write).
- Cerrar la tensión TEEP/utilización con horas programadas reales de la planta.
- Resolver GRP001 con el taller antes de emitir la RFQ.
- Costeo/valoración de inventario, checkpoints de calidad, reposición
  automática de clientes y registro de cobro (`account.payment`) contra la
  factura de cliente — el flujo venta→factura ya existe, falta el cobro.
