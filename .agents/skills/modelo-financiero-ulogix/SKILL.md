---
name: modelo-financiero-ulogix
description: Trabajar con el motor financiero demand-driven y el libro Excel de 23 hojas del proyecto Ulogix/FEMSA. Úsala SIEMPRE que se mencione VPN, TIR, ROI, payback, CAPEX, EBITDA, flujo de caja, estado de resultados, balance, depreciación, sensibilidad, licencias, nómina, costos por lote, rotación de inventarios, el archivo Modelo_FEMSA_Ulogix_2026.xlsx, el módulo core/finanzas_negocio.py o el repo femsa-modelo-financiero — incluso si el usuario solo pide "cambiar un supuesto", "agregar una hoja", "actualizar los números" o "regenerar el Excel".
---

# Modelo financiero Ulogix — motor + libro

## Regla de oro: **Sheets gobierna, Python es el fallback**

> Cambió de dirección a propósito (pedido explícito del dueño del proyecto).
> Hasta la versión anterior, `core/finanzas_negocio.py` era la **única**
> fuente de las cifras del caso, y el generador del Excel importaba de ahí
> (`CAPEX_FILAS`, `CONTINGENCIA`, `VIDAS`, `CAPEX_SOFTWARE`). **Eso ya no es
> cierto para los parámetros financieros**: ahora el libro de Google Sheets
> (hojas `Parametros` y `CAPEX`) es la fuente **viva** que el usuario edita a
> mano (CAPEX, turnos/nómina, precios, TMAR...), y las constantes de
> `core/finanzas_negocio.py` (`TRM`, `TMAR_ANUAL`, `CAPEX_FILAS`, `VIDAS`,
> etc.) pasaron a ser el **default/fallback** — se usan tal cual cuando Sheets
> no está configurado, la hoja está vacía o una celda no castea a número. El
> motor sigue dando exactamente los mismos números de siempre en ese caso
> (verificado: `tools/verificacion.py`, paso "Caso de negocio").

Mecanismo (`core/finanzas_negocio.py`, funciones `_parametros()` /
`_capex_filas_activas()` / `_maestro()`): en cada llamada a `indicadores()` /
`flujos_desde_demanda()` / `sensibilidad()` se lee `Contabilidad().
leer_parametros()` (pares clave-valor) y `Contabilidad().leer_capex()` (tabla)
vía `integrations/sheets_client.py`, con **TTL de 60 s en memoria de proceso**
(`_cacheado()`) para no golpear la API de Sheets en cada rerun de Streamlit.
El botón **🔄 Refrescar desde Sheets** de la página *Finanzas* fuerza una
lectura inmediata (`forzar_refresco=True`). `core/finanzas_negocio.py` sigue
siendo puro (sin `st.*`): la integración vive en `integrations/sheets_client.py`.

El generador del Excel (`../femsa-modelo-financiero/tools/generar_modelo.py`)
sigue importando `CAPEX_FILAS, CONTINGENCIA, VIDAS, CAPEX_SOFTWARE` de este
módulo, pero ahora son solo el **seed inicial** del libro (para poblar la hoja
`CAPEX`/`Parametros` la primera vez) — una vez el usuario edita esas hojas en
Drive, el libro manda y el generador ya no vuelve a pisar esos valores en una
regeneración. Si hay que cambiar el CAPEX o un supuesto **de ahora en
adelante, edítalo en la hoja de Sheets**, no en el módulo — el módulo solo se
toca si hay que cambiar el *default* para cuando Sheets no esté disponible.

## Cómo funciona el motor (demand-driven)

No hay flujos calibrados. Todo sale de la demanda:

```
demanda por SKU (pronóstico v4 o escenario del ERP)
  × precios/costos del maestro (Sheets Parametros → fallback Costos_Lote/CSV)
  → ER: caso BASE vs caso PROYECTO
       proyecto = base × (1 + uplift 11% × monetización 31% × rampa)
                + ahorro scrap + mantenimiento evitado
                − otros fijos proyecto − OPEX licencias
  → EBITDA incremental − D&A (por categoría, CAPEX de Sheets → fallback local) → impuesto 35% → FCF
  → pre-op (meses 1-4): CAPEX en fases + nómina implementación + licencias
  → capital de trabajo: 8% del ingreso incremental (m5, se recupera en m60)
  → VPN / TIR / ROI / paybacks
```

