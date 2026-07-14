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
                           SQLite ERP (10 tablas)
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
| `integrations/rrhh_client.py` | Roster + resumen por rol: hoja `RRHH` de Sheets (consolidada) + fallback `data/empleados.csv` |
| `integrations/state_store.py` | SQLite WAL, 10 tablas ERP (incl. `inventario_stock`/`movimientos_stock`, stock en vivo) |
| `tools/verificacion.py` | **QA de 17 pasos — correr siempre antes de dar algo por bueno** |
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
   verificacion.py`, paso "Caso de negocio", exige actualmente
   `payback_simple_meses == 28`, alineado con los precios vivos vigentes).
   El generador del libro hermano
   (`../femsa-modelo-financiero`) sigue importando esas constantes, pero ahora
   son solo el **seed** con el que se puebla el libro la primera vez, no la
   fuente de verdad en operación — no vuelvas a llamarlo "fuente única" en
   código o docs nuevos. Contrato completo de columnas en
   `docs/INTEGRACION_APIS.md` §1 y en el skill `modelo-financiero-ulogix`.
   El maestro físico/comercial operativo también vive ahora en la hoja
   `Maestro_Productos`; el CSV es únicamente semilla/fallback cuando
   `EXTERNAL_ONLY=false` (ver decisión #24).
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
   los dos totales de esa hoja. Verificado end-to-end tras el recorte de
   alcance de la decisión #15 y quitar el crecimiento de demanda (decisión
   #20): 84 filas de CAPEX real leídas correctamente (antes 25 — sin
   lavadoras ni inspección de línea, celdas robóticas a detalle de BOM
   real), VPN $15.935 M / TIR 83.8 % / ROI 242.8 % / payback 21 m con datos
   en vivo.
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
    justificó de abajo hacia arriba. **2026-07: ahora es un modelo vivo**:
    cantidades, tarifas y porcentajes AIU son entradas; subtotales/AIU/totales
    son fórmulas; la mano de obra propia toma su tarifa desde `RRHH`; y el
    `costo_unitario` de las 3 filas `Servicios` de `CAPEX` referencia el total
    correspondiente de `APU_Ingenieria`. Editar el APU propaga a CAPEX →
    depreciación → flujo → indicadores. El motor Python no lee APU directamente:
    sigue leyendo `CAPEX`, que es el punto de integración.
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
15. **2026-07: alcance del CAPEX recortado — sin lavadoras ni inspección de
    línea; celdas robóticas a detalle de BOM real.** Pedido explícito del
    dueño del proyecto: ya no se compran lavadoras/prewash retornables ni
    equipos de inspección de línea (envase vacío/lleno, visión artificial).
    Filas afectadas de `CAPEX` puestas en `cantidad=0` (no se borran, se
    conserva el registro de qué se evaluó y excluyó — mismo patrón que ya
    venía usando el usuario): `Upgrade lavadora retornable / prewash` (L2),
    `Inspeccion envase vacio` (L2), `Bloc soplado-llenado-tapado` (L3),
    `Inspeccion botella llena` (L3), `Lavado y sanitizacion garrafon` (L7).
    La fila `Llenado / taponado / inspeccion garrafon` (L7) se **separó** en
    dos filas — `Llenado / taponado garrafon` (activa) e `Inspeccion
    garrafon` (`cantidad=0`) — mismo patrón que ya usaba el libro en L2/L3;
    el precio de cada mitad es un supuesto documentado en el comentario junto
    a `CAPEX_FILAS` en `core/finanzas_negocio.py` (garrafón es la línea más
    lenta — 480 und/h — así que un chequeo de nivel de llenado es más simple
    y barato que la inspección óptica de L2/L3; no hay desglose real del
    proveedor). Las 2 filas resumen de `Celdas roboticas (BOM real)` (GANTRY
    L1-L2 y ROBOT ARTICULADO L3) se **expandieron a 60 filas de detalle**
    (36 + 24 ítems) a partir de las BOM de ingeniería reales de las celdas de
    paletizado — cada fila es un componente con su fabricante/referencia; de
    paso se corrigió la moneda de esas filas de `USD` a `USD*` (son
    cotizaciones reales de la BOM, no un benchmark — no debían llevar el
    factor `FACTOR_RFQ`). Publicado a Sheets con `tools/
    actualizar_capex_celdas.py` (preserva el encabezado real, regenera la
    fórmula de `CAPEX COP` por fila según moneda, y el pie de Subtotal/
    Contingencia/Total). El caso de negocio mejoró sustancialmente porque el
    EBITDA incremental es demand-driven (no cambia con el CAPEX) mientras el
    CAPEX casi se redujo a la mitad — ver cifras nuevas en "Estado actual".
16. **Inventario en vivo (ERP local + Odoo) — se mueve a medida que se
    produce, no solo al cerrar la orden.** Pedido explícito: "tanto ODOO
    como el ERP" deben mostrar productos/unidades/materia prima
    actualizados con la producción real, no solo al completar un lote.
    - **ERP local**: tabla nueva `state_store.inventario_stock` (+ bitácora
      `movimientos_stock`). Cada avance real de `AvailableQuantity`/
      `GoodCount` (`actualizar_disponible()`/`acumular_produccion()`) llama
      `_aplicar_produccion_a_stock()`: suma producto terminado y resta
      materia prima según `data/bom.csv` (`cantidad_por_unidad`) — no espera
      a que la orden complete. La recepción de una PO de insumos (página
      *Órdenes Odoo*) suma materia prima; la entrega de una venta (página
      *Ventas y Facturación*) resta producto terminado. Vista en vivo:
      página *Inventario*, sección "📊 Stock actual (tiempo real)".
    - **Odoo**: cada `INTERVALO_SYNC_ODOO` (60 s, `mqtt_middleware.py`),
      `sincronizar_parciales_odoo()` postea a Odoo el avance acumulado desde
      el último sync usando el mecanismo **nativo de backorder** de
      `mrp.production` (`odoo_client.avanzar_produccion_parcial`): fija
      `qty_producing` parcial, marca los `stock.move` de componentes
      recogidos en esa proporción, `button_mark_done` (que con
      `qty_producing < product_qty` no cierra sino que dispara el wizard
      `mrp.production.backorder`) y completa ese wizard con
      `to_backorder=True` — la orden original queda `done` solo por esa
      porción (descuenta BOM, entra terminado) y Odoo crea sola una MO
      backorder por el remanente (mismo `origin`), que
      `po_tracking.mo_id`/`mo_name` pasa a rastrear. El cierre FINAL de la
      orden sigue siendo `completar_orden_fabricacion` (sin backorder, cubre
      todo lo que reste) — no cambió. **Verificado en vivo contra Odoo
      real** (saas-19.3): cadena de 4 avances parciales + cierre final suma
      exacto al objetivo, cada tramo con su propio `stock.move` `done`. Nota
      técnica: la respuesta XML-RPC de `action_backorder` a veces trae un
      `Fault` de marshalling ("cannot marshal None") aunque la operación SI
      se ejecutó — `avanzar_produccion_parcial` no confía en esa respuesta,
      relee el estado para confirmar.
    - `tools/verificacion.py` paso 17 cubre la lógica local (stock sube/baja
      correctamente, cola de sync a Odoo se marca y despeja) en dry-run; el
      mecanismo de backorder contra Odoo real se probó aparte (no es
      reproducible en dry-run, depende del wizard real de Odoo).
17. **2026-07: reconstrucción grande del libro de Sheets — Tiempos consolidada
    con OEE +5% EXACTO por línea, RRHH centralizado con nómina colombiana
    completa, CAPEX en bloques por área, hoja Dashboard nueva.** Pedido
    explícito del dueño del proyecto, con el archivo fuente real
    `Tiempos_Fontibon_Corregido.xlsx` (10 hojas de auditoría de ingeniería
    completa) como insumo.
    - **Hoja `Tiempos` reconstruida** (`tools/actualizar_tiempos_oee.py`):
      consolida en UNA sola hoja, en 10 bloques, TODO el contenido del
      archivo fuente — memoria/metodología, las 8 correcciones de auditoría,
      parámetros y tiempos por línea, **MLT/VSM estación-por-estación**
      (contenido nuevo, no existía en el ERP), OEE bottom-up, capacidad vs.
      demanda, **máquinas y referencias comerciales reales** por etapa
      (KRONES/HEUFT/Festo/Satech/ReeR/Werma/EAO, contenido nuevo), glosario
      y referencias. La hoja `OEE_TEEP` (redundante, su contenido ya queda
      cubierto) se **borró**. **Bug real corregido**: `core/tiempos_oee.py:
      DATOS[...]["mlt_lote_h"]` tenía L2=16.44h/L3=14.9h, que NO coincidían
      con el archivo fuente (L2=19.26h/L3=15.57h) — ya corregido.
    - **Mejora de OEE, ahora ESTRICTAMENTE +5% relativo por línea** (antes
      una cifra plana de +3.9pp igual para las 3 líneas, que en realidad NO
      correspondía a un +5% relativo exacto porque cada línea parte de un
      OEE base distinto). `core/tiempos_oee.py: _mejora_pp_linea()` calcula
      el Δpp exacto por línea (L1 +3.856pp, L2 +3.825pp, L3 +3.769pp — cada
      uno repartido 50/30/20% entre disponibilidad/rendimiento/calidad) para
      que `oee_a_implementar = oee_base × 1.05` sea matemáticamente exacto,
      no aproximado. Cronograma de implementación nuevo
      (`CRONOGRAMA_MEJORA_OEE`) atado a las 4 fases de preoperación del
      CAPEX (`FASES_CAPEX`): el +5% se completa al cierre del mes 4, justo
      antes de la rampa del mes 5. La meta aspiracional de programa (≥86%)
      queda documentada aparte, sin confundirse con el +5% estricto.
    - **RRHH centralizado en una sola hoja `RRHH`** (antes `Personal` +
      `Empleados` separadas, ver decisión #10 — la separación conceptual
      detalle/agregado se mantiene, ahora en secciones de la misma hoja:
      RESUMEN POR ROL / ROSTER INDIVIDUAL / TASAS DE CARGA PRESTACIONAL /
      RECONCILIACIÓN). `integrations/rrhh_client.py` reescrito para leer por
      nombre de sección (mismo patrón que `leer_capex()`/
      `leer_apu_ingenieria()`) y escribir SIEMPRE reconstruyendo la hoja
      completa (el resumen se deriva del roster). **Carga prestacional
      colombiana agregada** (`core/rrhh.py:
      COMPONENTES_PRESTACIONALES_COMUNES`/`ARL_POR_CLASE`/
      `desglosar_costo_empleador()`): EPS 8.5% + pensión 12% + caja 4% +
      cesantías 8.33% + intereses cesantías 1% + prima 8.33% + vacaciones
      4.17% (SENA/ICBF exonerados, Ley 1607/2012, salarios <10 SMMLV) + ARL
      según clase de riesgo (I administrativo 0.522% · III supervisión
      2.436% · IV planta industrial 4.35% · V alto riesgo 6.96%) — banda de
      **referencia** de mercado/histórico a validar contra la normativa
      vigente, mismo criterio que el AIU de `APU_Ingenieria` (no es
      "tarifa fijada por ley" inmutable). Verificado que
      `NOMINA_OPERACION_MES`/`NOMINA_IMPLEMENTACION_MES` YA venían cargados
      con esta carga (la UI de *RRHH* ya decía "costo empleador", no salario
      base) — **el total NO cambió** ($85.915.382/$87.161.760), solo se
      justificó de abajo hacia arriba (mismo patrón que el AIU con CAPEX
      Servicios). Corrección a la nota original de este punto: se creyó que
      `Dep_Amort` ya era una fórmula SUMIF viva contra `CAPEX` por categoría
      que se autoactualizaba sola — **era falso**, ver decisión #18.
    - **`CAPEX` reorganizada en 8 bloques por área** dentro de la MISMA hoja
      (`tools/reorganizar_capex_areas.py`): título + subtotal por bloque,
      usando filas con `seccion` vacío (que `leer_capex()` ya salta) para
      los divisores — **cero cambios de valores**, verificado que
      `leer_capex()` sigue devolviendo las mismas 84 filas y el mismo total
      ($11.080.079.385 subtotal / $12.188.087.323 con contingencia).
    - **Hoja `Dashboard` nueva** (`tools/actualizar_dashboard.py`, primera
      pestaña del libro): resumen ejecutivo de una pantalla — demanda,
      capacidad/OEE, caso de negocio, RRHH, navegación del libro. **Bug de
      locale encontrado y corregido**: escribir números con coma como
      separador de miles (formato inglés, p. ej. `"279,150"`) con
      `value_input_option="USER_ENTERED"` en una hoja de locale colombiano
      (coma = decimal) hace que Sheets **reinterprete** el valor como
      279.15 y lo muestre mal — corregido usando `value_input_option="RAW"`
      para esta hoja (es texto ya formateado, no fórmulas).
    - **No se persigue formato uniforme en todas las hojas** — pedido
      explícito del dueño del proyecto de dejarlo así, no es un pendiente.
18. **2026-07: reparación de fórmulas rotas por la reconstrucción de la
    decisión #17 — root cause y arreglo estructural, no un parche.** Al
    reorganizar `CAPEX` en bloques y consolidar `Personal`+`Empleados` en
    `RRHH`, varias hojas quedaron con `#VALUE!`/`#REF!` en cascada
    (`Sensibilidad`, `Flujo_Caja`, `FinancieroEscenario`, `Reportes`,
    `ER_Proyecto`, `Dep_Amort`) — encontrado porque el dueño del proyecto
    señaló explícitamente "las hojas tienen que tener fórmulas funcionales,
    no solo los datos". Causas y arreglo (`tools/
    reparar_formulas_capex_rrhh.py`, `tools/convertir_capex_formulas.py`):
    - **Referencias a celda fija que se movió**: `CAPEX!$G$34` (el total
      viejo) y `Personal!$D$10`/`$D$11` (nómina Operación/Implementación,
      hoja ya borrada) apuntaban a celdas que ya no eran las correctas.
      Reemplazadas por `INDEX/MATCH` **por etiqueta de texto** (p. ej.
      `INDEX(CAPEX!$G:$G;MATCH("CAPEX TOTAL (con contingencia)";CAPEX!$C:$C;0))`)
      en vez de coordenadas fijas — sobreviven a que el usuario siga editando
      CAPEX (agregar/quitar filas), que es justo lo que dijo que iba a
      seguir haciendo. Ojo con el mapeo: `Personal!$D$10` era **Operación**
      y `$D$11` era **Implementación** (no al revés — se verificó contra la
      etiqueta real de la fila que consumía cada una, `ER_Proyecto` fila 12
      "Nomina operacion" vs. `Flujo_Caja` fila 9 "Equipo implementacion
      ULogix", antes de reparar, para no invertirlas).
    - **`Dep_Amort` SUMIF con rango angosto** (`CAPEX!$I$5:$I$29`, dimensionado
      para el CAPEX viejo de 25 filas): contaba de menos en silencio (sin
      error visible) desde la expansión del CAPEX a 84 filas, no solo desde
      la reorganización de esta sesión — **estaba mal desde antes**, se
      encontró al investigar esto. Ampliado a `$I$5:$I$300`.
    - **Root cause real, más profundo que las referencias movidas**: la
      columna `CAPEX COP` (G) y `costo_unitario` (F) de la hoja `CAPEX`
      mezclaban NÚMEROS reales con TEXTO formateado como moneda (p. ej.
      `"$90.000"` en vez de `90000`) — según qué script/persona escribió esa
      fila. Un `SUMIF`/multiplicación sobre una celda de texto la trata como
      0 o revienta en `#VALUE!`, sin aviso. **Arreglado en la raíz**: la
      columna G de `CAPEX` ahora es una fórmula viva por fila (`=IF(moneda=
      "COP";cant×costo;IF(moneda="USD*";cant×costo×TRM;cant×costo×TRM×
      FACTOR_RFQ))`, leyendo TRM/FACTOR_RFQ de `Parametros!$B$5`/`$B$6` en
      vivo), los subtotales por bloque son `=SUM(...)` sobre su rango, y el
      pie (Subtotal/Contingencia/Total) también son fórmulas
      (`Parametros!$B$27` para contingencia) — nada estático. La columna F
      se normalizó a número real en las 4 celdas que estaban en texto.
    - **`RRHH`: el RESUMEN por rol pasó de estático a fórmulas vivas**
      (`COUNTIFS`/`SUMIFS` sobre el bloque ROSTER INDIVIDUAL de la misma
      hoja) para conteo, costo unitario y costo total por rol, y el pie
      (Costo mensual OPERACIÓN/IMPLEMENTACIÓN, lo que lee `Parametros` para
      gobernar el motor financiero) es `SUMIF` sobre el RESUMEN — si el
      usuario edita el roster directo en Sheets, todo recalcula solo.
      `salario_base_cop`/`factor_prestacional_pct` quedan como valores
      calculados al publicar (no alimentan ningún otro cálculo, mismo
      criterio que el AIU de `APU_Ingenieria` — no hace falta que sean
      fórmula viva).
    - **Verificado exhaustivamente tras el arreglo**: todos los totales
      recalculados en vivo coinciden EXACTO con los valores conocidos de
      antes (CAPEX total $12.188.087.323, VPN Base $16.661M/TIR 85.7% en
      `Sensibilidad`, Nómina Operación $85.915.382/Implementación
      $87.161.760) — el arreglo no cambió ninguna cifra de negocio, solo
      las hizo recalcularse solas en vez de quedar pegadas por un script.
