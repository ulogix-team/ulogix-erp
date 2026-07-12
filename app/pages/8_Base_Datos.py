import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from app.ui import theme
from config import settings
from integrations import state_store

theme.preparar_pagina("Base de datos ERP", "🗄️")
theme.encabezado("PERSISTENCIA · SQLITE WAL",
                 "Base de datos del ERP",
                 "Todo lo que la suite decide o recibe queda en "
                 f"`{settings.STATE_DB}`: corridas de pronostico, demanda por "
                 "escenario, politicas de inventario, plan de compras, POs, "
                 "eventos de produccion del UNS y KPIs MES. Docker la monta "
                 "como volumen para que sobreviva reinicios.")

resumen = state_store.resumen_tablas()
with st.container(border=True):
    cols = st.columns(len(resumen))
    for col, (tabla, n) in zip(cols, resumen.items()):
        col.metric(tabla, f"{n:,}")

st.divider()

# --------------------------------------------------------------- navegador
st.subheader("🔎 Navegador de tablas")
c1, c2 = st.columns([2, 1])
tabla = c1.selectbox("Tabla", state_store.TABLAS_ERP)
limite = c2.number_input("Ultimas filas", 10, 5000, 300, step=50)
filas = state_store.leer_tabla(tabla, int(limite))
if filas:
    df = pd.DataFrame(filas)
    st.dataframe(df, width="stretch", hide_index=True, height=380)
    st.download_button(f"⬇ Exportar {tabla}.csv", df.to_csv(index=False),
                       f"{tabla}.csv", "text/csv")
else:
    st.info("Tabla vacia todavia. Se llena al usar la suite: recalcular el "
            "pronostico (pagina 1), activar un escenario (2), simular la "
            "politica (3), generar ordenes (4) o recibir mensajes del UNS (5).")

# --------------------------------------------------------------- tablero KPI UNS
st.divider()
st.subheader("📊 Tablero de KPIs del UNS (ultimo valor por linea)")
kpis = state_store.kpis_actuales()
if kpis:
    piv = (pd.DataFrame(kpis)
           .pivot_table(index="linea", columns="kpi", values="valor_num",
                        aggfunc="last").round(4))
    orden = [c for c in ["OEE", "Availability", "Performance", "Quality",
                         "TEEP", "DT", "MTTR", "MTBF"] if c in piv.columns]
    st.dataframe(piv[orden + [c for c in piv.columns if c not in orden]],
                 width="stretch")
    st.caption("Fuente: topicos `FEMSA/+/MES/KPI/#` ingeridos por el middleware "
               "(tabla kpi_uns). El detalle historico esta en el navegador de "
               "arriba.")
else:
    st.info("Aun no llegan KPIs del UNS. Corre el middleware y el simulador: "
            "`python middleware/run_middleware.py` + "
            "`python tools/simulador_produccion.py`, o publica desde Node-RED "
            "a `FEMSA/LineaX/MES/KPI/...`.")
