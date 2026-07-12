---
name: modelo-financiero-ulogix
description: Trabajar con el motor financiero demand-driven y el libro Excel de 23 hojas del proyecto Ulogix/FEMSA. Úsala SIEMPRE que se mencione VPN, TIR, ROI, payback, CAPEX, EBITDA, flujo de caja, estado de resultados, balance, depreciación, sensibilidad, licencias, nómina, costos por lote, rotación de inventarios, el archivo Modelo_FEMSA_Ulogix_2026.xlsx, el módulo core/finanzas_negocio.py o el repo femsa-modelo-financiero — incluso si el usuario solo pide "cambiar un supuesto", "agregar una hoja", "actualizar los números" o "regenerar el Excel".
---

# Modelo financiero Ulogix — motor + libro

## Regla de oro: fuente única de verdad

`core/finanzas_negocio.py` (repo `ulogix-fontibon-suite`) es la **única** fuente
de las cifras del caso. El generador del Excel
(`../femsa-modelo-financiero/tools/generar_modelo.py`) **importa** de ahí:

```python
from core.finanzas_negocio import CAPEX_FILAS, CONTINGENCIA, VIDAS, CAPEX_SOFTWARE
from core.tiempos_oee import NOTA_UNS, tabla_capacidad, tabla_oee, tabla_tiempos
```

**Nunca** hardcodees una cifra en el generador que ya exista en el motor. Si hay
que cambiar el CAPEX, la contingencia o una vida útil → se edita el motor y se
regenera el libro.

## Cómo funciona el motor (demand-driven)

No hay flujos calibrados. Todo sale de la demanda:

```
demanda por SKU (pronóstico v4 o escenario del ERP)
  × precios/costos del maestro (Costos_Lote)
  → ER: caso BASE vs caso PROYECTO
       proyecto = base × (1 + uplift 11% × monetización 31% × rampa)
                + ahorro scrap + mantenimiento evitado
                − otros fijos proyecto − OPEX licencias
  → EBITDA incremental − D&A (por categoría) → impuesto 35% → FCF
  → pre-op (meses 1-4): CAPEX en fases + nómina implementación + licencias
  → capital de trabajo: 8% del ingreso incremental (m5, se recupera en m60)
  → VPN / TIR / ROI / paybacks
```

Funciones clave:
- `capex()` → dict con subtotal, contingencia, total, base por categoría
- `flujos_desde_demanda(demanda_mensual)` → arrays de 60 meses (FCF, EBITDA, D&A…)
- `indicadores(demanda_mensual, escenario)` → dict con VPN/TIR/ROI/paybacks
- `sensibilidad()` → DataFrame con Conservador/Base/Optimista

Probar sin levantar la app: `python core/finanzas_negocio.py`

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

| Área | Hojas | Escribe |
|---|---|---|
| — | LEEME_Integracion, Reportes | fórmulas |
| Finanzas | Parametros, Modelo_Negocio, ER_Proyecto, Flujo_Caja, Balance, FinancieroEscenario, Sensibilidad, CAPEX, Licencias, Personal, Costos_Lote, Dep_Amort | equipo + fórmulas |
| Ventas | Demanda, DemandaEscenario | **app** (rango fijo `A4:F16`) |
| Inventario | Inventarios | **app** (`A4:I8`) + fórmulas de rotación |
| Compras | PlanCompras | app |
| Producción | KPIs_UNS, LibroProduccion, ResumenMensual | middleware (MQTT/UNS) |
| Producción (doc.) | Tiempos, OEE_TEEP | **documentales, NO conectadas** |

**Rangos fijos**: `ER_Proyecto`, `Flujo_Caja`, `Balance`, `FinancieroEscenario` y
la rotación de `Inventarios` referencian esas celdas con fórmulas. Si mueves las
filas de `Demanda`/`DemandaEscenario`/`Inventarios`, rompes el libro. La app
escribe **posicionalmente** (`_escribir_rango()` en `integrations/sheets_client.py`).

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
- Si cambias precios o costos unitarios, hazlo en `data/maestro_productos.csv`
  **y** en la hoja `Costos_Lote`: deben ser consistentes.
