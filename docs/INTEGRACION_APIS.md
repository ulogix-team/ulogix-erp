# Integración de APIs — Suite Ulogix Fontibón

Guía definitiva para conectar las tres integraciones. Las credenciales viven
**solo** en `.env` y `config/google_service_account.json` (nunca en el código);
Docker las monta con `env_file` y volúmenes.

---

## 1 · Google Sheets (cuenta de servicio)

**Cómo funciona.** La app no usa tu cuenta personal: usa una *service account*
de Google Cloud cuyo JSON de credenciales ya está en
`config/google_service_account.json` (el `client_email` está dentro de ese
JSON, no versionado). gspread firma un JWT con esa llave privada contra
`oauth2.googleapis.com` y opera el libro como un editor más. Por eso el único
requisito es **compartir el libro con ese correo**.

**Pasos (una sola vez):**
1. Sube `Modelo_FEMSA_Ulogix_2026.xlsx` (repo `femsa-modelo-financiero/salida/`)
   a Google Drive y ábrelo → *Archivo → Guardar como hoja de cálculo de Google*.
2. Botón **Compartir** → agrega como **Editor** el `client_email` de
   `config/google_service_account.json`
3. Copia el **ID** del libro de la URL:
   `https://docs.google.com/spreadsheets/d/`**`<ID>`**`/edit`
4. En `.env`: `SHEETS_SPREADSHEET_ID=<ID>` → reinicia
   (`docker compose -f docker-compose.dashboard.yml restart`).
5. Página **Pruebas** → *Probar Sheets*: escribe y relee la hoja `_PruebaAPI`.

**Contrato de hojas (por área del ERP).** Dos direcciones conviven en el mismo
libro: el ERP **escribe** demanda/inventario/compras, y desde esta versión
**lee** CAPEX/turnos/precios/unit-economics de vuelta — el usuario edita esas
hojas a mano y el motor financiero (`core/finanzas_negocio.py`) las recoge en
el siguiente render (TTL de 60 s en memoria, o el botón **🔄 Refrescar desde
Sheets** de la página Finanzas para forzarlo al instante):

| Área | Hoja | Dirección | Método | Rango |
|---|---|---|---|---|
| Ventas | `Demanda` (pronóstico Base) | ERP → Sheets | `publicar_demanda()` — se dispara solo al recalcular el pronóstico (`app/ui/theme.py:datos_pronostico()`, cacheado) | **fijo A4:F16** |
| Ventas | `DemandaEscenario` (escenario activo) | ERP → Sheets | `publicar_demanda_escenario()` — se dispara al **Activar** en la página Escenarios | **fijo A4:F16** |
| Inventario | `Inventarios` (política s,Q) | ERP → Sheets | `publicar_inventarios()` — al simular en la página Inventario | **fijo A4:I8** |
| Compras | `PlanCompras` | ERP → Sheets | `publicar_plan_compras()` | reemplazo |
| Producción | `LibroProduccion` / `ResumenMensual` / `KPIs_UNS` | ERP → Sheets | middleware/sync | append/reemplazo |
| Maestro | `Maestro_Productos` (SKU, atributos físicos, empaque, EAN, precio y costo base) | **Sheets → ERP** | `leer_maestro_productos()` | tabla completa por SKU |
| Financiero | `Parametros` (pares clave-valor: TRM, TMAR, nómina, otros fijos, vidas útiles, unit economics por SKU...) | **Sheets → ERP** | `leer_parametros()` | pares clave-valor, cualquier fila |
| Financiero | `CAPEX` (tabla: sección, línea, activo, cantidad, moneda, costo_unitario, vida_años, categoría_dep) | **Sheets → ERP** | `leer_capex()` | tabla, encabezado reconocido por nombre de columna |
| Financiero | `Licencias` (`CAPEX software capitalizable`, `OPEX mensual licencias` — última celda no vacía de la fila) | **Sheets → ERP** | `leer_licencias()` | filas etiquetadas, sin columna fija |
| RRHH | `RRHH` (roster + resumen por rol + tasas, consolidada — ver `integrations/rrhh_client.py`) | ERP → Sheets *(alta)* / **Sheets → ERP** *(lectura)* | `leer_empleados()` / `publicar_empleados()` / `agregar_empleado()` | reconstrucción completa (el resumen se deriva del roster), sin fórmulas dependientes |
| Financiero | `APU_Ingenieria` (costos de ingeniería que cobra ULogix, justificados por AIU) | ERP → Sheets | `tools/publicar_apu_ingenieria.py` (escribe) / `leer_apu_ingenieria()` (lee, solo exhibición) | reemplazo; tarifa propia enlazada por fórmula a `RRHH` |
| Financiero | `Analisis_Paletizado` (caso de inversión paralelo: paletizado+encajonado antes/ULogix/comercial) | ERP → Sheets | `tools/publicar_analisis_paletizado.py` — solo exhibición, no alimenta `CAPEX_FILAS` ni el caso de negocio principal | reemplazo, sin fórmulas dependientes |

