import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import plotly.graph_objects as go
import streamlit as st

import pandas as pd

from app.ui import theme
from app.ui.theme import COL, COLOR_SKU, NOMBRE_CORTO
from core.inventario import ParametrosInventario, plan_compras, simular_inventario
from core.tiempos_oee import DATOS as _LINEAS_OEE
from core.tiempos_oee import tabla_capacidad, tabla_tiempos
from integrations import state_store

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
st.caption("Se mueve solo, sin botones: cada avance real de producción "
           "(`AvailableQuantity`/`GoodCount` por MQTT) suma producto terminado y "
           "resta materia prima según `data/bom.csv`; cada PO de insumos recibida "
           "(*Órdenes Odoo*) suma materia prima; cada venta entregada (*Ventas y "
           "Facturación*) resta producto terminado. Es el inventario del **ERP "
           "local** — en Odoo, el mismo movimiento físico se refleja al validar "
           "cada orden de fabricación (`mrp.production`) y cada entrega "
           "(`stock.picking`); consúltalo en vivo con los botones de abajo.")

stock = state_store.stock_actual()
if not stock:
    st.info("Aún no hay movimientos de stock. Recibe una PO de insumos o reporta "
            "producción para que el inventario empiece a moverse.")
else:
    df_stock = pd.DataFrame(stock)
    prod = df_stock[df_stock["tipo"] == "producto"].copy()
    comp = df_stock[df_stock["tipo"] == "componente"].copy()

    if not prod.empty:
        st.markdown("**Producto terminado**")
        cols_pt = st.columns(len(COLOR_SKU))
        prod_ix = prod.set_index("codigo")
        for col, sk in zip(cols_pt, COLOR_SKU):
            with col:
                cant = float(prod_ix.loc[sk, "cantidad"]) if sk in prod_ix.index else 0.0
                st.metric(NOMBRE_CORTO[sk], f"{cant:,.0f} un", delta_color="off")

    if not comp.empty:
        with st.expander(f"Materia prima ({len(comp)} componentes)"):
            st.dataframe(
                comp[["codigo", "descripcion", "cantidad", "uom", "actualizado_ts"]]
                    .sort_values("codigo"),
                width="stretch", hide_index=True)
            negativos = comp[comp["cantidad"] < 0]
            if not negativos.empty:
                st.warning(f"⚠️ {len(negativos)} componente(s) con saldo negativo — se "
                           "produjo sin haber recibido suficiente insumo en el ERP local "
                           "(revisa las PO de insumos en *Órdenes Odoo*).", icon="⚠️")

    with st.expander("Movimientos recientes de stock"):
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
    from integrations import state_store
    state_store.guardar_politica_inventario(r, nombre_esc)  # -> ERP
    try:  # y al libro (hoja Inventarios -> rotacion real)
        from integrations.sheets_client import Contabilidad
        pol = state_store.politicas_inventario_actuales()
        if pol:
            Contabilidad().publicar_inventarios(pol)
    except Exception:  # noqa: BLE001
        pass
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

plan = plan_compras(dem, scrap=scrap, cobertura_meses=cobertura)
if st.button("💾 Guardar plan de compras en la base ERP"):
    from integrations import state_store
    ts = state_store.guardar_plan_compras(plan, nombre_esc)
    st.success(f"Plan guardado en la tabla `plan_compras` (corrida {ts}). "
               "Consultalo en la pagina Base de datos ERP.")
st.dataframe(plan, width="stretch", hide_index=True,
             column_config={"subtotal_cop": st.column_config.NumberColumn(format="$%,.0f"),
                            "precio_unitario_cop": st.column_config.NumberColumn(format="$%,.2f")})
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
st.subheader("🏭 Capacidad y factibilidad de producción — escenario activo")
st.caption("Compara la demanda del **escenario activo** contra la capacidad efectiva "
           "de cada línea (estudio de tiempos auditado, `core/tiempos_oee.py`) para "
           "saber si los turnos actuales alcanzan o si el escenario exige un turno "
           "adicional. La base OEE/tiempos es documental y **no cambia** — lo que "
           "cambia con el escenario es la demanda con la que se compara. Los KPIs "
           "OEE/TEEP **en vivo** siguen llegando solo por MQTT (no se tocan aquí).")