Funciones clave:
- `capex(forzar=False)` → dict con subtotal, contingencia, total, base por categoría (CAPEX de Sheets si hay filas válidas, si no `CAPEX_FILAS` local)
- `flujos_desde_demanda(demanda_mensual, forzar_refresco=False)` → arrays de 60 meses (FCF, EBITDA, D&A…)
- `indicadores(demanda_mensual, escenario, forzar_refresco=False)` → dict con VPN/TIR/ROI/paybacks
- `sensibilidad(demanda_mensual, forzar_refresco=False)` → DataFrame con Conservador/Base/Optimista
- `estado_fuente_financiera(forzar=False)` → diagnóstico: modo (`sheets`/`excel`), qué claves de `Parametros` están activas, si `CAPEX` trajo filas — es lo que pinta la página *Finanzas*

Probar sin levantar la app: `python core/finanzas_negocio.py` (imprime también
`estado_fuente_financiera()`). Por defecto valida contra el fallback local
(fuerza `DRY_RUN=true`, `settings.DRY_RUN_FORZADO`) — pide permiso explícito
al dueño del proyecto antes de conectarte al Sheets real (verificado una vez,
ver "Contrato real" abajo; no asumas que sigue vigente sin confirmarlo de
nuevo si ha pasado tiempo).

## Valores de referencia (si tus números se alejan mucho, algo se rompió)

