---
name: integraciones-erp-ulogix
description: Trabajar con las integraciones externas del proyecto Ulogix — Odoo (XML-RPC, productos, BOM, órdenes de compra, recepciones) y Google Sheets (cuenta de servicio, publicación de hojas). Úsala SIEMPRE que se mencione Odoo, XML-RPC, purchase.order, mrp.bom, product.template, bootstrap, API key de Odoo, Google Sheets, gspread, cuenta de servicio, spreadsheet, publicar al libro, o los módulos integrations/odoo_client.py, integrations/sheets_client.py, integrations/state_store.py, tools/bootstrap_odoo.py — incluso si el usuario solo dice "no se crea la orden" o "no se actualiza el Excel".
---

# Integraciones: Odoo y Google Sheets

## Odoo (XML-RPC)

**Endpoints:** `/xmlrpc/2/common` (authenticate) y `/xmlrpc/2/object`
(`execute_kw` sobre cualquier modelo). La **API key funciona como contraseña**;
el usuario sigue siendo el correo de login.

`.env`: `ODOO_URL=https://ulogix-admin.odoo.com` · `ODOO_DB=ulogix-admin` ·
`ODOO_USER=ulogixteam@gmail.com` · `ODOO_API_KEY=...`

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

### Modo dry-run

Sin credenciales (o forzando `settings.DRY_RUN_FORZADO = True`), todo se registra
en SQLite sin tocar Odoo. La verificación (`tools/verificacion.py`, pasos 7-8)
**fuerza dry-run a propósito**: prueba la *lógica*, no la conectividad. La
conectividad real se prueba en la página 7 del dashboard.

## Google Sheets (cuenta de servicio)

No usa cuenta personal: usa una *service account*
(`ulogix-sheets-admin@ulogix-femsa.iam.gserviceaccount.com`), cuyo JSON está en
`config/google_service_account.json`. gspread firma un JWT con esa llave y opera
el libro como un editor más → **el único requisito es compartir el libro con ese
correo como Editor**.

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

`integrations/state_store.py` — 7 tablas: `pronosticos`, `plan_compras`,
`inventario_politicas`, `po_tracking`, `eventos_produccion`, `kpi_uns`,
`log_acciones`. Docker la monta como volumen para que sobreviva reinicios.
Navegable en la página 8 del dashboard.

## Diagnóstico

La **página 7 (Pruebas)** verifica las tres integraciones en vivo: eco MQTT
round-trip, `authenticate` + versión de Odoo + PO de prueba, y escritura/relectura
en Sheets + lectura de `Parametros`. Cada error muestra causa y remedio.

## Seguridad

**Nunca** commitear `.env` ni `config/google_service_account.json`. Las
credenciales actuales son de desarrollo y se rotarán.
