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
                 "Ordenes de compra y de fabricacion desde la simulacion",
                 "El plan MRP del escenario activo se convierte en purchase.order "
                 "por insumo (concentrados, etiquetas, tapas, ...) y en una orden "
                 "de fabricacion (mrp.production) por producto y mes, ligada a su "
                 "lista de materiales. Cada lote queda vinculado a un SKU y una "
                 "cantidad objetivo que el middleware MQTT rastrea hasta validar "
                 "la orden de fabricacion.")
theme.banner_escenario()
nombre_esc, dem = theme.demanda_activa()

odoo = OdooClient()
estado = "🟢 conectado a " + settings.ODOO_URL if not odoo.dry_run else \
         "🟡 dry-run (sin credenciales en .env — las POs se auditan en SQLite)"
st.caption(f"Estado Odoo: {estado}")

# ------------------------------------------------------------------ propuesta de POs
st.subheader("1 · 🛒 Propuesta de ordenes")
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
avanzar = st.toggle("Confirmar y recibir insumos de inmediato + reservar en la MO "
                    "+ factura de proveedor",
                    value=True,
                    help="Recomendado: confirma cada purchase.order y valida su "
                         "recepcion en el mismo paso (la suite no modela el lead "
                         "time real del proveedor), genera y contabiliza la "
                         "factura de proveedor (cuenta por pagar) sobre esa PO, y "
                         "confirma + reserva la orden de fabricacion "
                         "(mrp.production) contra ese stock. Si lo apagas, PO y MO "
                         "quedan en borrador para gestionar a mano desde Odoo.")

if st.button("🛒 Crear ordenes en Odoo", type="primary", disabled=not sel_refs):
    creadas = []
    avisos = []
    ordenes_fabricacion: dict[tuple[str, str], dict] = {}  # (producto, mes) -> MO
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
                                      confirmar=avanzar, recibir=avanzar,
                                      facturar=avanzar)
        if avanzar and not res.get("recibida"):
            avisos.append(f"⚠️ {res['name']}: la recepcion de insumos no se pudo "
                          "validar (ver Auditoria abajo para el detalle).")
        if avanzar and not res.get("facturada"):
            avisos.append(f"⚠️ {res['name']}: la factura de proveedor no se pudo "
                          "generar (ver Auditoria abajo para el detalle).")

        # una sola orden de fabricacion por (producto, mes): la comparten las
        # POs de distintos proveedores que abastecen el mismo lote
        clave_mo = (g.producto, g.etiqueta_mes)
        if clave_mo not in ordenes_fabricacion:
            ordenes_fabricacion[clave_mo] = odoo.crear_orden_fabricacion(
                g.producto, float(g.unidades_producto),
                referencia=f"ULOGIX/{g.etiqueta_mes}/{g.producto}",
                confirmar=avanzar, reservar=avanzar)
        mo = ordenes_fabricacion[clave_mo]

        state_store.registrar_po(po_name=res["name"], sku=g.producto,
                                 qty_objetivo=float(g.unidades_producto),
                                 odoo_id=res.get("id"),
                                 proveedor=g.proveedor,
                                 componente=f"{g.lineas} componentes",
                                 detalle=g.referencia,
                                 mo_id=mo.get("id"), mo_name=mo.get("name"),
                                 insumos_recibidos=res.get("recibida", avanzar))
        creadas.append(f"{res['name']} → {mo['name']}")
        barra.progress(i / len(sel))
    st.success(f"{len(creadas)} ordenes de compra "
               f"{'creadas en Odoo' if not odoo.dry_run else 'registradas (dry-run)'} "
               f"y {len(ordenes_fabricacion)} orden(es) de fabricacion: "
               + ", ".join(creadas))
    for a in avisos:
        st.warning(a)
    st.caption("El middleware validara **cumplida → recibida_odoo** la orden de "
               "fabricacion vinculada cuando la produccion reportada por MQTT "
               "cubra la cantidad objetivo del lote (descuenta la BOM y da "
               "entrada al producto terminado). Cuando ese lote quede listo, "
               "aparece en la pagina *Ventas y Facturacion* para venderlo a un "
               "cliente.")

st.divider()

# ------------------------------------------------------------------ seguimiento
st.subheader("2 · 🔗 Seguimiento de ordenes vinculadas")
pos = state_store.listar_pos()
if not pos:
    st.info("Aun no hay ordenes vinculadas. Crea ordenes arriba; luego alimenta "
            "produccion por MQTT (pagina *Produccion MQTT*).")
else:
    iconos = {"abierta": "🔵", "cumplida": "🟠", "recibida_odoo": "🟢", "error": "🔴"}
    with st.container(border=True):
        for p in pos[:40]:
            avance = min(1.0, p["qty_producida"] / max(p["qty_objetivo"], 1e-9))
            c1, c2 = st.columns([3, 1])
            with c1:
                insumo_icono = "📦" if p.get("insumos_recibidos") else "⏳"
                st.progress(avance,
                            text=f"{iconos.get(p['estado'],'⚪')} **{p['po_name']}** · "
                                 f"{p['sku']} · {p['qty_producida']:,.0f} / "
                                 f"{p['qty_objetivo']:,.0f} un · {p['proveedor']} · "
                                 f"{insumo_icono} MO `{p.get('mo_name') or '—'}`")
            with c2:
                st.caption(f"`{p['estado']}`<br/>{p['actualizado_ts'][:16]}",
                           unsafe_allow_html=True)

with st.expander("Ordenes en Odoo (lectura directa de la API)"):
    c1, c2 = st.columns(2)
    if c1.button("Consultar purchase.order"):
        st.dataframe(pd.DataFrame(odoo.listar_ordenes()), width="stretch",
                     hide_index=True)
    if c2.button("Consultar mrp.production"):
        st.dataframe(pd.DataFrame(odoo.listar_ordenes_fabricacion()), width="stretch",
                     hide_index=True)
with st.expander("Auditoria (log_acciones)"):
    st.dataframe(pd.DataFrame(state_store.ultimo_log(60)), width="stretch",
                 hide_index=True)