**Formato numérico del libro real: colombiano, no inglés.** Punto = separador
de miles, coma = separador decimal (`"3.850"` = 3850, `"18,00%"` = 0.18,
`"1.200,0"` = 1200.0). `integrations/sheets_client.py: numero_cop()` es el
parser compartido; `core/finanzas_negocio.py: _num()` lo usa y además maneja
el sufijo `%`. **No** uses el formato inglés al editar celdas nuevas.

**Contrato de la hoja `Parametros` para el motor financiero** (todas las
claves son opcionales — si faltan o el valor no castea a número, el motor usa
su default local). El libro real usa claves **minúsculas en español**, que
`core/finanzas_negocio.py: _ALIAS_PARAMETROS` traduce a las claves canónicas
internas (también se aceptan las claves canónicas directamente, sin
distinguir mayúsculas/minúsculas):

| Clave real (libro) | Clave canónica |
|---|---|
| `trm_cop_usd` | `TRM` |
| `factor_rfq_benchmark` | `FACTOR_RFQ` |
| `tmar_anual` | `TMAR_ANUAL` |
| `tasa_renta` | `TASA_RENTA` |
| `uplift_throughput` | `UPLIFT_THROUGHPUT` |
| `factor_monetizacion` | `FACTOR_MONETIZACION` |
| `rampa_mes5` | `RAMPA_MES5` |
| `scrap_pp` | `SCRAP_PP` |
| `mant_evitado_mes` | `MANT_EVITADO_MES` |
| `wc_pct_ingreso` | `WC_PCT_INGRESO` |
| `nomina_operacion_mes` | `NOMINA_OPERACION_MES` |
| `nomina_implementacion_mes` | `NOMINA_IMPLEMENTACION_MES` |
| `otros_fijos_base_mes` | `OTROS_FIJOS_BASE_MES` |
| `otros_fijos_proyecto_mes` | `OTROS_FIJOS_PROYECTO_MES` |
| `contingencia_capex` | `CONTINGENCIA` |
| `fase_capex_1` .. `fase_capex_4` (4 filas) | `FASES_CAPEX` (se combinan) |
| `precio_p1_330ml` o `precio_p1_350ml` / `precio_p2_pet15` / `precio_p3_garrafon` | `precio_venta_cop_<SKU>` |

`VIDA_equipos`/`VIDA_automatizacion`/`VIDA_servicios`/`VIDA_intangibles`/
`VIDA_software` y `costo_material_cop_<SKU>` **no tienen hoy una fila
equivalente en el libro real** — quedan solo con el default local hasta que
se agreguen (con esos mismos nombres canónicos, no hace falta alias). Esta
Los atributos físicos/comerciales se leen de `Maestro_Productos` mediante
`core.forecast.cargar_maestro()` y `core.finanzas_negocio._maestro()` en modo
operativo. `data/maestro_productos.csv` es únicamente semilla/fallback cuando
`EXTERNAL_ONLY=false`; nunca es la fuente viva del despliegue.