| Indicador | Valor esperado |
|---|---|
| CAPEX total | ~$12.188 M COP (recortado 2026-07, decisión #15: sin lavadoras ni inspección de línea, celdas robóticas a detalle de BOM real) |
| D&A mensual | ~$123.5 M |
| EBITDA incremental 12 m operativos | ~$13.119 M |
| VPN @ TMAR 18 % E.A. | ~$15.935 M |
| TIR | ~83.8 % E.A. |
| ROI 60 m | ~242.8 % |
| Payback | 21 m simple / 24 m descontado |
| Sensibilidad VPN | $7.134 M (Cons.) — $14.046 M (Opt.) |

Nota 2026-07 (decisión #20): estos valores ya NO incluyen ningún supuesto de
crecimiento de demanda interanual — el horizonte de 60 meses repite el
patrón de 12 meses del pronóstico/escenario del ERP tal cual, sin inflarlo.
Pedido explícito del dueño del proyecto. El motor nativo de Sheets
(`Sensibilidad`, `ER_Proyecto`) da una cifra más baja (~$10.8 M en el
escenario Base) que el motor Python — es la brecha esperada entre los dos
modelos paralelos (ver más abajo), que se hizo algo más visible al quitar
el crecimiento de los dos.

## El libro Excel (seed original de 23 hojas + `RRHH`/`APU_Ingenieria`/`Dashboard` agregadas por el ERP; `Personal`/`Empleados`/`OEE_TEEP` ya no existen, consolidadas 2026-07 — ver decisión #17 de AGENTS.md)

Orden y responsables:

| Área | Hojas | Dirección |
|---|---|---|
| — | LEEME_Integracion, Reportes, `Dashboard` (resumen ejecutivo, nueva) | fórmulas / ERP escribe (`tools/actualizar_dashboard.py`) |
| Finanzas | `Parametros`, `CAPEX` (en 8 bloques por área desde 2026-07, `tools/reorganizar_capex_areas.py` — mismo esquema/valores, solo presentación) | **usuario edita → `core/finanzas_negocio.py` LEE** (Sheets → ERP) |
| Finanzas | `APU_Ingenieria` (justificación de las 3 filas `Servicios` de `CAPEX`, AIU) | **ERP escribe** (`tools/publicar_apu_ingenieria.py`); fórmulas vivas → costo unitario de Servicios en `CAPEX` |
| Finanzas | Modelo_Negocio, ER_Proyecto, Flujo_Caja, Balance, FinancieroEscenario, Sensibilidad, Licencias, Costos_Lote, Dep_Amort (fórmula SUMIF viva contra CAPEX por categoría) | equipo + fórmulas |
| RRHH | `RRHH` (roster + resumen por rol + tasas de carga prestacional colombiana + reconciliación, consolidada — ver skill `integraciones-erp-ulogix`) | **ERP escribe/lee** (`integrations/rrhh_client.py`), reconstrucción completa (el resumen se deriva del roster) |
| Ventas | Demanda, DemandaEscenario | **app escribe** (ERP → Sheets, rango fijo `A4:F16`) |
| Inventario | Inventarios | **app escribe** (`A4:I8`) + fórmulas de rotación |
| Compras | PlanCompras | app escribe |
| Producción | KPIs_UNS, LibroProduccion, ResumenMensual | middleware escribe (MQTT/UNS) |
| Producción (doc.) | `Tiempos` (consolidada, incluye OEE/TEEP/MLT-VSM/máquinas reales/glosario en 10 bloques, `tools/actualizar_tiempos_oee.py`) | **documental, NO conectada** |

### Costos de ingeniería ULogix (APU) — `APU_Ingenieria`

Justifica, con metodología APU (Análisis de Precios Unitarios, estándar de
construcción/EPC en Colombia), las 3 filas `Servicios` de `CAPEX`
(Ingeniería de detalle/FAT/SAT/PMO, Instalación/EPC, Capacitación/gestión
del cambio): `precio_total = costo_directo × (1 + AIU)`. La mano de obra
propia usa el costo real de nómina de `data/empleados.csv`; los rubros de
subcontratistas/OEM (FAT/SAT, cuadrillas de instalación) son supuestos de
mercado documentados línea por línea — **no cotizaciones reales**, a validar
antes de contratar. **AIU es una banda de mercado (25–30%), no una tarifa
fijada por ley** — no afirmes lo contrario. El AIU implícito resultante en
los 3 ítems (27–28%) confirma que los montos de `CAPEX` ya estaban bien
calibrados: **el precio total no cambió**, solo se justificó de abajo hacia
arriba. Regenerar: `python tools/publicar_apu_ingenieria.py`; cantidades,
tarifas y porcentajes AIU son entradas, los totales son fórmulas y las 3 filas
de `Servicios` en `CAPEX` toman su costo unitario del APU.

**Rangos fijos**: `ER_Proyecto`, `Flujo_Caja`, `Balance`, `FinancieroEscenario` y
la rotación de `Inventarios` referencian esas celdas con fórmulas. Si mueves las
filas de `Demanda`/`DemandaEscenario`/`Inventarios`, rompes el libro. La app
escribe **posicionalmente** (`_escribir_rango()` en `integrations/sheets_client.py`)
— eso no cambió con la nueva dirección Sheets→ERP.

## Contrato REAL de `Parametros`/`CAPEX`/`Licencias` (verificado contra el libro)

**El libro real usa formato numérico COLOMBIANO, no inglés**: punto = miles,
coma = decimales (`"3.850"` = 3850, `"18,00%"` = 0.18). El parser compartido
es `integrations/sheets_client.py: numero_cop()`; `core/finanzas_negocio.py:
_num()` lo usa y además maneja el sufijo `%`. Si escribes un valor nuevo en
Sheets, usa ese formato (coma decimal), no `18.00`.

**Las claves reales del libro son minúsculas y en español**, no las
constantes en mayúsculas del módulo — `core/finanzas_negocio.py:
_ALIAS_PARAMETROS` traduce entre ambas (las claves canónicas en mayúsculas
también funcionan directo, por si el libro cambia a futuro):

| Clave real (libro) | Clave canónica del motor |
|---|---|
| `trm_cop_usd` | `TRM` |
| `factor_rfq_benchmark` | `FACTOR_RFQ` |
| `tmar_anual`, `tasa_renta` | `TMAR_ANUAL`, `TASA_RENTA` (mismo nombre, min/mayúsc.) |
| `uplift_throughput`, `factor_monetizacion`, `rampa_mes5`, `scrap_pp`, `mant_evitado_mes`, `wc_pct_ingreso` | ídem en mayúsculas |
| `nomina_operacion_mes`, `nomina_implementacion_mes` | ídem en mayúsculas |
| `otros_fijos_base_mes`, `otros_fijos_proyecto_mes` | ídem en mayúsculas |
| `contingencia_capex` | `CONTINGENCIA` |
| `fase_capex_1` .. `fase_capex_4` (4 filas separadas) | `FASES_CAPEX` (se combinan solas) |
| `precio_p1_330ml`/`precio_p2_pet15`/`precio_p3_garrafon` | `precio_venta_cop_<SKU>` |

`crecimiento_demanda` (fila `Parametros!B10`) **ya NO se lee** (decisión #20
de AGENTS.md, 2026-07): el motor eliminó por completo el parámetro
`CRECIMIENTO_DEMANDA_ANUAL` — la evaluación financiera sigue siempre la
demanda que manda el ERP (pronóstico/escenario), sin inflarla con una tasa
de crecimiento aparte. La fila de Sheets se conserva en 0% con una nota
(mismo patrón que el CAPEX en cantidad=0) por si hace falta auditar qué
existía antes; escribir un valor ahí ya no tiene ningún efecto en el motor
Python. **Ojo**: la hoja `ER_Proyecto`/`FinancieroEscenario` (motor nativo
de Sheets) SÍ sigue teniendo la fórmula `(1+Parametros!$B$10)^N` en ~900
celdas — quedó neutralizada porque B10=0, no porque se haya borrado la
fórmula; si algún día hace falta reintroducir crecimiento, cambiar B10 lo
reactivaría en el motor de Sheets pero NO en el motor Python (que ya no
tiene ese parámetro en absoluto) — hay que decidir a propósito si se quiere
eso.

`VIDA_*` y `costo_material_cop_<SKU>` **no existen hoy en el libro real** —
si hace falta gobernarlos desde Sheets, agrégalos con esos nombres canónicos
tal cual (no necesitan alias).

`OPEX_LICENCIAS_MES`/`CAPEX_SOFTWARE` **no viven en `Parametros` ni en
`CAPEX`** — viven en la hoja `Licencias`, filas `CAPEX software
capitalizable` / `OPEX mensual licencias` (última celda no vacía de la fila,
sin columna fija), leídas por `leer_licencias()`.

`CAPEX` es tabular (`leer_capex()`). El encabezado real **no** es idéntico
letra por letra al de `CAPEX_FILAS` (`activo / paquete` en vez de `activo`,
`vida (años)` en vez de `vida_anios`, y trae una columna extra `CAPEX COP`
ya calculada entre `costo_unitario` y `vida_anios`) — por eso `leer_capex()`
busca la fila de encabezado **por nombre de columna** (`_ALIAS_CAPEX`, tolera
variantes e ignora columnas extra) en vez de exigir una lista posicional
exacta. Verificado: 25 filas reales leídas correctamente (vs. 24 del default
local — el libro tiene una línea que el seed de Python no tiene).

Si una hoja no existe, está vacía o no se reconoce ninguna columna/etiqueta
esperada, el motor cae a su default local sin error visible — es el mismo
patrón de resiliencia del resto del proyecto.

## Flujo obligatorio al regenerar el libro

```bash
cd ../femsa-modelo-financiero
python tools/generar_modelo.py
# recalcular con LibreOffice (openpyxl NO calcula fórmulas):
soffice --headless --convert-to xlsx --outdir /tmp salida/Modelo_FEMSA_Ulogix_2026.xlsx
```
Mejor aún, si el repo tiene el script de recálculo, úsalo y **verifica que
reporte 0 errores** antes de dar el archivo por bueno. Después valida que los
indicadores del libro (`Flujo_Caja!B19..B29`) coincidan con
`python core/finanzas_negocio.py`. Si no coinciden, hay una fórmula mal.

**Ojo con el orden si ya hay un libro en producción**: regenerar desde cero
sobreescribe `Parametros`/`CAPEX` con el *seed* del módulo Python, borrando
cualquier ajuste manual que el usuario ya haya hecho en Drive (CAPEX, turnos,
precios...). Antes de regenerar un libro que el usuario esté editando
activamente, **pregunta** si quiere conservar sus valores actuales — el
generador todavía no hace merge, solo sobreescribe.

Errores típicos de fórmula y sus causas:
- `#N/A` en paybacks → `MATCH(TRUE,INDEX(rango>0,0),0)` mal construido
- `#NUM!`/`#N/A` en TIR → `IRR` de LibreOffice **necesita guess**: `IRR(rango,0.02)`
- `#DIV/0!` en ROI → la inversión pre-operativa quedó en 0 (referencia rota)
- `#VALUE!` → referencia a una celda de otra hoja que quedó desplazada

## Convenciones de formato

Azul = entrada editable · Negro = fórmula · Verde = referencia entre hojas ·
Amarillo = palanca clave. Fuente Arial. Formato moneda `$#,##0;($#,##0);-`.

## Advertencias

- **⚠ GRP001**: dos grippers distintos con el mismo código en las BOM de
  paletizado. Se mantienen **separados y marcados en rojo** en la hoja CAPEX.
  No consolidar.
- El Δ vs el modelo original (+268 % en VPN) es **esperado y documentado**: aquel
  usaba flujo agregado, este deriva de la demanda real v4 con D&A e impuestos
  explícitos. No "corregirlo" hacia el valor viejo.
- **Maestro operativo único en Sheets.** `Maestro_Productos` contiene EAN,
  empaque, atributos físicos y precio/costo base. Lo consumen
  `core.forecast.cargar_maestro()` y `core.finanzas_negocio._maestro()` en
  operación. `data/maestro_productos.csv` solo es seed/fallback cuando
  `EXTERNAL_ONLY=false`; no lo uses como fuente viva. BOM/proveedores/stock y
  transacciones siguen gobernados por Odoo.
