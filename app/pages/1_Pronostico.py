import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.ui import theme
from app.ui.theme import COL, COLOR_SKU, NOMBRE_CORTO

theme.preparar_pagina("Pronostico", "📈")
theme.encabezado("MODELO ESTADISTICO v4 · DATOS REALES KOF 2021T1–2026T1",
                 "Pronostico de demanda",
                 "Holt-Winters amortiguado (m=4) sobre litros trimestrales reales · "
                 "garrafon: combinacion OPTIMA Bates-Granger · diferenciacion "
                 "P1/P2 por deriva de mezcla retornable + perfil de formato · "
                 "bandas Monte Carlo N=10,000 · horizonte Abr 2026 – Mar 2027.")

datos = theme.datos_pronostico()
mensual, metricas = datos["mensual"], datos["metricas"]
hist_m, hist_q = datos["historico_mensual"], datos["historico_trimestral"]
val = datos["validacion"]

SKUS = list(NOMBRE_CORTO)
PROD_DE = {"P1-CC350-RGB": "P1", "P2-QT1500-PET": "P2", "P3-GARR25L": "P3"}
MES_NUM = {m: i + 1 for i, m in enumerate(
    ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
     "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"])}

# --------------------------------------------------------- backtest + validacion
st.subheader("📊 Backtest un-paso (5 trimestres) y validacion 2026T1")
with st.container(border=True):
    cols = st.columns(3)
    for col, r in zip(cols, metricas.itertuples()):
        v = val.get(r.producto, {})
        with col:
            st.metric(NOMBRE_CORTO[[s for s in SKUS if PROD_DE[s] == r.producto][0]],
                      f"MAPE {r.mape*100:.2f}%",
                      f"2026T1: {v.get('error_pct', 0):+.2f}% · TS {r.tracking_signal:+.2f}",
                      delta_color="off")
st.caption("Modelos: " + " · ".join(
    f"**{r.producto}**: {r.modelo}" for r in metricas.itertuples()) +
    ". La validacion compara el modelo entrenado hasta 2025T4 contra el dato real "
    "del 1T-2026.")

# --------------------------------------------------------- correccion garrafon
comp = datos["supuestos"]["comparacion_modelos_P3_MAPE_pct"]
with st.expander("🔧 Correccion del modelo del garrafon (P3) — comparacion de MAPEs"):
    st.dataframe(pd.DataFrame([{"modelo": k, "MAPE %": v} for k, v in comp.items()]),
                 width="stretch", hide_index=True)
    st.markdown(
        "El repositorio v3 usaba la combinacion **50/50** (Bates-Granger simple); "
        "v4 estima el **peso optimo** w* = MSE_b/(MSE_a+MSE_b) sobre el backtest, "
        "que pondera mas el modelo directo y logra el mejor MAPE. Los pesos se "
        "recalculan automaticamente si llegan datos nuevos.")
corr = datos["supuestos"]["correlacion_mensual_P1P2"]
st.info(f"**Diferenciacion P1 vs P2** — correlacion mensual: historico "
        f"{corr['historico (mezcla fija)']:.2f} (mezcla RET/NR fija por "
        f"construccion) → pronostico v4 **{corr['pronostico v4']:.4f}** "
        f"(deriva de mezcla retornable "
        f"{datos['supuestos']['mezcla_retornable']['deriva_anual_pp']:.1f} pp/año "
        f"+ perfil de formato mensual, ambos editables).")

# --------------------------------------------------------- grafico mensual + historico
st.subheader("📈 Serie mensual por producto: historico real + pronostico")
sel = st.multiselect("Productos", SKUS, default=SKUS,
                     format_func=lambda s: NOMBRE_CORTO[s])
escala_log = st.toggle("Escala logaritmica (compara los 3 ordenes de magnitud)",
                       value=len(sel) > 1)

fig = go.Figure()
mensual = mensual.copy()
mensual["fecha"] = pd.to_datetime(dict(year=mensual["ano"],
                                       month=mensual["mes"].map(MES_NUM), day=1))
mensual = mensual.sort_values("fecha").reset_index(drop=True)
hist_m = hist_m.copy()
hist_m["fecha"] = pd.to_datetime(hist_m["fecha"], errors="raise")
hist_m["unidades"] = pd.to_numeric(hist_m["unidades"], errors="raise")
hist_m = hist_m.sort_values(["producto", "fecha"]).reset_index(drop=True)