19. **2026-07: auditoría completa de las 23 hojas — "datos sueltos" vs.
    fórmula viva vs. dato legítimamente crudo/del ERP.** Pedido explícito
    del dueño del proyecto: "necesito que todos los datos que se calcularon
    no estén escritos sino tengan su fórmula y estén vinculados... revisa
    todas las hojas". Metodología: para cada hoja, se comparó cada celda
    numérica contra su fórmula (`value_render_option=FORMULA` vs
    `FORMATTED_VALUE`) y se barrió el libro completo buscando
    `#VALUE!/#REF!/#N/A/#DIV/0!/#ERROR!/#NAME?/#NUM!/#NULL!`.
    - **Resultado**: `Reportes`/`Modelo_Negocio` ya estaban 100% fórmula.
      `ER_Proyecto`/`Flujo_Caja`/`Balance`/`FinancieroEscenario` solo tenían
      literales en la fila de índice de mes (1-60, un rótulo, no un cálculo
      — correcto tal cual). `Sensibilidad` (factores de escenario),
      `Costos_Lote` (costos de insumo por lote) y `Dep_Amort` (vidas útiles
      en años) solo tenían literales en columnas de **entrada editable**
      (igual que `cantidad`/`costo_unitario` en `CAPEX` o `Parametros`) — no
      son cálculos, son las palancas que el usuario edita a mano, correcto
      dejarlas así. `Costos_Lote!Total lote`/`COSTO UNITARIO` ya eran
      `SUM`/división en vivo. **No había ningún cálculo real pegado como
      valor estático fuera de lo ya arreglado en la decisión #18.**
    - **2 bugs más del mismo patrón, encontrados por el barrido de
      errores**: `Tiempos` tenía 3 `#ERROR!` (la columna `justificacion` del
      bloque de mejora de OEE empieza con texto tipo `"+1.93pp A: ..."` —
      Sheets interpreta un valor que arranca con `+` como inicio de fórmula,
      convención heredada de Lotus 1-2-3, y revienta). Corregido:
      `tools/actualizar_tiempos_oee.py` pasó de `value_input_option=
      "USER_ENTERED"` a `"RAW"` (toda la hoja es texto/número documental
      estático, nunca fue pensada como fórmula viva — decisión #1/#17).
    - **`RRHH`: la sección RECONCILIACIÓN pasó de snapshot de Python a
      fórmulas vivas** (`SUMIFS` sobre el ROSTER + `SUMIF` sobre el RESUMEN,
      independientes entre sí, para que la reconciliación sea un chequeo
      real y no una tautología calculada dos veces en Python).
    - **`Dashboard`: leía el roster del CSV local (`data/empleados.csv`) en
      vez de la hoja `RRHH` en vivo** — bug real de desconexión, corregido
      para usar `integrations.rrhh_client.leer_empleados()` (hoja RRHH con
      fallback a CSV, como todo el resto del ERP). Se documentó
      explícitamente en la propia hoja que el bloque "Caso de negocio" del
      Dashboard usa el motor canónico `core.finanzas_negocio` (el mismo que
      valida `tools/verificacion.py` y la página *Finanzas*) — un modelo
      **paralelo y más completo** (D&A/impuestos/capital de trabajo
      explícitos) que las fórmulas nativas de `Sensibilidad`/`Flujo_Caja`/
      `ER_Proyecto` (modelo simplificado tipo seed original). Ambos
      convergen hoy en el mismo número pero son cálculos distintos **a
      propósito** — no se combinan/enlazan entre sí para no dar la falsa
      impresión de que es un solo cálculo.
    - **Qué se dejó correctamente SIN fórmula** (dato legítimo del ERP o
      entrada cruda, no un cálculo pendiente): `Demanda`/`DemandaEscenario`/
      `Inventarios`/`PlanCompras`/`LibroProduccion`/`ResumenMensual`/
      `KPIs_UNS` (el ERP/middleware las escribe directo, decisión #2/#16 —
      son la fuente, no un resultado derivado dentro de Sheets);
      `Parametros`/`Licencias`/las columnas de entrada de `CAPEX` (cantidad,
      moneda, costo_unitario) — el usuario las edita a mano por diseño,
      decisión #3; `Tiempos` es documental respecto al ERP/MQTT pero sus
      bloques cuantitativos son fórmulas vivas; `APU_Ingenieria` alimenta las
      3 filas de Servicios de CAPEX; el roster
      individual de `RRHH` — dato crudo persona por persona.
    - **Verificado**: barrido de errores en las 23 hojas → 0 errores;
      `tools/verificacion.py` 17/17 en verde; ninguna cifra de negocio
      cambió (mismos VPN/TIR/ROI/payback/CAPEX/nómina de siempre).
20. **2026-07: sin supuesto de crecimiento de demanda — la evaluación
    financiera sigue SIEMPRE la demanda que manda el ERP.** Pedido explícito
    del dueño del proyecto: "no quiero que se tenga ese crecimiento de la
    demanda en lo financiero... quiero que se siga la demanda que mande el
    ERP siempre". Antes, el horizonte de 60 meses del caso de negocio
    repetía el patrón de 12 meses del pronóstico/escenario activo pero
    **inflándolo** con un +1.5% anual compuesto en los meses 13-60 —
    existía en **dos motores independientes** a la vez, y había que apagarlo
    en los dos:
    - **Motor Python** (`core/finanzas_negocio.py`): se eliminó por completo
      `CRECIMIENTO_DEMANDA_ANUAL` (constante, alias `crecimiento_demanda`,
      entrada en `_CLAVES_PARAMETROS`/`_parametros()`) y el factor `crec`
      que multiplicaba la demanda en `flujos_desde_demanda()` — ahora el
      patrón de 12 meses se repite **idéntico** los 5 años, sin excepción,
      sin importar lo que diga Sheets.
    - **Motor nativo de Sheets** (`ER_Proyecto`/`FinancieroEscenario`, el
      modelo tipo seed, independiente del motor Python): tenía la MISMA
      idea aplicada en **~900 celdas de fórmula** (`=Demanda!...*(1+
      Parametros!$B$10)^N`) — en vez de tocar 900 fórmulas, se neutralizó
      en la raíz: `Parametros!crecimiento_demanda` (B10) → **0%** (con
      B10=0, `(1+0)^N=1` para cualquier N, así que el crecimiento
      desaparece sin romper ninguna fórmula que lo referencia). Verificado
      con lectura directa: mes 1 = mes 13 = mes 25 = mes 37 = mes 49 de
      `ER_Proyecto` dan exactamente el mismo número. La fila de Parametros
      se conserva (mismo patrón que el CAPEX en cantidad=0) con nota
      explicando que ya no se aplica.
    - **Nuevas cifras** (sin crecimiento, escenario Base): motor Python VPN
      $15.935 M / TIR 83.8 % E.A. / ROI 242.8 % / payback 21/24 m (baja
      desde $16.661 M/85.7 %/253.1 % — la caída es solo en años 2-5, el
      payback no se mueve porque ocurre temprano). El motor nativo de
      Sheets (`Sensibilidad`, escenario Base) baja más — $10.802 M/62.6 %
      — porque su estructura de fórmulas responde distinto a la demanda
      plana; **es la brecha esperada entre los dos modelos paralelos**
      (documentada desde antes, ver decisión #3 y el skill
      `modelo-financiero-ulogix`: nunca fueron el mismo cálculo, solo
      convergían cuando ambos tenían el mismo supuesto de crecimiento
      aplicado — al quitarlo de los dos, la estructura distinta de cada
      motor produce una brecha algo mayor que antes).
    - **De paso, se conectó `Parametros!nomina_operacion_mes`/
      `nomina_implementacion_mes` (B23/B24) con fórmula viva a `RRHH`**
      (`INDEX/MATCH` por etiqueta, mismo patrón robusto que el total de
      `CAPEX`) — antes eran copias estáticas de la vieja hoja `Personal`
      (ya no existe, decisión #17); si el roster de `RRHH` cambia, estas
      celdas ahora se actualizan solas, y con ellas el motor Python (que
      lee `Parametros`, no `RRHH` directo) y el motor nativo de Sheets
      (que ya referenciaba `Parametros!$B$16` para capital de trabajo, etc.
      — la nómina ahora también queda genuinamente en vivo de punta a
      punta). Se corrigió además una nota obsoleta en `Parametros!D32`
      ("hoja OEE_TEEP" → "hoja Tiempos", la primera ya no existe).

21. **2026-07: remediación de secretos expuestos en el repo público.**
    Encontrado durante una revisión de rutina: una API key real de Odoo, la
    URL/DB/correo real de la instancia, la IP LAN/Tailscale real del broker
    MQTT y del endpoint OPC-UA, el ID real del spreadsheet de Sheets y el
    `client_email` de la cuenta de servicio estaban **hardcodeados y
    commiteados** en `.env.example`, `docs/INTEGRACION_APIS.md`, ambos
    `SKILL.md` de integraciones/UNS, `README.md`, `tools/bootstrap_odoo.py`,
    `config/settings.py` (default de `OPCUA_ENDPOINT`) y
    `docker-compose.dashboard.yml` (comentario) — confirmado en el
    historial de git desde hace varios commits, incluido pusheado a
    `github.com/ulogix-team/ulogix-erp` (público). `.env` en sí y
    `config/google_service_account.json` **nunca** estuvieron versionados
    (correcto, siguen sin estarlo). Se redactó el árbol de trabajo completo
    reemplazando cada valor real por un placeholder genérico o una
    referencia a la variable de `.env` (`tu-ip-o-host-del-broker`,
    `tu-instancia.odoo.com`, `MQTT_HOST` en vez del IP literal, etc.) —
    `git grep` final confirma cero coincidencias de la API key, la IP, la
    URL/correo de Odoo, el ID del spreadsheet o el correo de la cuenta de
    servicio en archivos versionados. **No se reescribió el historial de
    git** (decisión explícita del dueño del proyecto: rotar la API key de
    Odoo por su cuenta en vez de purgar el historial) — el valor viejo
    sigue técnicamente visible en commits antiguos del remoto hasta que se
    rote. Si se vuelve a tocar cualquiera de estos archivos, **nunca**
    reintroducir un valor real — todos los ejemplos de aquí en adelante
    deben usar placeholders o `$MQTT_HOST`/`<ODOO_URL>`/etc.

22. **2026-07: hoja `Analisis_Paletizado` — caso de inversión paralelo,
    antes/después de automatizar paletizado + encajonado.** Pedido
    explícito: comparar, por línea, paletizado manual (operarios) vs.
    celda robótica ULogix (CAPEX + tarifa de servicios) vs. comprar una
    máquina comercial, incluyendo encajonado para retornables. Nuevo
    módulo puro `core/analisis_paletizado.py` + publicador
    `tools/publicar_analisis_paletizado.py` (mismo patrón que
    `APU_Ingenieria`, decisión #11). El análisis de paletizado es paralelo:
    no toca `CAPEX_FILAS` ni el caso de negocio principal — VPN/TIR del proyecto
    completo, decisión #20, no cambian). Alcance real de las 2 estaciones
    de FINAL de línea: paletizado en L1/L2/L3; encajonado (empacar
    producto lleno en canastilla) **solo en L1** — L2 es PET no retornable
    (bandeja/película, no canastilla) y L3 (garrafón 25 L) es demasiado
    grande para canastilla estándar, se paletiza a granel. La máquina de
    referencia que dio el dueño del proyecto (Krones Linapac-A-T-1600,
    bevmaq.es, EUR 14.000 usada) resultó ser, tras revisarla, una
    **desencajonadora** (retira botella vacía de canastilla al INICIO de
    línea, antes del lavado) — no una paletizadora ni un encajonador de
    producto lleno; se dejó documentado en la hoja como referencia
    ilustrativa de precio de mercado, no como sustituto funcional
    (confirmado con el dueño del proyecto antes de construir la hoja).
    CAPEX de las celdas de paletizado es el BOM real ya existente (GANTRY
    L1-L2 USD* 107.993 compartido, ROBOT L3 USD* 131.896, decisión #15); el
    CAPEX de una celda de encajonado para L1 (no existe en el proyecto) y
    los precios de máquinas comerciales son **estimaciones de ingeniería
    documentadas sin cotización real**, mismo tratamiento que el supuesto
    de split de L7 en decisión #15. Tarifa de servicios ULogix = AIU 27.5%
    (punto medio de la banda de mercado 25-30% ya validada en decisión #11)
    sobre el CAPEX de equipo de esta cadena de valor específica — no existía
    ningún concepto de "tarifa ULogix" antes de esta hoja, se definió por
    analogía directa con la metodología APU ya establecida. Resultado (TMAR
    18%, horizonte 10 años = vida útil de "equipos"): **ULogix gana a la
    opción comercial en las 3 líneas** por dos motores estructurales, no
    un supuesto forzado — (1) la celda GANTRY sirve a L1+L2 a la vez, una
    máquina comercial no; (2) el CAPEX ULogix parte de costeo directo de
    BOM (USD*, sin margen de venta) mientras el comercial es precio de
    lista (USD benchmark, con `FACTOR_RFQ`). L1 y L2 (ULogix) son
    rentables por sí solas (TIR 43.7 %/29.9 %, payback 2.2/3.1 años). **L3
    (ULogix) es marginal como decisión aislada** (TIR 3.2 %, por debajo de
    la TMAR, payback 8.45 años) — el brazo articulado es más caro que el
    GANTRY pero libera solo 2 operarios de 1 turno en la línea de menor
    volumen; sigue siendo defendible dentro del proyecto completo (el
    caso de negocio agregado se sostiene con el EBITDA demand-driven de
    las 3 líneas juntas, no con el ahorro de mano de obra de L3 aislado),
    pero no se pagaría sola si el criterio fuera únicamente esta decisión.

23. **2026-07: modo operativo externo estricto — Sheets/Odoo gobiernan; SQLite
    es solo caché técnica.** `EXTERNAL_ONLY=true` obliga a que RRHH, demanda,
    escenarios, inventarios planificados, unit economics, `Costos_Lote`,
    `LibroProduccion` y `KPIs_UNS` salgan de Google Sheets; no se degrada en
    silencio a CSV/Excel. Odoo gobierna BOM, proveedores, MOQ/lead time/precio,
    `stock.quant`, PO, MO, clientes, SO y facturas. Las páginas *Inventario*,
    *Órdenes Odoo*, *Producción MQTT*, *Ventas*, *RRHH* y *Fuentes del ERP*
    consultan esas APIs como fuente primaria. El middleware anexa a Sheets los
    KPIs y el delta válido de `AvailableQuantity` (no suma repetidamente el
    contador absoluto). La cola, secuencia, objetivo, avance absoluto y avance
    sincronizado viven en campos `x_ulogix_*` de `mrp.production`; el
    middleware puede reconstruirse desde Odoo aunque se borre SQLite. Los logs
    de SQLite quedan solo como diagnóstico técnico.

24. **2026-07: pipeline de demanda reproducible + maestros laborales en Odoo.**
    Los scripts base de `Downloads/Repo` se mapearon al pipeline v4 sin crear
    una dependencia operativa a esa carpeta: KOF trimestral, reconstrucción
    mensual, perfil de formato, Holt-Winters/Bates-Granger, Monte Carlo y MRP
    se alimentan de las hojas `Forecast_*`. `tools/verificar_pipeline_demanda.py`
    reconstruye y contrasta el resultado vigente y publica 9 controles en
    `Forecast_QA`; los loaders cachean una sola lectura por corrida para evitar
    cuota 429 y reconocen las fechas seriales de Sheets. `Maestro_Productos`
    gobierna atributos físicos y precios base del ERP; Odoo gobierna BOM,
    proveedores, stock y transacciones. La hoja `RRHH` gobierna el roster y
    `OdooClient.sincronizar_empleados()` lo replica idempotentemente en
    `hr.employee`/`hr.version`. No se inventan reglas de nómina: hasta configurar
    y validar una estructura salarial colombiana en Odoo no se generan recibos.
    `tools/qa_erp_funcional.py --flujo-completo` prueba las integraciones reales;
    `tools/verificacion.py` conserva 17 pruebas aisladas sin escribir externamente.

24. **2026-07: alcance ULogix y CAPEX multimoneda revisados con cotizaciones.**
    L1: encajonadora custom 30x30, KRONES usada 44.000 bph y GANTRY compartido.
    L2: KRONES usada 18.000 bph, Variopac usada y el mismo GANTRY alternado.
    L3: llenadora existente 600 gfn/h y solo celda robotica. Cotizaciones:
    EUROBOTS GBP 13.500 (robot L3) e IGAM USD 6.500 (IRC5), con logistica.
    El ahorro laboral monetizable (70% inicial de 10 FTE equivalentes, editable)
    entra al EBITDA; proveedores, APU digital y tiempos antes/despues quedan
    documentados en hojas vivas del libro.

## Estado actual (validado)

- Pronóstico v4 sobre 21 trimestres reales de KOF: MAPE 2.9/2.9/2.1 %.
- Tiempos auditados: OEE base 77.1/76.5/75.4 %, TEEP 40.3/40.0/8.3 %.
  **Hallazgo:** con 2 turnos U=1.25 (L1) y 1.30 (L2) → **infactible**, el 3er
  turno la devuelve a 0.83/0.86.
- Capacidad/factibilidad de producción **reactiva al escenario activo**:
  `core/tiempos_oee.py: tabla_tiempos()/tabla_capacidad()` ya recibían
  `demanda_mensual` pero no estaban conectadas al dashboard — ahora la
  página *Inventario*, sección "🏭 Capacidad y factibilidad de producción",
  las llama con `theme.demanda_activa()`: al cambiar de escenario en la
  página *Escenarios* se ve en vivo si cada línea sigue siendo factible con
  los turnos actuales (takt requerido, % utilización, si hace falta 3er
  turno). La base OEE/tiempos sigue siendo documental (no cambia); lo que
  reacciona es la demanda contra la que se compara — no viola la decisión
  #1 (el ERP sigue sin gestionar OEE/TEEP en vivo, eso solo llega por MQTT).
  MRP/compras (*Órdenes Odoo*) y finanzas (*Finanzas*, comparación Base vs.
  escenario) ya usaban `demanda_activa()` desde antes.
- Caso de negocio vivo (alcance decisión #24): CAPEX $9.080 M · **VPN
  $10.729 M · TIR 76.7 % E.A. · ROI 222.4 % · payback 22/26 m**, con
  precios base gobernados por `Maestro_Productos` en Sheets.
- Libro de Sheets: 36 hojas, **4.082 fórmulas y 0 errores** en la auditoría
  completa del 2026-07.
- Despliegue Docker validado en Windows: dashboard y middleware levantan con
  `docker-compose.dashboard.yml`; dentro del contenedor funcionan SciPy 1.18,
  statsmodels 0.14.6 y el pronóstico de 12 meses (MAPE 2.91/2.91/2.05 %).
  Windows Defender/Application Control no interviene en ese runtime Linux.
- Libro de Sheets real (2026-07, tras la reconstrucción de la decisión #17):
  `Tiempos` consolidada + `Tiempos_Resumen` ejecutivo,
  OEE objetivo +5% exacto por línea, `RRHH` centralizada (28 personas, carga
  prestacional colombiana documentada, reconcilia exacto: Operación
  $85.915.382, Implementación $87.161.760), `CAPEX` en 8 bloques por área
  (85 filas de datos, total vivo $9.080 M), hoja `Dashboard` nueva como primera
  pestaña. `OEE_TEEP`/`Personal`/`Empleados` ya no existen (contenido
  migrado, ver decisión #17).
- Integraciones reales validadas: Odoo SaaS 19.3 con 3 productos/BOM, 13
  tarifas de proveedor, inventario, clientes y ciclo PO→recepción→factura
  proveedor→MO/BOM→SO→entrega→factura cliente; RRHH 28/28 sin duplicados;
  MQTT round-trip operativo. Único aviso de configuración: Odoo Payroll no
  tiene todavía una estructura salarial colombiana validada (0 recibos).

## Comandos

```bash
# Levantar todo (reconstruye con las variables anti-segfault)
docker compose -f docker-compose.dashboard.yml up -d --build
docker compose -f docker-compose.dashboard.yml logs -f dashboard

# QA lógico completo (17 pasos, aislado) — obligatorio antes de cerrar cambios
python tools/verificacion.py

# QA de integraciones reales (idempotente; --flujo-completo crea/reutiliza QA)
python tools/qa_erp_funcional.py --flujo-completo
python tools/verificar_pipeline_demanda.py --publicar-qa

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