_sku_de_linea = {lin: d["sku"] for lin, d in _LINEAS_OEE.items()}
tcap = tabla_capacidad(dem)
ttmp = tabla_tiempos(dem)

cols_cap = st.columns(3)
for col, lin in zip(cols_cap, ["L1", "L2", "L3"]):
    sku = _sku_de_linea[lin]
    fila_cap = tcap[tcap["linea"] == lin].iloc[0]
    fila_tmp = ttmp[ttmp["linea"] == lin].iloc[0]
    factible = fila_cap["dictamen"].startswith("Factible")
    with col:
        with st.container(border=True):
            st.markdown(f"**{NOMBRE_CORTO[sku]}**")
            st.metric("Utilización (turnos actuales)",
                      f"{fila_cap['U_turnos_actuales']*100:.0f}%",
                      fila_cap["dictamen"],
                      delta_color="normal" if factible else "inverse")
            st.metric("Demanda del escenario (anual)",
                      f"{fila_cap['demanda_2026_und']:,.0f} un",
                      f"capacidad: {fila_cap['capacidad_efectiva_und']:,.0f} un",
                      delta_color="off")
            if "takt_s_por_und" in fila_tmp:
                st.caption(f"Takt requerido: {fila_tmp['takt_s_por_und']:.3f} s/und · "
                           f"ciclo de línea: {fila_tmp['ciclo_Tc_s']:.3f} s/und · "
                           f"con 3er turno: {fila_cap['U_con_3_turnos']*100:.0f}% "
                           f"({fila_cap['capacidad_3_turnos_und']:,.0f} un/año)")

fig_cap = go.Figure()
lineas_orden = ["L1", "L2", "L3"]
fig_cap.add_trace(go.Bar(
    x=[NOMBRE_CORTO[_sku_de_linea[l]] for l in lineas_orden],
    y=[tcap[tcap["linea"] == l]["demanda_2026_und"].iloc[0] for l in lineas_orden],
    name=f"Demanda ({nombre_esc})", marker_color=COL["acento"]))
fig_cap.add_trace(go.Bar(
    x=[NOMBRE_CORTO[_sku_de_linea[l]] for l in lineas_orden],
    y=[tcap[tcap["linea"] == l]["capacidad_efectiva_und"].iloc[0] for l in lineas_orden],
    name="Capacidad (turnos actuales)", marker_color=COL["acento2"]))
fig_cap.add_trace(go.Bar(
    x=[NOMBRE_CORTO[_sku_de_linea[l]] for l in lineas_orden],
    y=[tcap[tcap["linea"] == l]["capacidad_3_turnos_und"].iloc[0] for l in lineas_orden],
    name="Capacidad (3 turnos)", marker_color=COL["muted"]))
fig_cap.update_layout(barmode="group", yaxis_title="unidades / año")
st.plotly_chart(theme.plotly_layout(fig_cap, f"Demanda vs. capacidad · escenario {nombre_esc}"),
                width="stretch")

if not tcap["dictamen"].str.startswith("Factible").all():
    infactibles = tcap[~tcap["dictamen"].str.startswith("Factible")]["linea"].tolist()
    st.warning(f"⚠️ Con la demanda del escenario **{nombre_esc}**, las líneas "
               f"{', '.join(infactibles)} no alcanzan con los turnos actuales y "
               "requieren un turno adicional. Este hallazgo de capacidad **no** "
               "ajusta automáticamente la nómina/OPEX del caso de negocio en "
               "*Finanzas* (esa nómina la gobierna la hoja `Parametros` de Sheets, "
               "editada a mano) — impleméntalo ahí manualmente si el escenario se "
               "vuelve el plan real.", icon="⚠️")
else:
    st.success(f"✅ Con la demanda del escenario **{nombre_esc}**, las 3 líneas son "
               "factibles con los turnos actuales.", icon="✅")

with st.expander("Tabla de tiempos y capacidad — detalle completo"):
    st.dataframe(ttmp, width="stretch", hide_index=True)
    st.dataframe(tcap, width="stretch", hide_index=True)
