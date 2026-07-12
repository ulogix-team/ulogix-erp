import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from app.ui import theme
from config import settings
from core.inventario import plan_compras
from integrations import state_store
from integrations.odoo_client import LineaPedido, OdooClient

theme.preparar_pagina("Ordenes Odoo", "🛒")
theme.encabezado("ODOO · API EXTERNA (XML-RPC)",
                 "Ordenes de compra desde la simulacion",
                 "El plan MRP del escenario activo se convierte en purchase.order. "
                 "Cada PO queda vinculada a un SKU y una cantidad objetivo que el "
                 "middleware MQTT rastrea hasta marcarla cumplida.")
theme.banner_escenario()
nombre_esc, dem = theme.demanda_activa()

odoo = OdooClient()
estado = "🟢 conectado a " + settings.ODOO_URL if not odoo.dry_run else \
         "🟡 dry-run (sin credenciales en .env — las POs se auditan en SQLite)"
st.caption(f"Estado Odoo: {estado}")

# ------------------------------------------------------------------ propuesta de POs
st.subheader("1 · Propuesta de ordenes")
c1, c2 = st.columns(2)
scrap = c1.slider("Scrap", 0.0, 0.10, 0.02, 0.005, format="%.3f")
cobertura = c2.slider("Meses a convertir en ordenes", 1, 12, 1)

plan = plan_compras(dem, scrap=scrap, cobertura_meses=cobertura)
grupos = (plan.groupby(["proveedor", "etiqueta_mes", "producto"])
          .agg(lineas=("componente", "count"),
               unidades_producto=("unidades_producto_mes", "first"),
               total_cop=("subtotal_cop", "sum"),
               fecha_pedido=("fecha_pedido", "min"))
          .reset_index())
grupos["referencia"] = ("ULOGIX/" + grupos["etiqueta_mes"] + "/"
                        + grupos["producto"] + "/" + grupos["proveedor"].str[:12])
st.dataframe(grupos, width="stretch", hide_index=True,
             column_config={"total_cop": st.column_config.NumberColumn(format="$%,.0f")})
st.caption(f"{len(grupos)} ordenes propuestas · escenario **{nombre_esc}** · "
           f"total ${grupos['total_cop'].sum():,.0f} COP")

sel_refs = st.multiselect("Ordenes a crear", grupos["referencia"].tolist(),
                          default=grupos["referencia"].tolist())
confirmar = st.toggle("Confirmar en Odoo al crear (draft → purchase)", value=False,
                      help="Confirmada, Odoo genera la recepcion (stock.picking) que "
                           "el middleware validara cuando MQTT reporte la produccion.")

if st.button("🛒 Crear ordenes en Odoo", type="primary", disabled=not sel_refs):
    creadas = []
    barra = st.progress(0.0)
    sel = grupos[grupos["referencia"].isin(sel_refs)]
    for i, g in enumerate(sel.itertuples(), 1):
        lineas_df = plan[(plan["proveedor"] == g.proveedor)
                         & (plan["etiqueta_mes"] == g.etiqueta_mes)
                         & (plan["producto"] == g.producto)]
        lineas = [LineaPedido(nombre=f"{l.descripcion} [{l.componente}]",
                              default_code=l.componente,
                              cantidad=float(l.cantidad),
                              precio_unitario=float(l.precio_unitario_cop),
                              uom=l.uom)
                  for l in lineas_df.itertuples()]
        res = odoo.crear_orden_compra(g.proveedor, lineas, g.referencia,
                                      fecha_planeada=str(g.fecha_pedido),
                                      confirmar=confirmar)
        state_store.registrar_po(po_name=res["name"], sku=g.producto,
                                 qty_objetivo=float(g.unidades_producto),
                                 odoo_id=res.get("id"),
                                 proveedor=g.proveedor,
                                 componente=f"{g.lineas} componentes",
                                 detalle=g.referencia)
        creadas.append(res["name"])
        barra.progress(i / len(sel))
    st.success(f"{len(creadas)} ordenes {'creadas en Odoo' if not odoo.dry_run else 'registradas (dry-run)'}: "
               + ", ".join(creadas))
    st.caption("El middleware las marcara **cumplida → recibida_odoo** cuando la "
               "produccion reportada por MQTT cubra la cantidad objetivo del SKU.")

st.divider()

# ------------------------------------------------------------------ seguimiento
st.subheader("2 · Seguimiento de ordenes vinculadas")
pos = state_store.listar_pos()
if not pos:
    st.info("Aun no hay ordenes vinculadas. Crea ordenes arriba; luego alimenta "
            "produccion por MQTT (pagina *Produccion MQTT*).")
else:
    iconos = {"abierta": "🔵", "cumplida": "🟠", "recibida_odoo": "🟢", "error": "🔴"}
    for p in pos[:40]:
        avance = min(1.0, p["qty_producida"] / max(p["qty_objetivo"], 1e-9))
        c1, c2 = st.columns([3, 1])
        with c1:
            st.progress(avance,
                        text=f"{iconos.get(p['estado'],'⚪')} **{p['po_name']}** · "
                             f"{p['sku']} · {p['qty_producida']:,.0f} / "
                             f"{p['qty_objetivo']:,.0f} un · {p['proveedor']}")
        with c2:
            st.caption(f"`{p['estado']}`<br/>{p['actualizado_ts'][:16]}",
                       unsafe_allow_html=True)

with st.expander("Ordenes en Odoo (lectura directa de la API)"):
    if st.button("Consultar purchase.order"):
        st.dataframe(pd.DataFrame(odoo.listar_ordenes()), width="stretch",
                     hide_index=True)
with st.expander("Auditoria (log_acciones)"):
    st.dataframe(pd.DataFrame(state_store.ultimo_log(60)), width="stretch",
                 hide_index=True)
