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
`estado_fuente_financiera()`). **Nunca** pruebes esto contra el Sheets real sin
permiso explícito del dueño del proyecto — fuerza `DRY_RUN=true` en el entorno
(`settings.DRY_RUN_FORZADO`) para que caiga al fallback Excel local.

## Valores de referencia (si tus números se alejan mucho, algo se rompió)

| Indicador | Valor esperado |
|---|---|
| CAPEX total | ~$22.216 M COP |
| D&A mensual | ~$206.9 M |
| EBITDA incremental 12 m operativos | ~$13.182 M |
| VPN @ TMAR 18 % E.A. | ~$8.033 M |
| TIR | ~36.6 % E.A. |
| ROI 60 m | ~103.8 % |
| Payback | 33 m simple / 42 m descontado |
| Sensibilidad VPN | $2.380 M (Cons.) — $12.831 M (Opt.) |

## El libro Excel (23 hojas)

Orden y responsables:

| Área | Hojas | Dirección |
|---|---|---|
| — | LEEME_Integracion, Reportes | fórmulas |
| Finanzas | `Parametros`, `CAPEX` | **usuario edita → `core/finanzas_negocio.py` LEE** (Sheets → ERP, nuevo) |
| Finanzas | Modelo_Negocio, ER_Proyecto, Flujo_Caja, Balance, FinancieroEscenario, Sensibilidad, Licencias, Personal, Costos_Lote, Dep_Amort | equipo + fórmulas |
| Ventas | Demanda, DemandaEscenario | **app escribe** (ERP → Sheets, rango fijo `A4:F16`) |
| Inventario | Inventarios | **app escribe** (`A4:I8`) + fórmulas de rotación |
| Compras | PlanCompras | app escribe |
| Producción | KPIs_UNS, LibroProduccion, ResumenMensual | middleware escribe (MQTT/UNS) |
| Producción (doc.) | Tiempos, OEE_TEEP | **documentales, NO conectadas** |

**Rangos fijos**: `ER_Proyecto`, `Flujo_Caja`, `Balance`, `FinancieroEscenario` y
la rotación de `Inventarios` referencian esas celdas con fórmulas. Si mueves las
filas de `Demanda`/`DemandaEscenario`/`Inventarios`, rompes el libro. La app
escribe **posicionalmente** (`_escribir_rango()` en `integrations/sheets_client.py`)
— eso no cambió con la nueva dirección Sheets→ERP.

## Contrato de `Parametros` y `CAPEX` (lo que el usuario puede editar a mano)

`Parametros` es pares clave-valor (cualquier fila, `leer_parametros()` en
`integrations/sheets_client.py`); claves reconocidas por el motor —todas
opcionales, sin ellas usa el default local—:
`TRM, FACTOR_RFQ, TMAR_ANUAL, UPLIFT_THROUGHPUT, FACTOR_MONETIZACION,
RAMPA_MES5, SCRAP_PP, MANT_EVITADO_MES, TASA_RENTA, WC_PCT_INGRESO,
CRECIMIENTO_DEMANDA_ANUAL, FASES_CAPEX ("0.20,0.35,0.27,0.18"),
NOMINA_OPERACION_MES, NOMINA_IMPLEMENTACION_MES, OTROS_FIJOS_BASE_MES,
OTROS_FIJOS_PROYECTO_MES, OPEX_LICENCIAS_MES, CAPEX_SOFTWARE, CONTINGENCIA,
VIDA_equipos/VIDA_automatizacion/VIDA_servicios/VIDA_intangibles/VIDA_software`
y unit economics por SKU: `precio_venta_cop_<SKU>` / `costo_material_cop_<SKU>`
(p.ej. `precio_venta_cop_P1-CC350-RGB`). Admite `%` y separador de miles.

`CAPEX` es tabular (`leer_capex()`), encabezado **exacto** en la fila 1:
`seccion, linea, activo, cantidad, moneda, costo_unitario, vida_anios,
categoria_dep` — mismo esquema que la tupla `CAPEX_FILAS` del módulo. Si el
encabezado no calza o la hoja está vacía, se ignora entera (fallback local),
sin romper nada.

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
- **Dos "maestros" de precio distintos, a propósito.** `data/maestro_productos.csv`
  (vía `core/forecast.cargar_maestro()`) es el maestro **físico** que también
  ve Odoo/MRP (EAN, empaque, precio/costo base) — si lo cambias, hazlo
  también en la hoja `Costos_Lote` para que sigan consistentes. Las unit
  economics del **caso de negocio** (`core/finanzas_negocio._maestro()`) son
  independientes: usan ese mismo CSV como default pero se pueden
  sobreescribir solo para el escenario financiero con `precio_venta_cop_<SKU>`
  / `costo_material_cop_<SKU>` en `Parametros`, sin tocar lo que ve Odoo. Si
  quieres que ambos digan lo mismo, edítalos en los dos lugares.
