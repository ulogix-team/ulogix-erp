# Integración de APIs — Suite Ulogix Fontibón

Guía definitiva para conectar las tres integraciones. Las credenciales viven
**solo** en `.env` y `config/google_service_account.json` (nunca en el código);
Docker las monta con `env_file` y volúmenes.

---

## 1 · Google Sheets (cuenta de servicio)

**Cómo funciona.** La app no usa tu cuenta personal: usa una *service account*
(`ulogix-sheets-admin@ulogix-femsa.iam.gserviceaccount.com`) cuyo JSON de
credenciales ya está en `config/google_service_account.json`. gspread firma un
JWT con esa llave privada contra `oauth2.googleapis.com` y opera el libro como
un editor más. Por eso el único requisito es **compartir el libro con ese
correo**.

**Pasos (una sola vez):**
1. Sube `Modelo_FEMSA_Ulogix_2026.xlsx` (repo `femsa-modelo-financiero/salida/`)
   a Google Drive y ábrelo → *Archivo → Guardar como hoja de cálculo de Google*.
2. Botón **Compartir** → agrega como **Editor**:
   `ulogix-sheets-admin@ulogix-femsa.iam.gserviceaccount.com`
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
| Financiero | `Parametros` (pares clave-valor: TRM, TMAR, nómina, otros fijos, vidas útiles, unit economics por SKU...) | **Sheets → ERP** | `leer_parametros()` | pares clave-valor, cualquier fila |
| Financiero | `CAPEX` (tabla: sección, línea, activo, cantidad, moneda, costo_unitario, vida_años, categoría_dep) | **Sheets → ERP** | `leer_capex()` | tabla, encabezado reconocido por nombre de columna |
| Financiero | `Licencias` (`CAPEX software capitalizable`, `OPEX mensual licencias` — última celda no vacía de la fila) | **Sheets → ERP** | `leer_licencias()` | filas etiquetadas, sin columna fija |
| RRHH | `Empleados` (roster individual — ver `integrations/rrhh_client.py`) | ERP → Sheets *(alta)* / **Sheets → ERP** *(lectura)* | `leer_empleados()` / `publicar_empleados()` / `agregar_empleado()` | reemplazo o append, sin fórmulas dependientes |
| Financiero | `APU_Ingenieria` (costos de ingeniería que cobra ULogix, justificados por AIU) | ERP → Sheets | `tools/publicar_apu_ingenieria.py` (escribe) / `leer_apu_ingenieria()` (lee, solo exhibición) | reemplazo, sin fórmulas dependientes |

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
| `crecimiento_demanda` | `CRECIMIENTO_DEMANDA_ANUAL` |
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
| `precio_p1_330ml` / `precio_p2_pet15` / `precio_p3_garrafon` | `precio_venta_cop_<SKU>` |

`VIDA_equipos`/`VIDA_automatizacion`/`VIDA_servicios`/`VIDA_intangibles`/
`VIDA_software` y `costo_material_cop_<SKU>` **no tienen hoy una fila
equivalente en el libro real** — quedan solo con el default local hasta que
se agreguen (con esos mismos nombres canónicos, no hace falta alias). Esta
hoja **no** gobierna el maestro físico que usa Odoo/MRP
(`data/maestro_productos.csv` vía `core/forecast.cargar_maestro()`) — solo
las unit economics del caso de negocio de `core/finanzas_negocio.py`; ver
decisión de diseño #3 en `CLAUDE.md`.

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
**`Tiempos` y `OEE_TEEP` son DOCUMENTALES** (referencia de ingeniería del
estudio corregido, no conectadas) y **el ERP no gestiona OEE/TEEP**: esos
KPIs solo llegan por MQTT según el UNS a `KPIs_UNS`.
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

**`.env` (ya cargado):**
```
ODOO_URL=https://ulogix-admin.odoo.com
ODOO_DB=ulogix-admin              # en odoo.com la BD se llama como el subdominio
ODOO_USER=TU_CORREO_DE_LOGIN_ODOO # ← ÚNICO dato pendiente: tu correo de login
ODOO_API_KEY=36793ebc3101d9c6edf4d3b4100af97c85f7e58c
```
> Si la autenticación falla con usuario/clave correctos, confirma el nombre real
> de la BD: entra a `https://ulogix-admin.odoo.com/web/database/selector` o
> mira `web.base.url` en Ajustes técnicos.

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
PO↔MO (`mo_id`/`mo_name`) para que el middleware sepa cuál validar. Sin
credenciales la suite opera en `dry-run` y registra todo en SQLite.

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

