---
name: pronostico-demanda-ulogix
description: Trabajar con el pronóstico de demanda, los escenarios, la política de inventario (s,Q) y el MRP del proyecto Ulogix/FEMSA. Úsala SIEMPRE que se mencione pronóstico, forecast, Holt-Winters, Bates-Granger, Monte Carlo, MAPE, backtest, estacionalidad, escenarios de demanda, elasticidades, punto de reorden, stock de seguridad, fill rate, lote Q, plan de compras, BOM, explosión de materiales, o los módulos core/forecast.py, core/escenarios.py, core/inventario.py — incluso si el usuario solo pide "recalcular la demanda" o "cambiar un supuesto del modelo".
---

# Pronóstico, escenarios, inventario y MRP

## Datos base (todos reales, versionados en `data/`)

21 trimestres reales de KOF Colombia (2021T1–2026T1) por categoría, bajados a
escala de planta con: participación de Bogotá, captación por producto (SHARE),
litros por caja unidad (5,678), mezcla retornable/no-retornable (34/66) y volumen
de envase (0,35 / 1,5 / 25 L). Mensualización con pesos intra-trimestrales.

SKUs: `P1-CC350-RGB` (L1) · `P2-QT1500-PET` (L2) · `P3-GARR25L` (L3).

## Modelos (`core/forecast.py`)

**P1 y P2** — Holt-Winters multiplicativo con tendencia **amortiguada** (m=4).
El φ<1 modera la extrapolación de la recuperación post-impuesto saludable.

**P3 (garrafón)** — combinación **óptima** de Bates-Granger entre (a) HW directo
y (b) modelo ligado al agua. El peso es inversamente proporcional al MSE de
backtest:

```
w* = MSE_b / (MSE_a + MSE_b)   →   ŷ = w*·ŷ_a + (1−w*)·ŷ_b
```

Con `w* = 0.73`, el MAPE bajó de 2.15 % (promedio 50/50 del repo v3) a **2.11 %**.
Los pesos se re-estiman solos si entran datos nuevos. **No volver al 50/50.**

**Diferenciación P1 vs P2** — el histórico reconstruido los dejaba colineales
(r=1.0). Se separan con dos mecanismos documentados y editables:
1. Deriva de mezcla retornable: `ret(t) = RET₀ + 0.5 pp/año`
2. Perfil de formato mensual: individual (350 ml) sube jun-jul; familiar (1.5 L)
   sube nov-dic. Renormalizado dentro de cada trimestre para preservar totales.

**Incertidumbre** — Monte Carlo N=10.000 (semilla 42), σ relativa por producto
(3.48 % P1/P2, 7.03 % P3), validada con KS / Anderson-Darling / χ². Se reportan
percentiles 5–95.

**Métricas** — MAPE, MAD, RMSE y señal de rastreo `TS = CFE/MAD` (sesgo si
|TS|>4). Valores actuales: MAPE 2.9 / 2.9 / 2.1 %; validación fuera de muestra
2026T1: +0.07 / +0.07 / −0.34 %.

## Escenarios (`core/escenarios.py`)

6 presets + personalizado. Las elasticidades son **por producto** (no por
categoría): p. ej. Mundial → P1 +8/+12 % vs P2 +5/+7 %; Recesión → downtrading
hacia retornables, P1 −3 % vs P2 −7 %.

Al **Activar** un escenario en la página 2, la app:
1. lo guarda en `st.session_state["escenario_activo"]`
2. persiste la demanda en la tabla `pronosticos` del ERP
3. **publica la hoja `DemandaEscenario`** del libro → `FinancieroEscenario`
   recalcula VPN/TIR/ROI del escenario solo

`theme.demanda_activa()` devuelve `(nombre, DataFrame)` — úsalo siempre en vez de
releer el CSV base, para que todo el dashboard sea coherente con el escenario.

## Inventario (`core/inventario.py`)

Revisión continua **(s, Q)**:
- `s = μ_L + z·σ_L` (demanda en lead time + stock de seguridad al nivel de
  servicio elegido)
- `Q` redondeado a **pallets reales**: 1.620 u/pallet en L1, 840 en L2, 30 en L3

La simulación Monte Carlo del año reporta fill rate, quiebres y capital
inmovilizado. Al simular, la política se persiste en el ERP y se publica a la
hoja `Inventarios` (rango fijo `A4:I8`), que alimenta la rotación del libro.

## MRP

Explosiona la demanda del escenario activo por la BOM (`data/bom.csv`,
16 componentes) con scrap, MOQ y lead time por proveedor → plan de compras →
tabla `plan_compras` + hoja `PlanCompras` + órdenes en Odoo.

## Al modificar

- Los módulos de `core/` son **puros**: reciben y devuelven DataFrames, sin
  Streamlit. Si necesitas UI, va en `app/`.
- Cada uno tiene `if __name__ == "__main__":` con un resumen imprimible —
  úsalo para probar sin levantar la app.
- Si tocas el pronóstico, **regenera los derivados**
  (`data/pronostico_base_mensual.csv` y compañía) con `exportar_base()`, porque
  el motor financiero y el generador del Excel los leen.
- Corre `python tools/verificacion.py` — los pasos 2 a 6 cubren estos módulos.
