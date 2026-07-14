---
name: integraciones-erp-ulogix
description: Trabajar con las integraciones externas del proyecto Ulogix — Odoo (XML-RPC, productos, BOM, órdenes de compra/venta, recepciones/entregas, facturación), Google Sheets (cuenta de servicio, publicación de hojas) y RRHH (roster de empleados). Úsala SIEMPRE que se mencione Odoo, XML-RPC, purchase.order, sale.order, mrp.bom, mrp.production, account.move, factura de cliente/proveedor, product.template, bootstrap, API key de Odoo, Google Sheets, gspread, cuenta de servicio, spreadsheet, publicar al libro, RRHH, empleados, roster, nómina, dotación, o los módulos integrations/odoo_client.py, integrations/sheets_client.py, integrations/state_store.py, integrations/rrhh_client.py, core/rrhh.py, tools/bootstrap_odoo.py — incluso si el usuario solo dice "no se crea la orden", "no se actualiza el Excel", "se duplicaron las órdenes" o "agregar un empleado".
---

# Integraciones: Odoo y Google Sheets

## Odoo (XML-RPC)

**Endpoints:** `/xmlrpc/2/common` (authenticate) y `/xmlrpc/2/object`
(`execute_kw` sobre cualquier modelo). La **API key funciona como contraseña**;
el usuario sigue siendo el correo de login.

`.env`: `ODOO_URL`/`ODOO_DB`/`ODOO_USER`/`ODOO_API_KEY` — valores reales solo
en `.env` local, nunca en archivos versionados (ver `.env.example`).

### Firma que la gente equivoca

```python
LineaPedido(nombre: str, default_code: str, cantidad: float,
            precio_unitario: float, uom: str = "un")
```
**No** existe el kwarg `sku` ni `precio`. (Fue un bug real en la página Pruebas.)

### Poblar desde cero

```bash
python tools/bootstrap_odoo.py --dry   # muestra el plan
python tools/bootstrap_odoo.py         # ejecuta
```
Es **idempotente** (busca por `default_code` antes de crear): instala las apps
que falten (purchase/stock/mrp), crea los 3 productos con EAN-13, los 16
componentes comprables con `product.supplierinfo` (precio, MOQ, lead time), los
proveedores y las listas de materiales (`mrp.bom`).

Es **robusto a versiones**: el tipo de producto cambió entre Odoo 17
(`detailed_type`) y 18 (`type` + `is_storable`); `_crear_producto()` prueba las
variantes en orden.

### Ordenes de fabricación (mrp.production)

`OdooClient.crear_orden_fabricacion(default_code_producto, cantidad, referencia)`
crea una `mrp.production` ligada a la `mrp.bom` del sku (creada por el
bootstrap). La PO de insumos (concentrados, etiquetas, tapas...) se **recibe
de inmediato** al crearse (`crear_orden_compra(..., recibir=True)` → confirma
+ `button_validate` del picking): la suite no modela el lead time real del
proveedor, así que el insumo queda disponible para que la MO lo reserve
(`action_assign`) en el mismo paso. Cuando la producción real llega por MQTT y
cubre la cantidad objetivo del lote, el middleware llama
`OdooClient.completar_orden_fabricacion(mo_id)` (`button_mark_done`): Odoo
descuenta los componentes de la BOM y da entrada al producto terminado.

El vínculo PO↔MO vive en `state_store.po_tracking` (columnas `mo_id`,
`mo_name`, `insumos_recibidos`), que la página *Órdenes Odoo* llena al crear
ambas órdenes (**una MO por producto+mes**, compartida entre los proveedores
de ese lote) y que `mqtt_middleware._procesar_produccion` usa para saber cuál
MO validar.

### Idempotencia (buscar antes de crear)

