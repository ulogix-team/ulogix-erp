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
hojas que se conecta al ERP por la API de Google Sheets. El generador importa
`CAPEX_FILAS`, `VIDAS` de `core/finanzas_negocio.py` y las tablas de
`core/tiempos_oee.py` de este repo, pero solo como **seed inicial** del libro
— ver decisión de diseño #3: para CAPEX/turnos/precios, el libro de Sheets ya
editado por el usuario manda sobre esas constantes, no al revés.

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
| `app/Inicio.py` + `app/pages/1..10` | Dashboard Streamlit (10 páginas) |
| `app/ui/theme.py` | Tema, helpers (`datos_pronostico()`, `demanda_activa()`, `plotly_layout()`), supresión de warnings |
| `core/forecast.py` | Holt-Winters amortiguado + Bates-Granger óptimo + Monte Carlo |
| `core/escenarios.py` | 6 presets + escenario personalizado (elasticidades **por producto**) |
| `core/inventario.py` | Política (s,Q) Monte Carlo + MRP |
| `core/tiempos_oee.py` | Tiempos y OEE **documentales** (auditoría corregida) |
| `core/finanzas_negocio.py` | **Motor financiero demand-driven**; `CAPEX_FILAS`/`TRM`/`TMAR`/... son el **default/fallback** — la fuente viva es la hoja `Parametros`/`CAPEX` de Sheets |
| `core/sensibilidad.py` | Tornado paramétrico |
| `core/rrhh.py` | Dotación/costo del roster de empleados (puro; reconcilia contra la hoja `Personal`) |
| `integrations/uns.py` | Interpreta `config/uns_femsa.yaml` (79 tópicos, incl. agregado de planta `linea='PLANTA'`) |
| `integrations/mqtt_middleware.py` | Suscribe UNS, cumple POs, publica rama ERP retained |
| `integrations/odoo_client.py` | XML-RPC; `LineaPedido(nombre, default_code, cantidad, precio_unitario)`; compras+fabricación+**ventas+facturación** (cliente y proveedor), todo idempotente por referencia |
| `integrations/sheets_client.py` | gspread + **fallback a Excel local** |
| `integrations/rrhh_client.py` | Roster de empleados: hoja `Empleados` de Sheets + fallback `data/empleados.csv` |
| `integrations/state_store.py` | SQLite WAL, 8 tablas ERP |
| `tools/verificacion.py` | **QA de 15 pasos — correr siempre antes de dar algo por bueno** |
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
3. **CAPEX/turnos/precios: Sheets gobierna, Python es el fallback (cambió de
   dirección a propósito).** Decisión original: `CAPEX_FILAS` vivía en
   `core/finanzas_negocio.py` como **fuente única** y el generador del Excel
   la importaba — "no duplicar cifras". Por pedido explícito del dueño del
   proyecto ("quiero que las unit economics y todo tema financiero se tome de
   la hoja de Sheets, no de un maestro local... el ERP se tiene que
   actualizar según cualquier cambio del documento de Sheets") esa dirección
   se **invirtió**: ahora el libro de Google Sheets (hojas `Parametros` — TRM,
   TMAR, nómina, otros fijos, licencias, vidas útiles, unit economics por
   SKU — y `CAPEX` — tabla completa) es la fuente **viva** que el usuario
   edita a mano, y `core/finanzas_negocio.py` la lee en cada llamada
   (`_parametros()`/`_capex_filas_activas()`/`_maestro()`, TTL de 60 s en
   memoria vía `integrations/sheets_client.py: leer_parametros()`/
   `leer_capex()`) con un botón "🔄 Refrescar desde Sheets" en la página
   *Finanzas* para forzar la lectura. Las constantes de módulo (`CAPEX_FILAS`,
   `TRM`, `TMAR_ANUAL`, etc.) **siguen existiendo** pero ahora son el
   default/fallback: se usan tal cual si Sheets no está configurado, la hoja
   está vacía/con encabezado distinto, o una celda no castea a número — el
   motor da los mismos resultados de siempre en ese caso (`tools/
   verificacion.py`, paso "Caso de negocio", sigue exigiendo
   `payback_simple_meses == 33`). El generador del libro hermano
   (`../femsa-modelo-financiero`) sigue importando esas constantes, pero ahora
   son solo el **seed** con el que se puebla el libro la primera vez, no la
   fuente de verdad en operación — no vuelvas a llamarlo "fuente única" en
   código o docs nuevos. Contrato completo de columnas en
   `docs/INTEGRACION_APIS.md` §1 y en el skill `modelo-financiero-ulogix`.
   El maestro físico que usa Odoo/MRP (`data/maestro_productos.csv`) es un
   dato **separado** y no lo gobierna esta hoja de Sheets — ver la nota en
   ese mismo skill si hace falta mantenerlos consistentes.
   **Nota real (verificado contra el libro):** las claves del libro real son
   minúsculas y en español (`trm_cop_usd`, `nomina_operacion_mes`,
   `fase_capex_1..4` en filas separadas, `precio_p1_330ml`...) y los números
   vienen en **formato colombiano** (punto = miles, coma = decimales —
   `"3.850"` = 3850, `"18,00%"` = 0.18), no en el formato inglés que se
   asumió al principio. `OPEX_LICENCIAS_MES`/`CAPEX_SOFTWARE` viven en la
   hoja `Licencias`, no en `Parametros`. Todo esto ya está resuelto:
   `_ALIAS_PARAMETROS`/`_normalizar_overrides()` en `core/finanzas_negocio.py`
   traducen las claves reales, `integrations/sheets_client.py: numero_cop()`
   parsea el formato colombiano, `leer_capex()` reconoce el encabezado real
   por nombre de columna (`activo / paquete`, `vida (años)`, con una columna
   extra `CAPEX COP` ya calculada que se ignora), y `leer_licencias()` lee
   los dos totales de esa hoja. Verificado end-to-end: 25 filas de CAPEX
   real leídas correctamente (vs. 24 del default local), VPN $8.059 M / TIR
   36.7 % / ROI 104.0 % / payback 33 m con datos en vivo.
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
10. **RRHH: roster individual en la hoja `Empleados`, separado del agregado
    `Personal`.** `Personal` es la hoja del libro financiero con el agregado
    por rol (conteo, costo unitario, costo total, fase) que ya gobierna
    `NOMINA_OPERACION_MES`/`NOMINA_IMPLEMENTACION_MES` (decisión #3) — **no se
    toca**. `Empleados` (nueva, `integrations/rrhh_client.py`) es el detalle
    persona por persona; cada fila tiene un `rol_personal` que debe coincidir
    con las categorías de `Personal` para poder reconciliar ambas
    (`core.rrhh.reconciliar_con_personal`, sección 3 de la página *RRHH*). A
    diferencia de `Demanda`/`Inventarios`, `Empleados` no tiene fórmulas
    dependientes: se reemplaza completa (`clear`+`append`) sin problema.
11. **Costos de ingeniería ULogix: APU (Análisis de Precios Unitarios), Sheets
    manda igual que el resto de CAPEX.** Las 3 filas `Servicios` de la hoja
    `CAPEX` (Ingeniería de detalle/FAT/SAT/PMO, Instalación/EPC, Capacitación/
    gestión del cambio) ahora se justifican componente por componente en la
    hoja nueva `APU_Ingenieria` (`tools/publicar_apu_ingenieria.py`,
    `Contabilidad.leer_apu_ingenieria()`): costo directo (mano de obra propia
    — costo real de `data/empleados.csv` — + subcontratistas/OEM + materiales
    + logística) × (1 + AIU). **AIU es una referencia de mercado (25–30%),
    NO una tarifa fijada por ley** — Colombia desreguló los honorarios de
    ingeniería (COPNIA no fija tarifas mínimas desde hace años); no afirmar
    lo contrario en código o docs. El AIU implícito resultante (27–28% en
    los tres ítems) valida que los montos de `CAPEX` ya estaban bien
    calibrados — **el precio total de cada ítem no cambió**, solo se
    justificó de abajo hacia arriba. Es de **solo lectura/exhibición**: no
    alimenta ningún cálculo de `core/finanzas_negocio.py` (los montos que sí
    computan siguen siendo los de `CAPEX`). Se muestra en la página
    *Finanzas*, sección "Costos de ingeniería ULogix — APU". Las 3 filas de
    `CAPEX` quedaron anotadas con `(ver hoja APU_Ingenieria)` (solo texto en
    la columna `activo / paquete`, no se tocaron cantidad/moneda/
    costo_unitario/vida/categoría).
12. **Identidad visual corporativa en `app/ui/theme.py`.** Paleta derivada
    del logo (fondo `#070213`, acento violeta `#8F7BFF`), tokens en `COL`
    (`base/panel/panel2/texto/texto2/acento/alerta/ok/borde/borde2/muted/
    critico/acento2`) y `COLORWAY` para series genéricas — **los colores por
    línea/SKU (`COLOR_SKU`) no cambiaron**, es la firma visual de la suite.
    `st.container(border=True)` alrededor de grupos de métricas es el patrón
    estándar en las 10 páginas para agrupación visual — úsalo en páginas
    nuevas. Cambio puramente visual/CSS: ningún cálculo, integración ni dato
    se tocó.
13. **UNS: 79 tópicos, incluye agregado de planta completa (`linea='PLANTA'`).**
    Verificado conectándose directo al broker real (Coreflux Hub, panel de
    administración en `:8080` de la IP del broker, accesible por Tailscale) y
    suscribiendo a `#`: además de los 9 KPI (incluye `MLT`, antes faltante) +
    4 mantenimiento + 9 ERP por línea, el broker publica **el mismo bloque
    KPI/Maintance a nivel de planta completa, sin segmento de línea**
    (`FEMSA/MES/KPI/...`) — antes invisible para nosotros (ni la suscripción
    ni `interpretar_topico()` lo reconocían). `integrations/uns.py` ahora se
    suscribe también a `FEMSA/MES/KPI/#`/`FEMSA/MES/Maintance/#` y las
    etiqueta `linea='PLANTA'`: caen en la misma tabla `kpi_uns` y el mismo
    tablero (páginas *Producción MQTT* y *Base de Datos*), sin vista aparte.
    El broker también trae `celda/status/nodered` (liveness del bridge
    Node-RED, aún sin integrar) y `Agent/*` (telemetría interna de Coreflux
    con IA, irrelevante) — no forman parte del UNS FEMSA, ignorarlos.
14. **`AvailableQuantity` (no `Process/GoodCount`) es el camino PRINCIPAL de
    producción; una sola orden de fabricación activa por línea a la vez.**
    Conexión **directa** al broker (Coreflux) — no requiere Node-RED de por
    medio para este flujo. Reparto de responsabilidades en la rama
    `FEMSA/LineaX/ERP/*`:
    - El **ERP** (esta suite) **publica** (retained) qué hay que producir:
      `OrderNumber` (= nombre de la MO, ya no el de la PO — `erp_desde_po()`
      usa `mo_name`), `OrderedQuantity`, `ScheduleStart/End`, `OrderStatus`,
      `ReservedQuantity`. Publica **una sola orden activa por línea a la
      vez** — la más antigua `'abierta'` de ese SKU (`state_store.
      orden_activa()`). Solo cuando esa orden se completa publica la
      **siguiente** de la cola — nunca dos activas a la vez en la misma
      línea. Se reafirma cada `INTERVALO_REPUBLICAR` (15 s,
      `mqtt_middleware.py`) para autocurarse si algo externo pisó la hoja.
    - El **MES** (planta real o su simulación en el broker) **escribe**
      `AvailableQuantity`: cuánto lleva producido de la orden activa, como
      valor **ABSOLUTO** (no un delta). El ERP se **suscribe** a esa hoja
      como dato de entrada — **nunca la publica él mismo** (evita eco/
      carrera) — y la usa (`state_store.actualizar_disponible()`) para
      marcar la orden `'cumplida'` → validar la MO en Odoo
      (`completar_orden_fabricacion`, descuenta la BOM: tapas, etiquetas,
      concentrado...) → avanzar sola a la siguiente.
    - **Protección contra ruido** (necesaria: ver hallazgo #13 — Coreflux
      Hub puede inyectar valores aleatorios vía su agente de IA):
      `actualizar_disponible()` exige que el avance sea **monótono** (un
      valor que retrocede se ignora, la producción real nunca disminuye) y
      **recorta** cualquier valor que supere el objetivo — nunca confía en
      el dato crudo del broker sin validar.
    - El contrato legado `Process/GoodCount` (delta, no valor absoluto)
      **sigue funcionando** (`state_store.acumular_produccion()`, ahora un
      wrapper delgado sobre `actualizar_disponible()`) para pruebas locales
      (`tools/simulador_produccion.py`, botón de prueba en *Producción
      MQTT*) pero **ya no es necesario en producción** — no lo quites, pero
      no lo trates como el camino principal en código o docs nuevos.
    - Sección de pruebas dedicada: página *Pruebas → 4 · Producción (orden
      activa)* — muestra la orden activa por línea, permite simular
      `AvailableQuantity` localmente (sin MQTT, prueba la lógica al
      instante) o publicarlo de verdad al broker. `tools/verificacion.py`
      paso 16 cubre cola de 2 órdenes + ruido descendente + recorte.

## Estado actual (validado)

- Pronóstico v4 sobre 21 trimestres reales de KOF: MAPE 2.9/2.9/2.1 %.
- Tiempos auditados: OEE base 77.1/76.5/75.4 %, TEEP 40.3/40.0/8.3 %.
  **Hallazgo:** con 2 turnos U=1.25 (L1) y 1.30 (L2) → **infactible**, el 3er
  turno la devuelve a 0.83/0.86.
- Caso de negocio (demanda v4): CAPEX $22.216 M · EBITDA incremental $13.182 M
  (12 m operativos) · **VPN $8.033 M · TIR 36.6 % E.A. · ROI 103.8 % · payback
  33/42 m**.
- Libro Excel: 23 hojas, 3.741 fórmulas, **0 errores** tras recalcular.
- `tools/verificacion.py`: **15/15 en verde**.
- Hoja `Empleados` creada y poblada en el libro real (28 personas, reconcilia
  exacto con los totales de `Personal`: Operación $85.915.382, Implementación
  $87.161.760).

## Comandos

```bash
# Levantar todo (reconstruye con las variables anti-segfault)
docker compose -f docker-compose.dashboard.yml up -d --build
docker compose -f docker-compose.dashboard.yml logs -f dashboard

# QA completo (15 pasos) — obligatorio antes de cerrar cualquier cambio
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
- El generador del repo hermano (`../femsa-modelo-financiero/tools/
  generar_modelo.py`) todavía sobreescribe `Parametros`/`CAPEX` con el seed de
  Python en cada regeneración — falta hacerlo "merge-aware" (no pisar valores
  que el usuario ya editó en Drive) si se va a regenerar el libro en
  producción con frecuencia.