**`crecimiento_demanda` ya no se lee** (decisión #20, 2026-07): el motor
Python eliminó por completo el parámetro `CRECIMIENTO_DEMANDA_ANUAL` — la
evaluación financiera sigue siempre la demanda que manda el ERP (pronóstico
o escenario activo), sin inflarla con una tasa de crecimiento aparte. La
fila queda en `Parametros!B10 = 0%` (conservada para auditoría, mismo
patrón que el CAPEX en cantidad=0). El motor nativo de Sheets (`ER_Proyecto`/
`FinancieroEscenario`) sigue teniendo la fórmula `(1+Parametros!$B$10)^N` en
~900 celdas — queda neutralizada porque B10=0, no porque se haya borrado.

**Contrato de la hoja `CAPEX`**: `leer_capex()` busca la fila de encabezado
por **nombre de columna** (no por posición exacta) — reconoce variantes como
`activo / paquete`, `cant.`, `vida (años)`, `categoria D&A`, y ADEMÁS ignora
columnas extra intercaladas (el libro real trae una `CAPEX COP` ya calculada
entre `costo_unitario` y `vida_anios`). `moneda` es `COP`, `USD` (aplica
`FACTOR_RFQ`) o `USD*` (cotización real, sin factor RFQ). `OPEX_LICENCIAS_MES`
y `CAPEX_SOFTWARE` **no** viven en `CAPEX` ni en `Parametros` — viven en la
hoja `Licencias` (filas `CAPEX software capitalizable` / `OPEX mensual
licencias`), leídas por `leer_licencias()`. Si una hoja no existe, está vacía
o no se reconoce ninguna columna esperada, el motor cae a su default local —
no hay error visible al usuario, solo se ignora la hoja.

**Contrato de la hoja `APU_Ingenieria`** (costos de ingeniería que cobra
ULogix, solo exhibición — no alimenta ningún cálculo, los montos que sí
computan siguen siendo los de `CAPEX`): dos bloques marcados por una fila
`RESUMEN` y una fila `DETALLE`, cada uno con su propia fila de encabezado
inmediatamente debajo (`leer_apu_ingenieria()` los ubica por esa etiqueta,
no por posición fija). `RESUMEN`: `item, costo_directo_cop,
pct_administracion, pct_imprevistos, pct_utilidad, pct_aiu_total, aiu_cop,
precio_total_cop` — una fila por ítem de `Servicios`. `DETALLE`: `item,
componente, descripcion, cantidad, unidad, valor_unitario_cop, subtotal_cop,
tipo_costo` — todas las líneas de costo de los tres ítems, con filas de
subtotal/AIU/total intercaladas (columna `item` vacía en esas). Metodología
APU (Análisis de Precios Unitarios, estándar de construcción/EPC en
Colombia): `precio_total = costo_directo × (1 + AIU)`, AIU = Administración +
Imprevistos + Utilidad — banda de mercado 25–30%, **no una tarifa fijada por
ley** (COPNIA no fija honorarios mínimos desde la desregulación). Se publica
con `python tools/publicar_apu_ingenieria.py` (también anota las 3 filas de
`Servicios` en `CAPEX` con `(ver hoja APU_Ingenieria)`, solo en la columna de
descripción). Se muestra en la página *Finanzas*.

Los rangos **fijos** de `Demanda`/`DemandaEscenario`/`Inventarios` existen
porque las hojas financieras (`ER_Proyecto`, `Flujo_Caja`, `Balance`,
`FinancieroEscenario`, `Inventarios·rotación`) referencian esas celdas con
fórmulas: la app escribe posicionalmente sin romperlas — eso **no cambió**.
**`Tiempos` es DOCUMENTAL** (referencia de ingeniería del estudio corregido,
consolidada 2026-07 — incluye OEE/TEEP, `OEE_TEEP` ya no existe como hoja
aparte, ver decisión #17 — no conectada al ERP en vivo). Su bloque de
capacidad separa explícitamente **ANTES** (equipos, tiempos, OEE y turnos
medidos) de **DESPUÉS** (equipos incluidos en CAPEX, celdas robotizadas, OEE
objetivo y turnos de diseño). También muestra “después con los mismos turnos”
para no atribuir al equipo el aumento que realmente proviene del tercer turno.
El MLT posterior es una proyección hasta validarlo en SAT/comisionamiento.
El ERP **no gestiona los KPI OEE/TEEP vivos**: esos valores llegan solo por
MQTT según el UNS a `kpi_uns` y luego se archivan en `KPIs_UNS`.
Si el ID no está configurado, todo cae a un Excel local
(`data/contabilidad_local.xlsx`) con la misma estructura: cero pérdida — y el
motor financiero da exactamente los mismos números que con sus constantes
hardcodeadas de antes (verificado en el paso "Caso de negocio" de
`tools/verificacion.py`).

**Si crea una credencial nueva:** Google Cloud Console → proyecto → *IAM y
administración → Cuentas de servicio → Claves → Agregar clave (JSON)* →
reemplazar `config/google_service_account.json` y volver a compartir el libro
con el `client_email` nuevo. Habilitar las APIs *Google Sheets API* y
*Google Drive API* en el proyecto.

---

## 2 · Odoo (API externa XML-RPC)

**Cómo funciona.** Odoo expone `/xmlrpc/2/common` (autenticación) y
`/xmlrpc/2/object` (`execute_kw` sobre cualquier modelo). La API key
funciona como **contraseña** del usuario; el login sigue siendo tu correo.

**`.env` (formato — los valores reales viven SOLO en tu `.env` local, nunca
en archivos versionados; ver `.env.example`):**
```
ODOO_URL=https://tu-instancia.odoo.com
ODOO_DB=tu-base-de-datos          # en odoo.com la BD se llama como el subdominio
ODOO_USER=tu-correo-de-login-odoo
ODOO_API_KEY=tu-api-key           # NUNCA pegar la key real aqui — repo publico
```
> Si la autenticación falla con usuario/clave correctos, confirma el nombre real
> de la BD: entra a `<ODOO_URL>/web/database/selector` o mira `web.base.url`
> en Ajustes técnicos.

**Poblar Odoo desde cero** (tu instancia solo tiene las apps; ni productos ni
BOM). El script es idempotente:
```bash
python tools/bootstrap_odoo.py --dry   # muestra el plan
python tools/bootstrap_odoo.py         # instala Compras si falta y crea:
```
- Productos terminados P1/P2/P3 con **EAN-13**, precio y costo del maestro.
- 16 componentes de BOM comprables con proveedor y tarifa
  (`product.supplierinfo`: precio, MOQ, lead time).
- **Listas de materiales** (`mrp.bom`) de los tres productos.

**Flujo en operación:** la página *Órdenes (Odoo)* crea, por cada línea del
plan MRP, un `purchase.order` de insumos (concentrados, etiquetas, tapas, ...)
que **se confirma y se recibe de inmediato** (`button_confirm` →
`stock.picking → button_validate`) — la suite no modela el lead time real del
proveedor, así que el insumo queda disponible en inventario en el mismo paso.
Si se pide `facturar=True`, además genera y contabiliza la **factura de
proveedor** (`account.move` `in_invoice`, vía `action_create_invoice` +
`action_post`) — la cuenta por pagar, no solo el movimiento de inventario.
Junto con esa PO se crea **una orden de fabricación por producto y mes**
(`mrp.production`, ligada a la `mrp.bom` del SKU creada por
`bootstrap_odoo.py`), confirmada y con los componentes **reservados**
(`action_assign`) contra ese stock recién recibido. El middleware, al
completarse la producción real vía UNS, **valida la orden de fabricación**
(`button_mark_done`): Odoo descuenta los componentes de la BOM y da entrada al
producto terminado. `integrations.state_store.po_tracking` guarda el vínculo
PO↔MO (`mo_id`/`mo_name`) para que el middleware sepa cuál validar — ver
§3 (MQTT) para el detalle de cómo `AvailableQuantity` dispara esa validación,
solo una orden activa por línea/SKU a la vez. Sin credenciales la suite opera
en `dry-run` y registra todo en SQLite.

**Inventario en vivo, no solo al cerrar la orden.** Cada `INTERVALO_SYNC_ODOO`
(60 s), `OdooClient.avanzar_produccion_parcial()` postea a Odoo el avance
acumulado desde el último sync usando el mecanismo nativo de **backorder**
de `mrp.production`: fija `qty_producing` parcial, marca los `stock.move` de
componentes recogidos en esa proporción y llama `button_mark_done` — con
`qty_producing < product_qty` esto no cierra la orden sino que dispara el
wizard `mrp.production.backorder`, que se completa por RPC con
`to_backorder=True`. La orden original queda `done` solo por esa porción
(BOM descontada, terminado entrado) y Odoo crea automáticamente una MO
backorder por el remanente (mismo `origin`) que sigue abierta. El cierre
final de la orden (cuando `AvailableQuantity` alcanza el objetivo) sigue
usando `completar_orden_fabricacion` tal cual, sin backorder. Verificado en
vivo contra Odoo real (saas-19.3): una cadena de varios avances parciales +
cierre final suma exacto al objetivo, cada tramo con su propio `stock.move`
`done`. Nota: la respuesta XML-RPC de `action_backorder` puede traer un
`Fault` de marshalling ("cannot marshal None") aunque la operación sí se
ejecutó en el servidor — el cliente no confía en esa respuesta, relee el
estado de la MO para confirmar. El ERP local espeja el mismo movimiento de
inmediato (sin esperar el sync a Odoo) en `state_store.inventario_stock` —
ver §5.

**Idempotencia.** `crear_orden_compra`, `crear_orden_fabricacion` y
`crear_orden_venta` buscan primero una orden **no cancelada** con la misma
referencia (`origin` en PO/MO, `client_order_ref` en SO —
`OdooClient._buscar_orden_existente`) antes de crear otra. Sin esto, hacer
doble clic en "Crear órdenes en Odoo" duplicaba POs/MOs contra la instancia
real (nos pasó de verdad: ~21 POs con el mismo `origin` en una sesión de
pruebas).

**Ventas y facturación de cliente.** Cuando una MO queda `recibida_odoo`
(producto terminado disponible), la página *Ventas y Facturación* la reparte
entre los clientes de `data/clientes.csv` (columna `participacion`) y por
cada uno crea un `sale.order` (`OdooClient.crear_orden_venta`): confirma
(`action_confirm`), entrega (`stock.picking` de salida — misma lógica de
`quantity_done`/`quantity`+`picked` que `recibir_orden`) y factura
(`account.move` `out_invoice` vía `_create_invoices`/`action_invoice_create`
+ `action_post`). Cierra el flujo compra-insumo → fabricación → venta →
factura → cobro. `integrations.state_store.venta_tracking` guarda cada SO
vinculada a su lote (`mo_name`) para no vender el mismo lote dos veces.

---

## 3 · MQTT — UNS FEMSA

**Broker:** el de tu stack (`MQTT_HOST` en `.env`), **conexión directa** — este
flujo no pasa por Node-RED. Regla de red del proyecto: fuera de Docker se usa
la **IP LAN** (no `localhost` ni hostnames de servicios Docker); dentro de
docker-compose sí resuelven los nombres de servicio.

**El árbol del UNS es tu YAML** (`config/uns_femsa.yaml`, guardado tal cual).
El middleware:

| Acción | Tópicos |
|---|---|
| Se suscribe | `FEMSA/+/MES/KPI/#` · `FEMSA/+/MES/Maintance/#` · `FEMSA/+/Process/#` (legado) · `FEMSA/MES/KPI/#` · `FEMSA/MES/Maintance/#` (agregado de **planta completa**, sin línea) · **`FEMSA/+/ERP/AvailableQuantity`** (entrada — la escribe el MES) |
| Publica (retained) | `FEMSA/LineaX/ERP/{OrderNumber, OrderStatus, ScheduleStart, ScheduleEnd, ActualStart, ActualEnd, ReservedQuantity, OrderedQuantity}` — **nunca** `AvailableQuantity`, esa hoja es de solo lectura para el ERP |

- **KPI**: 9 hojas por línea — `Availability, Quality, Performance, OEE, TEEP,
  DT, MTTR, MTBF, MLT` — número plano (`0.7712`) o JSON `{"value": 0.7712}` →
  tabla `kpi_uns` (tableros en páginas *Producción* y *Base de datos*),
  sincronizable a la hoja `KPIs_UNS`. **Verificado contra el broker real
  (Coreflux, conectándose directo y suscribiendo a `#`):** las mismas 9 hojas
  de KPI y 4 de mantenimiento existen también a **nivel de planta completa**
  (`FEMSA/MES/KPI/...`, sin segmento de línea) — `interpretar_topico()` las
  reconoce como `linea='PLANTA'`, mismo `kpi_uns`, misma tabla en el
  dashboard (fila `PLANTA`), sin vista aparte.
- **Producción — camino PRINCIPAL: `ERP/AvailableQuantity`.** El ERP publica
  (retained) **una sola orden de fabricación activa por línea a la vez** —
  la más antigua `'abierta'` de ese SKU (`state_store.orden_activa()`) — con
  `OrderNumber` = nombre de la MO. El MES escribe `AvailableQuantity` como
  **valor absoluto** (no delta) de cuánto lleva producido de esa orden; el
  middleware nunca la publica, solo la lee (`_procesar_disponible()` →
  `state_store.actualizar_disponible()`). Cuando iguala o supera el objetivo:
  valida la `mrp.production` vinculada en Odoo (descuenta BOM — tapas,
  etiquetas, concentrado — y entra el terminado), marca la orden `cumplida →
  recibida_odoo` en SQLite, y **recién entonces** publica la siguiente orden
  de la cola de ese SKU — nunca dos activas a la vez en la misma línea.
  **Protección contra ruido** (necesaria: el broker real tiene un agente de
  IA — Coreflux Hub `Agent/*` — que puede inyectar valores arbitrarios en
  cualquier hoja, verificado): el avance debe ser monótono (valores que
  retroceden se ignoran) y se recorta al objetivo (valores que lo superan no
  disparan una sobreproducción fantasma). El middleware además **reafirma la
  orden activa cada 15 s** (`INTERVALO_REPUBLICAR`, autocuración si algo
  externo pisó la hoja `OrderNumber`/etc.).
- **Producción — contrato LEGADO: `Process/GoodCount`** (delta, no valor
  absoluto). La rama `Process` está libre en el YAML; por convención el
  middleware toma `GoodCount / Count / Produccion / Production / value` como
  unidades buenas → `state_store.acumular_produccion()` (wrapper delgado
  sobre `actualizar_disponible()`) → mismo camino de cierre de arriba. Sigue
  funcionando para pruebas locales rápidas, pero **ya no es necesario en
  producción**.
- Mapeo: `Linea1↔L1 (350 ml)` · `Linea2↔L2 (1.5 L)` · `Linea3↔L3 (garrafón)`.

**Sección de pruebas dedicada:** página **Pruebas → 4 · Producción (orden
activa)** — muestra la orden activa por línea, permite simular
`AvailableQuantity` de forma local (llamada directa, sin MQTT, para probar la
lógica al instante) o publicarlo de verdad al broker.

**Probar en 3 comandos:**
```bash
python middleware/run_middleware.py            # terminal 1
python tools/simulador_produccion.py --n 20    # terminal 2 (KPIs+GoodCount legado al UNS)
mosquitto_sub -h $MQTT_HOST -t "FEMSA/+/ERP/#" -v   # ver la rama ERP retenida
```
O todo con Docker: `docker compose -f docker-compose.dashboard.yml up -d`
(servicios `dashboard` + `middleware`, con `data/` y `middleware/` como
volúmenes para que la base ERP sobreviva reinicios).

**Otros tópicos del broker que NO son parte del UNS FEMSA** (vistos
suscribiendo a `#` directamente en Coreflux Hub, el panel del broker en
`:8080`): `celda/status/nodered` (liveness del bridge Node-RED, fuera del
namespace `FEMSA/` — relacionado con el pendiente "Flujo de Node-RED que
puentee Ignition → UNS" de `CLAUDE.md`, no bridgeado todavía) y `Agent/*`
(telemetría interna del propio Coreflux Hub con IA — irrelevante para
nuestro UNS, ignorar).

---

## 4 · Diagnóstico

Página **Pruebas** del dashboard: eco MQTT completo (publica y verifica
recepción en `FEMSA/_pruebas/Process/Ping`), autenticación + versión de Odoo y
PO de prueba, escritura/relectura en Sheets y lectura de `Parametros`.
Todo error muestra la causa y el remedio (ACL del broker, `ODOO_USER` faltante,
libro sin compartir, etc.).

Página **Finanzas**, sección "Caso de negocio": muestra si el motor está
gobernado por Sheets o corriendo en fallback local (`core.finanzas_negocio.
estado_fuente_financiera()`), qué claves de `Parametros` están activas y si
`CAPEX` trajo filas — con botón **🔄 Refrescar desde Sheets** para forzar una
relectura inmediata sin esperar el TTL de 60 s.

---

## 5 · Inventario en vivo (ERP local)

`integrations/state_store.py`, tablas `inventario_stock` (saldo ACTUAL, no
histórico) y `movimientos_stock` (bitácora). A diferencia de Odoo (§2), que
solo mueve stock al validar una `mrp.production` — completa o por backorder
parcial —, el ERP local se mueve con **cada** reporte real de producción, sin
esperar ningún sync:

- `state_store.actualizar_disponible()`/`acumular_produccion()` (el camino
  de `AvailableQuantity`/`GoodCount`, ver §3) llaman
  `_aplicar_produccion_a_stock(sku, delta_unidades, referencia)` en cada
  avance: suma `delta_unidades` al producto terminado (`ajustar_stock
  ("producto", sku, ...)`) y resta de cada componente de `data/bom.csv` la
  cantidad proporcional (`cantidad_por_unidad * delta_unidades`,
  `ajustar_stock("componente", ...)`).
- Página **Órdenes Odoo**: al recibirse una PO de insumos
  (`res.get("recibida")`), suma cada línea del pedido a la materia prima
  (`motivo="recepcion_po"`).
- Página **Ventas y Facturación**: al entregarse una venta
  (`res.get("entregada")`), resta la cantidad vendida del producto terminado
  (`motivo="venta_entrega"`).

`state_store.ajustar_stock(tipo, codigo, delta, motivo, ...)` es el único
punto de escritura — upsert en `inventario_stock` + fila en
`movimientos_stock` con el saldo resultante, para auditoría. Vista en vivo:
página **Inventario**, sección "📊 Stock actual (tiempo real)" (métricas de
producto terminado por SKU, tabla de materia prima con alerta si algún
componente queda en negativo — señal de que se produjo sin haber registrado
suficiente insumo recibido — y bitácora de movimientos). Ambas tablas nuevas
están en `state_store.TABLAS_ERP`, navegables también desde la página **Base
de datos**.

---

## 6 · RRHH (roster + resumen por rol, centralizados)

`integrations/rrhh_client.py` gestiona la hoja **`RRHH`** (2026-07: antes
`Personal` + `Empleados` separadas, consolidadas por pedido explícito del
dueño del proyecto — ver decisión #17 de `CLAUDE.md`) — integración separada
de `sheets_client.Contabilidad`, no comparte código.

La hoja tiene 4 secciones marcadas, localizadas por nombre (mismo patrón que
`leer_capex()`/`leer_apu_ingenieria()`, no por rango fijo):
- **RESUMEN POR ROL**: agregado por rol/fase (conteo, ARL clase, salario
  base estimado, costo total — el que gobierna `NOMINA_OPERACION_MES`/
  `NOMINA_IMPLEMENTACION_MES` en `Parametros`, ver §1). Se **deriva** del
  roster, no es un dato independiente.
- **ROSTER INDIVIDUAL**: detalle persona por persona (antes hoja
  `Empleados`); cada fila tiene un `rol_personal` que debe coincidir con las
  categorías del RESUMEN para reconciliar (`core.rrhh.
  reconciliar_con_personal`).
- **TASAS DE CARGA PRESTACIONAL**: componentes de nómina colombiana de
  referencia (EPS, pensión, caja, cesantías, intereses, prima, vacaciones,
  ARL por clase de riesgo — `core/rrhh.py:
  COMPONENTES_PRESTACIONALES_COMUNES`/`ARL_POR_CLASE`) — banda de mercado a
  validar contra la normativa vigente, no una tarifa fijada por ley.
- **RECONCILIACIÓN**: roster vs. resumen, por fase.

`rrhh_client.publicar_empleados()`/`agregar_empleado()` **siempre
reconstruyen la hoja completa** (`construir_filas_rrhh()`) porque el
RESUMEN se deriva del roster — no tiene sentido editar solo un pedazo.
`leer_nomina_personal()` lee la sección RESUMEN en modo solo lectura, nunca
escribe ahí directamente (solo vía la reconstrucción completa).

Columnas del roster: `cedula, nombre, cargo, rol_personal, linea, turno,
fase, fecha_ingreso, estado, salario_mensual_cop, telefono, email` —
`salario_mensual_cop` es el **costo total empleador** (ya con carga
prestacional), no el salario base; el desglose vive en la sección de tasas.
Fallback
sin Sheets: `data/empleados.csv` (mismo esquema).

### Réplica laboral a Odoo 19

`OdooClient.sincronizar_empleados()` toma el roster vivo de `RRHH` y hace
upsert idempotente por cédula en `hr.employee`; Odoo 19 materializa la relación
laboral en `hr.version` (no `hr.contract`). Crea/reusa departamentos y cargos,
calcula el salario base implícito desde el costo empleador y conserva la
trazabilidad Ulogix en campos `x_ulogix_*`. Solo desactiva empleados previamente
marcados como administrados por Ulogix que ya no estén en Sheets. La página
*RRHH* y `tools/sincronizar_rrhh_odoo.py` exponen esta sincronización.

La instalación tiene `hr_payroll`, pero una estructura salarial colombiana
debe configurarse y validarse legalmente antes de generar `hr.payslip`; el ERP
no inventa reglas salariales. `OdooClient.estado_nomina()` muestra empleados,
versiones, estructuras y recibos para que esta condición sea visible.

## 7 · QA de integraciones reales

`tools/qa_erp_funcional.py --flujo-completo` comprueba Odoo, Sheets y MQTT y
crea/reutiliza referencias `QA-FULL/*`: compra, recepción, factura de proveedor,
MO con BOM, venta, entrega y factura de cliente. En Odoo 19 la facturación de
venta usa el asistente público `sale.advance.payment.inv`. Como XML-RPC puede
reportar un Fault de serialización después de ejecutar el asistente, el cliente
relee `account.move` por `invoice_origin`; esa relectura determina el éxito.
Antes de contabilizar, toda factura borrador recibe `invoice_date`.