**Broker:** `100.123.104.31:1883` (el de tu stack). Regla de red del proyecto:
fuera de Docker se usa la **IP LAN** (no `localhost` ni hostnames de servicios
Docker); dentro de docker-compose sí resuelven los nombres de servicio.

**El árbol del UNS es tu YAML** (`config/uns_femsa.yaml`, guardado tal cual).
El middleware:

| Acción | Tópicos |
|---|---|
| Se suscribe | `FEMSA/+/MES/KPI/#` · `FEMSA/+/MES/Maintance/#` · `FEMSA/+/Process/#` · `FEMSA/MES/KPI/#` · `FEMSA/MES/Maintance/#` (agregado de **planta completa**, sin línea) · legado `plant/+/production` |
| Publica (retained) | `FEMSA/LineaX/ERP/{OrderNumber, OrderStatus, ScheduleStart, ScheduleEnd, ActualStart, ActualEnd, AvailableQuantity, ReservedQuantity, OrderedQuantity}` |

- **KPI**: 9 hojas por línea — `Availability, Quality, Performance, OEE, TEEP,
  DT, MTTR, MTBF, MLT` — número plano (`0.7712`) o JSON `{"value": 0.7712}` →
  tabla `kpi_uns` (tableros en páginas *Producción* y *Base de datos*),
  sincronizable a la hoja `KPIs_UNS`. **Verificado contra el broker real
  (Coreflux, conectándose directo y suscribiendo a `#`):** las mismas 9 hojas
  de KPI y 4 de mantenimiento existen también a **nivel de planta completa**
  (`FEMSA/MES/KPI/...`, sin segmento de línea) — `interpretar_topico()` las
  reconoce como `linea='PLANTA'`, mismo `kpi_uns`, misma tabla en el
  dashboard (fila `PLANTA`), sin vista aparte.
- **Producción**: la rama `Process` está libre en el YAML; por convención el
  middleware toma `GoodCount / Count / Produccion / Production / value` como
  unidades buenas → descuenta la PO abierta de la línea (FIFO) → al completarla
  la recibe en Odoo → **publica la rama ERP retained** (cualquier consumidor
  nuevo — Ignition, Tecnomatix, Grafana — recibe el último estado al suscribirse).
- Mapeo: `Linea1↔L1 (350 ml)` · `Linea2↔L2 (1.5 L)` · `Linea3↔L3 (garrafón)`.

**Probar en 3 comandos:**
```bash
python middleware/run_middleware.py            # terminal 1
python tools/simulador_produccion.py --n 20    # terminal 2 (KPIs+GoodCount al UNS)
mosquitto_sub -h 100.123.104.31 -t "FEMSA/+/ERP/#" -v   # ver la rama ERP retenida
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

## 5 · RRHH (roster de empleados)

`integrations/rrhh_client.py` gestiona la hoja `Empleados` (roster individual)
como una integración separada de `sheets_client.Contabilidad` — no comparte
código porque no tiene rangos fijos ni fórmulas dependientes (se puede
`clear`+`append` sin romper nada, a diferencia de `Demanda`/`Inventarios`).

**No confundir con la hoja `Personal`** (agregado por rol: conteo, costo
unitario, costo total, fase — la que ya gobierna `NOMINA_OPERACION_MES`/
`NOMINA_IMPLEMENTACION_MES` en `Parametros`, ver §1). `Empleados` es el
detalle persona por persona; cada fila tiene un `rol_personal` que debe
coincidir con las categorías de `Personal` para que la página **RRHH**
pueda reconciliar ambas (`core.rrhh.reconciliar_con_personal`,
`rrhh_client.leer_nomina_personal()` — lee `Personal` en modo solo lectura,
nunca escribe ahí). Si un usuario agrega/quita gente en `Empleados` sin
actualizar el conteo/costo en `Personal` (o viceversa), la página lo marca
como descuadrado.

Columnas de `Empleados`: `cedula, nombre, cargo, rol_personal, linea, turno,
fase, fecha_ingreso, estado, salario_mensual_cop, telefono, email`. Fallback
sin Sheets: `data/empleados.csv` (mismo esquema).
