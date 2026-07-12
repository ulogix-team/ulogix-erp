import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.ui import theme
from app.ui.theme import COL
from core import rrhh
from integrations import rrhh_client

theme.preparar_pagina("RRHH", "🧑‍🤝‍🧑")
theme.encabezado("RRHH · DOTACION Y NOMINA",
                 "Roster individual vinculado a Google Sheets",
                 "Cada persona vive en la hoja **Empleados** del libro (o en "
                 "`data/empleados.csv` si Sheets no esta configurado). Es el "
                 "detalle individual de la hoja **Personal** (agregado por rol "
                 "que ya usa el motor financiero via `NOMINA_OPERACION_MES` / "
                 "`NOMINA_IMPLEMENTACION_MES`) — abajo se reconcilian ambas.")

if st.button("🔄 Refrescar desde Sheets"):
    st.cache_data.clear()


@st.cache_data(ttl=60, show_spinner="Leyendo el roster...")
def _cargar():
    return rrhh_client.leer_empleados()


df, origen = _cargar()
badge = "🟢 Google Sheets" if origen == "sheets" else "🟡 CSV local (`data/empleados.csv`)"
st.caption(f"Fuente del roster: **{badge}** · {len(df)} personas")

problemas = rrhh.validar_roster(df)
if problemas:
    for p in problemas:
        st.warning(f"⚠️ {p}")

# ------------------------------------------------------------------ resumen
st.subheader("1 · Dotación")
c1, c2, c3, c4 = st.columns(4)
activos = df[df["estado"] == "activo"]
c1.metric("Personas activas", f"{len(activos):,.0f}", f"{len(df) - len(activos)} inactivas/otro estado")
costo_fase = rrhh.costo_mensual_por_fase(df)
c2.metric("Nómina Operación/mes", f"${costo_fase.get('Operacion', 0):,.0f}")
c3.metric("Nómina Implementación/mes", f"${costo_fase.get('Implementacion', 0):,.0f}")
c4.metric("Costo total/mes", f"${sum(costo_fase.values()):,.0f}")

resumen_rol = rrhh.resumen_por_rol(df)
fig = go.Figure()
fig.add_trace(go.Bar(x=resumen_rol["rol_personal"], y=resumen_rol["conteo"],
                     marker_color=COL["acento"], name="Conteo"))
fig.update_layout(xaxis_title="", yaxis_title="personas activas")
st.plotly_chart(theme.plotly_layout(fig, "Dotación por rol"), width="stretch")
st.dataframe(resumen_rol, width="stretch", hide_index=True,
            column_config={"costo_total_mes_cop": st.column_config.NumberColumn(format="$%,.0f"),
                          "costo_unitario_cop": st.column_config.NumberColumn(format="$%,.0f")})

st.subheader("2 · Dotación por línea y turno")
resumen_linea = rrhh.resumen_por_linea(df)
if len(resumen_linea):
    fig2 = go.Figure()
    for turno in sorted(resumen_linea["turno"].unique()):
        d = resumen_linea[resumen_linea["turno"] == turno]
        fig2.add_trace(go.Bar(x=d["linea"], y=d["dotacion"], name=turno))
    fig2.update_layout(barmode="group", yaxis_title="personas")
    st.plotly_chart(theme.plotly_layout(fig2, "Operarios por línea y turno"), width="stretch")
else:
    st.info("Sin personal operativo (linea L1/L2/L3) en el roster actual.")

st.divider()

# ------------------------------------------------------------------ reconciliacion
st.subheader("3 · Reconciliación contra la hoja Personal")
nomina_personal = rrhh_client.leer_nomina_personal()
if nomina_personal is None:
    st.info("No se pudo leer la hoja **Personal** del libro (Sheets no conectado, o "
            "la hoja no tiene el formato esperado). La reconciliación solo compara "
            "el roster contra sí mismo hasta que haya conexión real.")
