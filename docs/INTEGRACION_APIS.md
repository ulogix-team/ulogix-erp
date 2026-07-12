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

**Contrato de hojas (por área del ERP).** La app **lee** `Parametros` y
**escribe**:

| Área | Hoja | Método | Rango |
|---|---|---|---|
| Ventas | `Demanda` (pronóstico Base) | `publicar_demanda()` | **fijo A4:F16** |
| Ventas | `DemandaEscenario` (escenario activo) | `publicar_demanda_escenario()` — se dispara al **Activar** en la página Escenarios | **fijo A4:F16** |
| Inventario | `Inventarios` (política s,Q) | `publicar_inventarios()` — al simular en la página Inventario | **fijo A4:I8** |
| Compras | `PlanCompras` | `registrar_plan_compras()` | reemplazo |
| Producción | `LibroProduccion` / `ResumenMensual` / `KPIs_UNS` | middleware/sync | append/reemplazo |

Los rangos **fijos** existen porque las hojas financieras (`ER_Proyecto`,
`Flujo_Caja`, `Balance`, `FinancieroEscenario`, `Inventarios·rotación`)
referencian esas celdas con fórmulas: la app escribe posicionalmente sin
romperlas. **`Tiempos` y `OEE_TEEP` son DOCUMENTALES** (referencia de
ingeniería del estudio corregido, no conectadas) y **el ERP no gestiona
OEE/TEEP**: esos KPIs solo llegan por MQTT según el UNS a `KPIs_UNS`.
Si el ID no está configurado, todo cae a un Excel local
(`data/contabilidad_local.xlsx`) con la misma estructura: cero pérdida.

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
Junto con esa PO se crea **una orden de fabricación por producto y mes**
(`mrp.production`, ligada a la `mrp.bom` del SKU creada por
`bootstrap_odoo.py`), confirmada y con los componentes **reservados**
(`action_assign`) contra ese stock recién recibido. El middleware, al
completarse la producción real vía UNS, **valida la orden de fabricación**
(`button_mark_done`): Odoo descuenta los componentes de la BOM y da entrada al
producto terminado. `integrations.state_store.po_tracking` guarda el vínculo
PO↔MO (`mo_id`/`mo_name`) para que el middleware sepa cuál validar. Sin
credenciales la suite opera en `dry-run` y registra todo en SQLite.

---

## 3 · MQTT — UNS FEMSA

**Broker:** `100.123.104.31:1883` (el de tu stack). Regla de red del proyecto:
fuera de Docker se usa la **IP LAN** (no `localhost` ni hostnames de servicios
Docker); dentro de docker-compose sí resuelven los nombres de servicio.

**El árbol del UNS es tu YAML** (`config/uns_femsa.yaml`, guardado tal cual).
El middleware:

| Acción | Tópicos |
|---|---|
| Se suscribe | `FEMSA/+/MES/KPI/#` · `FEMSA/+/MES/Maintance/#` · `FEMSA/+/Process/#` · legado `plant/+/production` |
| Publica (retained) | `FEMSA/LineaX/ERP/{OrderNumber, OrderStatus, ScheduleStart, ScheduleEnd, ActualStart, ActualEnd, AvailableQuantity, ReservedQuantity, OrderedQuantity}` |

- **KPI**: número plano (`0.7712`) o JSON `{"value": 0.7712}` → tabla `kpi_uns`
  (tableros en páginas *Producción* y *Base de datos*), sincronizable a la hoja
  `KPIs_UNS`.
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

---

## 4 · Diagnóstico

Página **Pruebas** del dashboard: eco MQTT completo (publica y verifica
recepción en `FEMSA/_pruebas/Process/Ping`), autenticación + versión de Odoo y
PO de prueba, escritura/relectura en Sheets y lectura de `Parametros`.
Todo error muestra la causa y el remedio (ACL del broker, `ODOO_USER` faltante,
libro sin compartir, etc.).
