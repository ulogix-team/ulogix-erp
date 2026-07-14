import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import plotly.graph_objects as go
import streamlit as st

import pandas as pd

from app.ui import theme
from app.ui.theme import COL, COLOR_SKU, NOMBRE_CORTO
from core.inventario import ParametrosInventario, simular_inventario
from core.tiempos_oee import DATOS as _LINEAS_OEE
from core.tiempos_oee import tabla_capacidad_comparada, tabla_tiempos
from integrations import state_store
from integrations.odoo_client import OdooClient

theme.preparar_pagina("Inventario", "📦")
theme.encabezado("INVENTARIO Y MRP",
                 "Politica de inventario y plan de compras",
                 "Monte Carlo diario con politica (s, Q) sobre la demanda del "
                 "escenario activo · explosion MRP con MOQ y lead time por proveedor.")
theme.banner_escenario()
nombre_esc, dem = theme.demanda_activa()
metricas = theme.datos_pronostico()["metricas"]
_sigma_prod = dict(zip(metricas["producto"], metricas["sigma_rel"]))
_prod_sku = {"P1-CC350-RGB": "P1", "P2-QT1500-PET": "P2", "P3-GARR25L": "P3"}

# ------------------------------------------------------------------ stock en vivo
st.subheader("📊 Stock actual (tiempo real)")
st.caption("Fuente de verdad: **Odoo `stock.quant` en ubicaciones internas**. "
           "Recepciones, fabricación y entregas actualizan este saldo mediante "
           "movimientos nativos de Odoo. SQLite se conserva únicamente como caché "
           "operativo/auditoría del puente MQTT y no alimenta estas cifras.")

odoo = OdooClient()
try:
    stock = odoo.listar_stock() if not odoo.dry_run else []
    error_stock = None
except Exception as exc:  # noqa: BLE001
    stock, error_stock = [], str(exc)
if error_stock:
    st.error(f"No se pudo consultar el inventario de Odoo: {error_stock}")
elif not stock:
    st.info("Odoo no reporta existencias en ubicaciones internas.")
else:
    df_stock = pd.DataFrame(stock)
    prod = df_stock[df_stock["codigo"].isin(COLOR_SKU)].copy()
    comp = df_stock[~df_stock["codigo"].isin(COLOR_SKU)].copy()

    if not prod.empty:
        st.markdown("**Producto terminado**")
        cols_pt = st.columns(len(COLOR_SKU))
        prod_ix = prod.set_index("codigo")
        for col, sk in zip(cols_pt, COLOR_SKU):
            with col:
                cant = float(prod_ix.loc[sk, "disponible"]) if sk in prod_ix.index else 0.0
                st.metric(NOMBRE_CORTO[sk], f"{cant:,.0f} un", delta_color="off")

    if not comp.empty:
        with st.expander(f"Materia prima ({len(comp)} componentes)"):
            st.dataframe(
                comp[["codigo", "producto", "cantidad", "reservada", "disponible", "uom"]]
                    .sort_values("codigo"),
                width="stretch", hide_index=True)

with st.expander("Caché técnico MQTT/UNS (SQLite, solo diagnóstico)"):
    st.caption("Puede diferir temporalmente de Odoo; nunca se presenta como saldo contable.")
    st.dataframe(pd.DataFrame(state_store.stock_actual()), width="stretch", hide_index=True)
    st.dataframe(pd.DataFrame(state_store.movimientos_stock_recientes(100)),
                 width="stretch", hide_index=True)

st.divider()

# ------------------------------------------------------------------ simulacion PT
st.subheader("📦 Simulacion de producto terminado")
sku = st.radio("Producto", list(COLOR_SKU), horizontal=True,
               format_func=lambda s: NOMBRE_CORTO[s], label_visibility="collapsed")

c1, c2, c3, c4 = st.columns(4)
lead = c1.slider("Lead time reposicion (dias)", 1, 15, 3)
nivel = c2.slider("Nivel de servicio objetivo", 0.90, 0.99, 0.95, 0.01)
sigma = c3.slider("σ demanda (relativa mensual)", 0.01, 0.20,
                  float(round(_sigma_prod[_prod_sku[sku]], 3)), 0.005,
                  help="Por defecto: σ residual del backtest un-paso del producto (v4).")
nrep = c4.slider("Replicas Monte Carlo", 50, 1000, 300, 50)