`crear_orden_compra`, `crear_orden_fabricacion` y `crear_orden_venta` llaman
primero a `OdooClient._buscar_orden_existente(modelo, campo_referencia,
referencia)`, que busca una orden **no cancelada** con la misma referencia
(`origin` en `purchase.order`/`mrp.production`, `client_order_ref` en
`sale.order`) antes de crear otra. Si el usuario reintenta o hace doble clic
en el dashboard, la orden se **reutiliza** (`modo: "existente"`) en vez de
duplicarse. Esto es un fix real: probando contra Odoo real en una sesión
terminamos con ~21 POs con el mismo `origin` porque cada corrida creaba
órdenes nuevas.

### Ventas y facturación (cuentas por cobrar/pagar)

El flujo completo es compra-insumo → fabricación → **venta → factura →
cobro**. `OdooClient.crear_orden_venta(cliente, lineas, referencia, ...)` crea
un `sale.order`, lo confirma, lo entrega (`entregar_orden_venta` — misma
lógica de `quantity_done`/`quantity`+`picked` que `recibir_orden`) y lo
factura (`facturar_orden_venta` — `sale.order._create_invoices` con fallback
a `action_invoice_create`, luego `account.move.action_post`). La página
*Ventas y Facturación* toma los lotes cuya MO quedó `recibida_odoo` y los
reparte entre los clientes de `data/clientes.csv` (columna `participacion`);
registra cada `sale.order` en `state_store.venta_tracking` (vinculado por
`mo_name`) para no vender el mismo lote dos veces.

Del lado de compras, `crear_orden_compra(..., facturar=True)` genera además
la **factura de proveedor** (`facturar_orden_compra` — `purchase.order.
action_create_invoice` + `action_post`) sobre la PO ya recibida: la cuenta
por pagar, no solo el movimiento de inventario.

### Modo dry-run

Sin credenciales (o forzando `settings.DRY_RUN_FORZADO = True`), todo se registra
en SQLite sin tocar Odoo. La verificación (`tools/verificacion.py`, pasos 7-9)
**fuerza dry-run a propósito**: prueba la *lógica*, no la conectividad. La
conectividad real se prueba en la página 7 del dashboard. La idempotencia
(búsqueda por referencia en Odoo) solo se ejerce fuera de dry-run — validarla
requiere una instancia real.

## Google Sheets (cuenta de servicio)

No usa cuenta personal: usa una *service account* de Google Cloud, cuyo JSON
está en `config/google_service_account.json` (`client_email` ahí dentro, no
versionado). gspread firma un JWT con esa llave y opera el libro como un
editor más → **el único requisito es compartir el libro con ese correo como
Editor**.

### Contrato de escritura (crítico)

| Método | Hoja | Modo |
|---|---|---|
| `publicar_demanda(mensual, escenario)` | `Demanda` | **rango fijo `A4:F16`** |
| `publicar_demanda_escenario(mensual, escenario)` | `DemandaEscenario` | **rango fijo `A4:F16`** |
| `publicar_inventarios(politicas)` | `Inventarios` | **rango fijo `A4:I8`** |
| `registrar_plan_compras(plan)` | `PlanCompras` | reemplazo |
| `registrar_produccion(eventos)` | `LibroProduccion` | append |
| `leer_parametros()` | `Parametros` | **lectura** — el libro gobierna al ERP |

Los **rangos fijos** usan `_escribir_rango()` (escritura posicional): las hojas
financieras referencian esas celdas con fórmulas y un `clear + append` las
rompería. **No cambiar a modo append.**

### Fallback

Si `SHEETS_SPREADSHEET_ID` no está configurado o falla la conexión, todo cae a
`data/contabilidad_local.xlsx` con la misma estructura — cero pérdida de datos.
Ojo: al reemplazar una hoja en el fallback, hay que borrarla y recrearla **en la
misma sesión** de openpyxl (un libro sin hojas visibles no se puede guardar).

## Base ERP (SQLite WAL)