else:
    rec = rrhh.reconciliar_con_personal(
        df, nomina_personal.get("nomina_operacion_mes", 0.0),
        nomina_personal.get("nomina_implementacion_mes", 0.0))
    c1, c2 = st.columns(2)
    with c1:
        ok = rec["operacion_reconciliado"]
        st.metric("Operación: roster vs. Personal",
                 f"${rec['operacion_roster_cop']:,.0f}",
                 f"{'✅ cuadra' if ok else '⚠️ difiere'} vs Personal "
                 f"${rec['operacion_personal_cop']:,.0f} "
                 f"({rec['operacion_diferencia_cop']:+,.0f})",
                 delta_color="off" if ok else "inverse")
    with c2:
        ok = rec["implementacion_reconciliado"]
        st.metric("Implementación: roster vs. Personal",
                 f"${rec['implementacion_roster_cop']:,.0f}",
                 f"{'✅ cuadra' if ok else '⚠️ difiere'} vs Personal "
                 f"${rec['implementacion_personal_cop']:,.0f} "
                 f"({rec['implementacion_diferencia_cop']:+,.0f})",
                 delta_color="off" if ok else "inverse")
    if not (rec["operacion_reconciliado"] and rec["implementacion_reconciliado"]):
        st.caption("La diferencia significa que alguien editó el roster individual "
                  "(Empleados) o el agregado (Personal) sin actualizar el otro — "
                  "corrígelo a mano en Sheets.")

st.divider()

# ------------------------------------------------------------------ roster
st.subheader("4 · Roster completo")
f1, f2, f3, f4 = st.columns(4)
filtro_linea = f1.multiselect("Línea", sorted(df["linea"].unique()))
filtro_turno = f2.multiselect("Turno", sorted(df["turno"].unique()))
filtro_fase = f3.multiselect("Fase", sorted(df["fase"].unique()))
filtro_estado = f4.multiselect("Estado", sorted(df["estado"].unique()))

vista = df.copy()
for col, filtro in [("linea", filtro_linea), ("turno", filtro_turno),
                    ("fase", filtro_fase), ("estado", filtro_estado)]:
    if filtro:
        vista = vista[vista[col].isin(filtro)]

st.dataframe(vista, width="stretch", hide_index=True,
            column_config={"salario_mensual_cop": st.column_config.NumberColumn(format="$%,.0f")})

st.divider()

# ------------------------------------------------------------------ alta de empleado
st.subheader("5 · Agregar empleado")
roles_conocidos = sorted(df["rol_personal"].unique())
with st.form("nuevo_empleado"):
    c1, c2, c3 = st.columns(3)
    cedula = c1.text_input("Cédula")
    nombre = c2.text_input("Nombre completo")
    cargo = c3.text_input("Cargo")
    c4, c5, c6 = st.columns(3)
    rol_personal = c4.selectbox("Rol (Personal)", roles_conocidos)
    linea = c5.selectbox("Línea", ["L1", "L2", "L3", "Todas"])
    turno = c6.selectbox("Turno", ["Turno 1", "Turno 2", "Turno 3", "Rotativo", "Administrativo"])
    c7, c8, c9 = st.columns(3)
    fase = c7.selectbox("Fase", ["Operacion", "Implementacion"])
    fecha_ingreso = c8.date_input("Fecha de ingreso", value=date.today())
    salario = c9.number_input("Salario mensual (COP, costo empleador)", min_value=0.0, step=100000.0)
    c10, c11 = st.columns(2)
    telefono = c10.text_input("Teléfono")
    email = c11.text_input("Email")
    enviado = st.form_submit_button("➕ Agregar al roster", type="primary")

    if enviado:
        if not cedula or not nombre:
            st.error("Cédula y nombre son obligatorios.")
        elif cedula in df["cedula"].astype(str).values:
            st.error(f"Ya existe un empleado con cédula {cedula}.")
        else:
            destino = rrhh_client.agregar_empleado(
                cedula=cedula, nombre=nombre, cargo=cargo, rol_personal=rol_personal,
                linea=linea, turno=turno, fase=fase,
                fecha_ingreso=fecha_ingreso.isoformat(), estado="activo",
                salario_mensual_cop=salario, telefono=telefono, email=email)
            st.success(f"{nombre} agregado(a) al roster ({destino}).")
            st.cache_data.clear()
            st.rerun()

with st.expander("Contrato de la hoja Empleados"):
    st.code(", ".join(rrhh_client.COLUMNAS), language="text")
    st.caption("Sin rangos fijos ni fórmulas dependientes: se puede reemplazar completa "
              "(clear + append) o agregar filas sueltas sin romper nada, a diferencia de "
              "`Demanda`/`DemandaEscenario`/`Inventarios`.")