if st.button("▶ Simular politica (s, Q)", type="primary"):
    with st.spinner("Simulando un año operativo..."):
        r = simular_inventario(dem, ParametrosInventario(sku, lead, nivel),
                               sigma_rel=sigma, n_rep=nrep)
    st.session_state["sim_inv"] = r
    try:  # fuente viva: hoja Inventarios; SQLite queda como cache posterior
        from integrations.sheets_client import Contabilidad
        cli = Contabilidad()
        prev = cli.leer_inventarios().to_dict("records")
        actual = {
            "ts": pd.Timestamp.utcnow().isoformat(), "escenario": nombre_esc,
            "sku": r["sku"], "punto_reorden_s": r["punto_reorden_s"],
            "stock_seguridad": r["stock_seguridad"], "lote_Q": r["lote_Q"],
            "pallets_por_lote": r["pallets_por_lote"],
            "fill_rate": r["fill_rate_prom"],
            "capital_inmovilizado_cop": r["capital_inmovilizado_cop"],
        }
        pol = [p for p in prev if str(p.get("sku")) != r["sku"]] + [actual]
        cli.publicar_inventarios(pol)
        state_store.guardar_politica_inventario(r, nombre_esc)
    except Exception as exc:  # noqa: BLE001
        st.error(f"La politica no se publico en Sheets: {exc}")
r = st.session_state.get("sim_inv")
if r and r["sku"] == sku:
    with st.container(border=True):
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Punto de reorden s", f"{r['punto_reorden_s']:,} un",
                  f"SS: {r['stock_seguridad']:,} un", delta_color="off")
        m2.metric("Lote Q (pallets completos)", f"{r['lote_Q']:,} un",
                  f"{r['pallets_por_lote']} pallets · EOQ {r['eoq_teorico']:,}",
                  delta_color="off")
        m3.metric("Fill rate", f"{r['fill_rate_prom']*100:.2f}%",
                  f"p05: {r['fill_rate_p05']*100:.2f}% (objetivo {int(nivel*100)}%)",
                  delta_color="off")
        m4.metric("Capital inmovilizado prom.",
                  f"${r['capital_inmovilizado_cop']:,.0f}",
                  f"{r['inventario_prom_unidades']:,} un promedio", delta_color="off")

    tray = r["trayectoria_ejemplo"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(y=tray, mode="lines", name="Inventario (replica 1)",
                             line=dict(color=COLOR_SKU[sku], width=2)))
    fig.add_hline(y=r["punto_reorden_s"], line_dash="dot", line_color="#8F7BFF",
                  annotation_text="s (reorden)")
    fig.add_hline(y=r["stock_seguridad"], line_dash="dot", line_color="#FFB454",
                  annotation_text="stock de seguridad")
    fig.update_xaxes(title="dia operativo")
    fig.update_yaxes(title="unidades")
    st.plotly_chart(theme.plotly_layout(fig, "Trayectoria de inventario (ejemplo)"),
                    width="stretch")
    st.caption(f"Dias de quiebre promedio por año: {r['dias_quiebre_prom']:.2f} · "
               f"{r['replicas']} replicas · escenario: {nombre_esc}")

st.divider()

# ------------------------------------------------------------------ MRP
st.subheader("🧮 Plan de compras (explosion MRP)")
c1, c2 = st.columns(2)
scrap = c1.slider("Scrap / merma de proceso", 0.0, 0.10, 0.02, 0.005,
                  format="%.3f")
cobertura = c2.slider("Meses a planear", 1, 12, 3)

st.caption("El cálculo consulta BOM, existencias, proveedores, MOQ, plazo y precios "
           "en Odoo. Se ejecuta bajo demanda para que una consulta lenta no impida "
           "renderizar el resto de la página.")

# Mostrar inmediatamente el último resultado disponible. Antes el MRP se
# ejecutaba en cada rerun y bloqueaba todo lo que venía debajo durante 40-60 s,
# dando la impresión de que la página se había cortado.
plan = st.session_state.get("plan_mrp_df")
origen_plan = st.session_state.get("plan_mrp_origen", "")
if plan is None:
    plan = pd.DataFrame()
    origen_plan = "sin plan cargado en esta sesión"
    st.session_state["plan_mrp_df"] = plan
    st.session_state["plan_mrp_origen"] = origen_plan

accion_calcular, accion_cargar = st.columns(2)
if accion_cargar.button("📥 Cargar último plan publicado"):
    with st.spinner("Leyendo `PlanCompras` desde Google Sheets…"):
        try:
            from integrations.sheets_client import Contabilidad
            plan = Contabilidad().leer_plan_compras()
            origen_plan = "último plan publicado en Sheets"
            st.session_state["plan_mrp_df"] = plan
            st.session_state["plan_mrp_origen"] = origen_plan
            st.session_state.pop("plan_mrp_error", None)
        except Exception as exc:  # noqa: BLE001
            st.session_state["plan_mrp_error"] = f"Sheets: {exc}"

