import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import plotly.graph_objects as go
import streamlit as st

from app.ui import theme
from app.ui.theme import COLOR_SKU, NOMBRE_CORTO
from core.inventario import ParametrosInventario, plan_compras, simular_inventario

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

# ------------------------------------------------------------------ simulacion PT
st.subheader("Simulacion de producto terminado")
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
st.subheader("Plan de compras (explosion MRP)")
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