`integrations/state_store.py` — 10 tablas: `pronosticos`, `plan_compras`,
`inventario_politicas`, `po_tracking`, `venta_tracking`, `eventos_produccion`,
`kpi_uns`, `inventario_stock`, `movimientos_stock`, `log_acciones`.
`inventario_stock` es el saldo ACTUAL de producto terminado/materia prima
(se mueve con cada avance real de producción, no solo al cerrar una orden —
ver decisión #16 de AGENTS.md); `movimientos_stock` es su bitácora. Docker
monta la base como volumen para que sobreviva reinicios. Navegable en la
página 8 del dashboard.

## Diagnóstico

La **página 7 (Pruebas)** verifica las tres integraciones en vivo: eco MQTT
round-trip, `authenticate` + versión de Odoo + PO de prueba, y escritura/relectura
en Sheets + lectura de `Parametros`. Cada error muestra causa y remedio. La
**página 9 (Ventas y Facturación)** muestra en pantalla (no solo en el log)
cuando falla la entrega o la factura de una orden de venta/compra.

## RRHH (roster + resumen por rol, centralizados en hoja `RRHH`)

2026-07: `Personal` (agregado) + `Empleados` (detalle) se consolidaron en
UNA hoja `RRHH`, con 4 secciones marcadas (RESUMEN POR ROL / ROSTER
INDIVIDUAL / TASAS DE CARGA PRESTACIONAL / RECONCILIACIÓN) — ver decisión
#17 de `AGENTS.md`. `integrations/rrhh_client.py` — conexión propia a
gspread (no reusa `sheets_client.Contabilidad`), lee cada sección por
nombre (mismo patrón que `leer_capex()`), y **siempre reconstruye la hoja
completa al escribir** (el resumen se deriva del roster, no tiene sentido
editar solo un pedazo). Fallback `data/empleados.csv` para el roster.
`leer_empleados()` / `publicar_empleados(df)` / `agregar_empleado(**campos)`
/ `leer_nomina_personal()` (lee la sección RESUMEN, solo lectura).

`core/rrhh.py: reconciliar_con_personal()` compara el roster contra el
resumen — la página **10 (RRHH)**, sección 3, muestra si cuadran. Cada
persona tiene un `rol_personal` que debe coincidir con las categorías del
resumen. `core/rrhh.py` también trae la carga prestacional colombiana de
referencia (`COMPONENTES_PRESTACIONALES_COMUNES`/`ARL_POR_CLASE`/
`desglosar_costo_empleador()`) — `salario_mensual_cop` del roster es el
costo total empleador YA cargado, no el salario base.

## Seguridad

## RRHH en Odoo y QA real (2026-07)

La hoja `RRHH` es la fuente viva. `OdooClient.sincronizar_empleados()` replica
el roster por cédula, sin duplicar, en `hr.employee` y `hr.version`; crea/reusa
departamentos y cargos y conserva rol, línea, turno, fase, estado, clase ARL,
costo empleador y salario base implícito en campos `x_ulogix_*`. Ejecutar con
`python tools/sincronizar_rrhh_odoo.py`. Odoo 19 usa `hr.version`, no
`hr.contract`. No crear reglas salariales colombianas por aproximación: si
`estado_nomina()` reporta cero estructuras, el maestro está integrado pero los
recibos `hr.payslip` quedan bloqueados hasta validar la estructura legal.

`python tools/qa_erp_funcional.py --flujo-completo` valida servicios reales e
idempotentes: Sheets, maestros/BOM/stock/clientes/RRHH, MQTT y el ciclo
PO→recepción→factura proveedor→MO→SO→entrega→factura cliente. En Odoo 19 la
factura de venta usa `sale.advance.payment.inv`; puede ejecutar y luego devolver
Fault al serializar `None`, así que siempre releer `account.move` antes de
declarar error. Toda factura borrador recibe `invoice_date` antes de `action_post`.

El maestro físico/comercial operativo sale de `Maestro_Productos` en Sheets.
`data/maestro_productos.csv` solo es seed/fallback con `EXTERNAL_ONLY=false`.

**Nunca** commitear `.env` ni `config/google_service_account.json`. Las
credenciales actuales son de desarrollo y se rotarán.