if accion_calcular.button("⚙️ Calcular / actualizar MRP desde Odoo", type="primary"):
    with st.spinner("Consultando Odoo y explotando las BOM… puede tardar hasta un minuto."):
        try:
            nuevo_plan = pd.DataFrame(odoo.plan_compras_desde_demanda(
                dem, scrap=scrap, cobertura_meses=cobertura))
            plan = nuevo_plan
            origen_plan = (f"Odoo · escenario {nombre_esc} · scrap {scrap:.1%} · "
                           f"cobertura {cobertura} mes(es)")
            st.session_state["plan_mrp_df"] = plan
            st.session_state["plan_mrp_origen"] = origen_plan
            st.session_state.pop("plan_mrp_error", None)
        except Exception as exc:  # noqa: BLE001
            st.session_state["plan_mrp_error"] = str(exc)

error_mrp = st.session_state.get("plan_mrp_error")
if error_mrp:
    st.error(f"No se pudo calcular el MRP desde Odoo: {error_mrp}")
    st.caption("Se conserva el último plan disponible. No se usará `data/bom.csv` "
               "como sustituto del maestro vivo de Odoo.")

plan = pd.DataFrame(plan).copy()
# PyArrow no tolera una misma columna con IDs enteros y nombres de Odoo. Las
# columnas descriptivas se homogeneizan antes de enviarlas a Streamlit.
for columna in plan.select_dtypes(include="object").columns:
    plan[columna] = plan[columna].map(
        lambda valor: "" if valor is None else str(valor))

if plan.empty:
    st.info("No hay un plan cargado todavía. Puedes recuperar el último publicado o "
            "calcular uno nuevo desde Odoo. La sección de capacidad ya está disponible abajo.")
else:
    st.caption(f"Mostrando: **{origen_plan}**.")
    if st.button("💾 Publicar plan de compras en Google Sheets"):
        from integrations.sheets_client import Contabilidad
        destino = Contabilidad().publicar_plan_compras(plan)
        st.success(f"Plan publicado en `PlanCompras` ({destino}); Odoo conserva los "
                   "maestros y Sheets el plan aprobado.")
    st.dataframe(plan, width="stretch", hide_index=True,
                 column_config={
                     "subtotal_cop": st.column_config.NumberColumn(format="$%,.0f"),
                     "precio_unitario_cop": st.column_config.NumberColumn(format="$%,.2f"),
                 })
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        c1.metric("Lineas de pedido", len(plan))
        c2.metric("Proveedores", plan["proveedor"].nunique())
        c3.metric("Total del plan", f"${plan['subtotal_cop'].sum():,.0f} COP")
    st.caption("Cada linea conserva su **producto** — asi cada orden de compra queda "
               "vinculada a un SKU rastreable por MQTT. La pagina *Ordenes Odoo* "
               "convierte este plan en `purchase.order`.")

    st.download_button("⬇ Descargar plan de compras (CSV)",
                       plan.to_csv(index=False).encode(),
                       "plan_compras_mrp.csv", "text/csv")

st.divider()

# ------------------------------------------------------------------ capacidad/factibilidad
st.subheader("🏭 Capacidad y factibilidad — antes vs. después del proyecto")
st.caption("Compara la misma demanda del **escenario activo** contra dos sistemas "
           "físicos distintos. **Antes:** equipos, tiempos, OEE y turnos medidos en "
           "la visita. **Después:** equipos realmente incluidos en el CAPEX, celdas "
           "robotizadas, OEE objetivo +5% relativo y turnos de diseño del proyecto "
           "(L1/L2: 3; L3: 1). Los KPI en vivo siguen llegando por MQTT y no "
           "reemplazan estos supuestos de ingeniería.")

_sku_de_linea = {lin: d["sku"] for lin, d in _LINEAS_OEE.items()}
tcap = tabla_capacidad_comparada(dem)
ttmp_antes = tabla_tiempos(dem, "antes")
ttmp_despues = tabla_tiempos(dem, "despues")

