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
from integrations.odoo_client import OdooClient

theme.preparar_pagina("RRHH", "🧑‍🤝‍🧑")
theme.encabezado("RRHH · DOTACION Y NOMINA",
                 "Roster individual + resumen por rol, centralizados en una hoja",
                 "Todo vive en la hoja **RRHH** del libro: el roster "
                 "individual, el resumen agregado por rol (el que alimenta al "
                 "motor financiero via `NOMINA_OPERACION_MES` / "
                 "`NOMINA_IMPLEMENTACION_MES` en la hoja `Parametros`), la tabla "
                 "de tasas de carga prestacional (ARL/EPS/pensión/parafiscales/"
                 "prestaciones — de referencia, ver la hoja) y la reconciliación "
                 "entre ambas vistas.")

if st.button("🔄 Refrescar desde Sheets"):
    st.cache_data.clear()


@st.cache_data(ttl=60, show_spinner="Leyendo el roster...")
def _cargar():
    return rrhh_client.leer_empleados(permitir_fallback=False)

try:
    df, origen = _cargar()
except Exception as exc:  # noqa: BLE001
    st.error(f"RRHH requiere Google Sheets y no usará datos locales: {exc}")
    st.stop()
badge = "🟢 Google Sheets (fuente de verdad)"
st.caption(f"Fuente del roster: **{badge}** · {len(df)} personas")

st.subheader("Estado de sincronización con Odoo")
try:
    odoo = OdooClient()
    estado_odoo = odoo.estado_nomina()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Empleados Odoo", estado_odoo["empleados"],
              f"Sheets: {len(df)}")
    c2.metric("Versiones laborales", estado_odoo["versiones"])
    c3.metric("Estructuras salariales", estado_odoo["estructuras"])
    c4.metric("Recibos de nómina", estado_odoo["recibos"])
    if estado_odoo["estructuras"] == 0:
        st.info("El maestro laboral se sincroniza con Odoo, pero no se generan "
                "recibos hasta configurar y validar una estructura salarial "
                "colombiana en Nómina. No se inventan reglas contables.")
    if st.button("🔄 Sincronizar roster con Odoo", type="primary"):
        resultado = odoo.sincronizar_empleados(df.to_dict("records"))
        st.success(f"Odoo actualizado: {resultado['creados']} creados, "
                   f"{resultado['actualizados']} actualizados y "
                   f"{resultado['desactivados']} desactivados.")
        st.cache_data.clear()
        st.rerun()
except Exception as exc:  # noqa: BLE001
    st.warning(f"No se pudo consultar/sincronizar RRHH con Odoo: {exc}")

problemas = rrhh.validar_roster(df)
if problemas:
    for p in problemas:
        st.warning(f"⚠️ {p}")

# ------------------------------------------------------------------ resumen
st.subheader("1 · 🧑‍🤝‍🧑 Dotación")
with st.container(border=True):
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

st.subheader("2 · 🏭 Dotación por línea y turno")
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
st.subheader("3 · ⚖️ Reconciliación contra el resumen por rol")
nomina_personal = rrhh_client.leer_nomina_personal()
if nomina_personal is None:
    st.info("No se pudo leer la sección RESUMEN de la hoja **RRHH** del libro (Sheets "
            "no conectado, o la hoja no tiene el formato esperado). La reconciliación "
            "solo compara el roster contra sí mismo hasta que haya conexión real.")
else:
    rec = rrhh.reconciliar_con_personal(
        df, nomina_personal.get("nomina_operacion_mes", 0.0),
        nomina_personal.get("nomina_implementacion_mes", 0.0))
    with st.container(border=True):
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
        st.caption("La diferencia significa que el roster individual y el resumen "
                  "por rol de la hoja RRHH se desincronizaron — vuelve a correr "
                  "`python tools/actualizar_rrhh.py` para reconstruir el resumen "
                  "desde el roster actual.")

st.divider()

# ------------------------------------------------------------------ roster
st.subheader("4 · 📋 Roster completo")
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
st.subheader("5 · ➕ Agregar empleado")
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
                permitir_fallback=False,
                cedula=cedula, nombre=nombre, cargo=cargo, rol_personal=rol_personal,
                linea=linea, turno=turno, fase=fase,
                fecha_ingreso=fecha_ingreso.isoformat(), estado="activo",
                salario_mensual_cop=salario, telefono=telefono, email=email)
            df_nuevo, _ = rrhh_client.leer_empleados(permitir_fallback=False)
            resultado_odoo = OdooClient().sincronizar_empleados(
                df_nuevo.to_dict("records"))
            st.success(f"{nombre} agregado(a) al roster ({destino}) y sincronizado "
                       f"con Odoo ({resultado_odoo['creados']} alta(s), "
                       f"{resultado_odoo['actualizados']} actualización(es)).")
            st.cache_data.clear()
            st.rerun()

with st.expander("Contrato de la hoja RRHH (sección ROSTER INDIVIDUAL)"):
    st.code(", ".join(rrhh_client.COLUMNAS), language="text")
    st.caption("`salario_mensual_cop` es el costo total empleador (ya con carga "
              "prestacional) — la sección TASAS DE CARGA PRESTACIONAL de la hoja "
              "documenta el desglose. Cada cambio al roster reconstruye la hoja "
              "completa (el resumen por rol se deriva del roster, no es un dato "
              "aparte) — no tiene fórmulas dependientes de rangos fijos como "
              "`Demanda`/`DemandaEscenario`/`Inventarios`.")
