import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.ui import theme
from app.ui.theme import COLOR_SKU, NOMBRE_CORTO
from core.escenarios import (ESCENARIOS, aplicar_escenario,
                             escenario_personalizado, resumen_comparativo)
from core.forecast import MESES, ResultadoPronostico

theme.preparar_pagina("Escenarios", "🎛️")
theme.encabezado("MOTOR DE ESCENARIOS · SCRIPT 13",
                 "Simulacion de escenarios de demanda",
                 "Factores multiplicativos mes a mes sobre el pronostico base — "
                 "el modelo estadistico nunca se toca. Cada escenario documenta "
                 "su justificacion y fuente.")

datos = theme.datos_pronostico()
res = theme.resultado_base()

# ------------------------------------------------------------------ seleccion
opciones = list(ESCENARIOS) + ["Personalizado"]
sel = st.selectbox("Escenario", opciones)

if sel != "Personalizado":
    esc = ESCENARIOS[sel]
    st.markdown(f"**Justificacion:** {esc.justificacion}")
    st.caption(f"Fuente: {esc.fuente}")
else:
    st.markdown("Define factores mensuales POR PRODUCTO (1.00 = sin cambio) — "
                "v4 permite elasticidades distintas para P1, P2 y P3.")
    nombre = st.text_input("Nombre del escenario", "Escenario personalizado")
    numcol = st.column_config.NumberColumn(min_value=0.5, max_value=1.5,
                                           step=0.01, format="%.2f")
    base_df = pd.DataFrame({"mes": MESES, "P1_350ml": [1.0] * 12,
                            "P2_1.5L": [1.0] * 12, "P3_garrafon": [1.0] * 12})
    edit = st.data_editor(base_df, hide_index=True, width="stretch",
                          column_config={"P1_350ml": numcol, "P2_1.5L": numcol,
                                         "P3_garrafon": numcol})
    esc = escenario_personalizado(
        nombre,
        dict(zip(edit["mes"], edit["P1_350ml"])),
        dict(zip(edit["mes"], edit["P2_1.5L"])),
        dict(zip(edit["mes"], edit["P3_garrafon"])),
    )

df_esc = aplicar_escenario(res, esc)

# ------------------------------------------------------------------ comparacion vs base
st.divider()
st.subheader("🎯 Escenario vs. base")
sku = st.radio("Producto", list(COLOR_SKU), horizontal=True,
               format_func=lambda s: NOMBRE_CORTO[s], label_visibility="collapsed")
x = df_esc["etiqueta"]
fig = go.Figure()
fig.add_trace(go.Scatter(x=x, y=res.mensual[f"{sku}_unidades"], name="Base",
                         mode="lines", line=dict(color="#5C5486", width=2, dash="dot")))
fig.add_trace(go.Scatter(x=x, y=df_esc[f"{sku}_unidades"], name=esc.nombre,
                         mode="lines+markers",
                         line=dict(color=COLOR_SKU[sku], width=3)))
st.plotly_chart(theme.plotly_layout(fig), width="stretch")

delta = df_esc[f"{sku}_unidades"].sum() / max(res.mensual[f"{sku}_unidades"].sum(), 1) - 1
with st.container(border=True):
    c1, c2 = st.columns(2)
    c1.metric("Total anual del escenario", f"{int(df_esc[f'{sku}_unidades'].sum()):,} un",
              f"{delta*100:+.2f}% vs base")
    c2.metric("Mes de mayor efecto",
              df_esc.loc[(df_esc[f"{sku}_factor"] - 1).abs().idxmax(), "etiqueta"],
              f"factor {df_esc[f'{sku}_factor'].loc[(df_esc[f'{sku}_factor']-1).abs().idxmax()]:.2f}",
              delta_color="off")

# ------------------------------------------------------------------ activar
st.divider()
c1, c2 = st.columns(2)
with c1:
    if st.button(f"✅ Activar «{esc.nombre}» para toda la suite", type="primary",
                 width="stretch"):
        st.session_state["escenario_activo"] = esc
        from integrations import state_store
        state_store.guardar_pronostico(df_esc, esc.nombre)  # demanda del escenario -> ERP
        try:  # y al libro financiero (hoja DemandaEscenario -> FinancieroEscenario)
            from integrations.sheets_client import Contabilidad
            destino = Contabilidad().publicar_demanda_escenario(df_esc, esc.nombre)
            st.toast(f"Demanda del escenario publicada al libro ({destino})")
        except Exception as _e:  # noqa: BLE001
            st.toast(f"Libro no actualizado: {_e}")
        st.success(f"Escenario activo: {esc.nombre}. Inventario, ordenes en Odoo y "
                   "finanzas usan ahora esta demanda.")
with c2:
    if st.button("↩ Volver al escenario Base", width="stretch"):
        st.session_state.pop("escenario_activo", None)
        st.info("Escenario Base reactivado.")
theme.banner_escenario()

# ------------------------------------------------------------------ resumen 6 escenarios
st.divider()
st.subheader("📋 Resumen comparativo (equivale al script 13)")


@st.cache_data(show_spinner=False)
def _resumen():
    return resumen_comparativo(res)


st.dataframe(_resumen(), width="stretch", hide_index=True)

st.download_button("⬇ Descargar demanda del escenario (CSV)",
                   df_esc.to_csv(index=False).encode(),
                   f"escenario_{esc.nombre.replace(' ', '_')}.csv", "text/csv")