def _rgba(hex_color: str, alpha: float) -> str:
    color = hex_color.lstrip("#")
    r, g, b = (int(color[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


for sku in sel:
    p = PROD_DE[sku]
    h = hist_m[hist_m["producto"] == p]
    c = COLOR_SKU[sku]
    fig.add_trace(go.Scatter(x=h["fecha"], y=h["unidades"], mode="lines",
                             name=f"{NOMBRE_CORTO[sku]} · historico",
                             line=dict(color=c, width=1.6)))
    fig.add_trace(go.Scatter(x=mensual["fecha"], y=mensual[f"{sku}_p95"],
                             mode="lines", line=dict(width=0),
                             showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=mensual["fecha"], y=mensual[f"{sku}_p05"],
                             mode="lines", line=dict(width=0), fill="tonexty",
                             fillcolor=_rgba(c, 0.16),
                             name=f"{NOMBRE_CORTO[sku]} · banda 90%",
                             showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=mensual["fecha"], y=mensual[f"{sku}_unidades"],
                             mode="lines+markers",
                             name=f"{NOMBRE_CORTO[sku]} · pronostico",
                             line=dict(color=c, width=2.4, dash="dash")))
fig.add_vline(x=pd.Timestamp("2026-03-15").timestamp() * 1000, line_dash="dot",
              line_color=COL["texto2"])
fig.add_annotation(x=pd.Timestamp("2026-03-15"), y=1.02, yref="paper",
                   text="fin del historico", showarrow=False,
                   font=dict(size=11, color=COL["texto2"]))
if escala_log:
    fig.update_yaxes(type="log")
fig.update_xaxes(type="date", tickformat="%b\n%Y", dtick="M6")
theme.plotly_layout(fig, "Unidades/mes · ene-2021 → mar-2027")
st.plotly_chart(fig, width="stretch")
st.caption("Historico: reconstruccion a escala planta de los 21 trimestres reales "
           "de KOF Colombia (scripts 00-01). Banda sombreada: percentiles 5–95 de "
           "10.000 simulaciones Monte Carlo.")

# --------------------------------------------------------- trimestral
st.subheader("📉 Serie trimestral (litros): historico + pronostico")
figq = go.Figure()
hq = hist_q.copy()
for sku in SKUS:
    p = PROD_DE[sku]
    c = COLOR_SKU[sku]
    figq.add_trace(go.Scatter(x=hq["t"], y=hq[p], mode="lines+markers",
                              name=f"{NOMBRE_CORTO[sku]} · real",
                              line=dict(color=c, width=1.8)))
tq = datos["trimestral"].copy()
tq["t"] = pd.PeriodIndex(tq["trimestre"], freq="Q").to_timestamp()
# conectar el ultimo real con el primer pronostico
for sku in SKUS:
    p = PROD_DE[sku]
    x = [hq["t"].iloc[-1]] + list(tq["t"])
    y = [hq[p].iloc[-1]] + list(tq[p])
    figq.add_trace(go.Scatter(x=x, y=y, mode="lines+markers",
                              name=f"{NOMBRE_CORTO[sku]} · pronostico",
                              line=dict(color=COLOR_SKU[sku], width=2.4,
                                        dash="dash")))
figq.update_yaxes(type="log")
theme.plotly_layout(figq, "Litros/trimestre (escala log) · 2021T1 → 2027T1")
st.plotly_chart(figq, width="stretch")

# --------------------------------------------------------- tabla y descarga
st.subheader("🗂️ Plan mensual (unidades) — escenario Base")
tabla = mensual[["etiqueta"] + [f"{s}_unidades" for s in SKUS] +
                [f"{s}_p05" for s in SKUS] + [f"{s}_p95" for s in SKUS]]
st.dataframe(tabla, width="stretch", hide_index=True, height=330)
st.download_button("⬇ Descargar pronostico (CSV)",
                   mensual.drop(columns=["fecha"]).to_csv(index=False),
                   "pronostico_v4_mensual.csv", "text/csv")

with st.expander("Supuestos y trazabilidad del modelo"):
    st.json(datos["supuestos"])