cols_cap = st.columns(3)
for col, lin in zip(cols_cap, ["L1", "L2", "L3"]):
    sku = _sku_de_linea[lin]
    fila_cap = tcap[tcap["linea"] == lin].iloc[0]
    fila_antes = ttmp_antes[ttmp_antes["linea"] == lin].iloc[0]
    fila_despues = ttmp_despues[ttmp_despues["linea"] == lin].iloc[0]
    with col:
        with st.container(border=True):
            st.markdown(f"**{NOMBRE_CORTO[sku]} · {lin}**")
            st.metric("Demanda del escenario (anual)",
                      f"{fila_cap['demanda_anual_und']:,.0f} un")
            st.metric("ANTES · utilización", f"{fila_cap['U_antes']*100:.0f}%",
                      f"{fila_cap['dictamen_antes']} · cap. "
                      f"{fila_cap['capacidad_antes_und']:,.0f}", delta_color="off")
            st.metric("DESPUÉS · utilización", f"{fila_cap['U_despues']*100:.0f}%",
                      f"{(fila_cap['U_despues']-fila_cap['U_antes'])*100:+.0f} pp · "
                      f"{fila_cap['dictamen_despues']}", delta_color="inverse")
            st.caption(
                f"OEE {fila_cap['oee_antes']*100:.1f}% → "
                f"{fila_cap['oee_despues']*100:.1f}% · ciclo "
                f"{fila_antes['ciclo_Tc_s']:.3f} → {fila_despues['ciclo_Tc_s']:.3f} s/und · "
                f"turnos {fila_cap['turnos_antes']} → {fila_cap['turnos_despues']} · "
                f"MLT lote {fila_cap['mlt_antes_h']:.2f} → "
                f"{fila_cap['mlt_despues_h']:.2f} h (proyectado).")
            st.caption(f"**Equipo después:** {fila_cap['equipo_despues']}")

fig_cap = go.Figure()
lineas_orden = ["L1", "L2", "L3"]
fig_cap.add_trace(go.Bar(
    x=[NOMBRE_CORTO[_sku_de_linea[l]] for l in lineas_orden],
    y=[tcap[tcap["linea"] == l]["demanda_anual_und"].iloc[0] for l in lineas_orden],
    name=f"Demanda ({nombre_esc})", marker_color=COL["acento"]))
fig_cap.add_trace(go.Bar(
    x=[NOMBRE_CORTO[_sku_de_linea[l]] for l in lineas_orden],
    y=[tcap[tcap["linea"] == l]["capacidad_antes_und"].iloc[0] for l in lineas_orden],
    name="Capacidad ANTES", marker_color=COL["muted"]))
fig_cap.add_trace(go.Bar(
    x=[NOMBRE_CORTO[_sku_de_linea[l]] for l in lineas_orden],
    y=[tcap[tcap["linea"] == l]["capacidad_despues_mismos_turnos_und"].iloc[0]
       for l in lineas_orden],
    name="DESPUÉS · solo tecnología/OEE", marker_color=COL["acento2"]))
fig_cap.add_trace(go.Bar(
    x=[NOMBRE_CORTO[_sku_de_linea[l]] for l in lineas_orden],
    y=[tcap[tcap["linea"] == l]["capacidad_despues_und"].iloc[0] for l in lineas_orden],
    name="DESPUÉS · proyecto completo", marker_color=COL["ok"]))
fig_cap.update_layout(barmode="group", yaxis_title="unidades / año")
st.plotly_chart(theme.plotly_layout(
    fig_cap, f"Demanda vs. capacidad antes/después · escenario {nombre_esc}"),
    width="stretch")

inf_antes = tcap[tcap["dictamen_antes"] == "INFACTIBLE"]["linea"].tolist()
inf_despues = tcap[tcap["dictamen_despues"] == "INFACTIBLE"]["linea"].tolist()
if inf_antes:
    st.warning(f"ANTES del proyecto, {', '.join(inf_antes)} no cubren la demanda "
               f"del escenario **{nombre_esc}**.", icon="⚠️")
if inf_despues:
    st.error(f"Aun DESPUÉS del proyecto, {', '.join(inf_despues)} quedan infactibles. "
             "Debe revisarse alcance, turnos o demanda antes de aprobar el plan.")
else:
    st.success(f"DESPUÉS del proyecto, las tres líneas cubren la demanda del escenario "
               f"**{nombre_esc}**. En L1/L2 esto exige mantener el 3.er turno previsto; "
               "la tecnología y el OEE por sí solos no sustituyen esa condición.", icon="✅")

with st.expander("Tiempos, equipos y capacidad — trazabilidad completa"):
    st.markdown("**Comparación consolidada**")
    st.dataframe(tcap, width="stretch", hide_index=True)
    st.markdown("**ANTES · valores medidos/auditados**")
    st.dataframe(ttmp_antes, width="stretch", hide_index=True)
    st.markdown("**DESPUÉS · valores de diseño**")
    st.dataframe(ttmp_despues, width="stretch", hide_index=True)
    st.caption("El MLT después es una proyección: conserva esperas del VSM base y "
               "recalcula la corrida con el nuevo cuello/lote. Debe sustituirse por "
               "la medición real durante SAT/comisionamiento.")
