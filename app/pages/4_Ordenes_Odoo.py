import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from app.ui import theme
from config import settings
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

try:
    plan = pd.DataFrame(odoo.plan_compras_desde_demanda(
        dem, scrap=scrap, cobertura_meses=cobertura))
except Exception as exc:  # noqa: BLE001
    st.error(f"No se pudo explotar el MRP desde Odoo: {exc}")
    st.caption("Esta página no usará `data/bom.csv` como sustituto. Verifica BOM, "
               "proveedores, precios, MOQ y stock directamente en Odoo.")
    st.stop()
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

        creadas.append(f"{res['name']} → {mo['name']}")
        barra.progress(i / len(sel))
    st.success(f"{len(creadas)} ordenes de compra "
               f"{'creadas en Odoo' if not odoo.dry_run else 'registradas (dry-run)'} "
               f"y {len(ordenes_fabricacion)} orden(es) de fabricacion: "
               + ", ".join(creadas))
    for a in avisos:
        st.warning(a)
    st.caption("Cada lote queda en la **cola de esa linea**: el ERP publica una "
               "sola orden de fabricacion activa a la vez (`FEMSA/LineaX/ERP/"
               "OrderNumber`); cuando el MES reporta `AvailableQuantity` (valor "
               "absoluto) igual o mayor al objetivo, el middleware valida **cumplida "
               "→ recibida_odoo** la MO vinculada (descuenta la BOM y da entrada al "
               "producto terminado) y avanza solo a la siguiente orden de la cola. "
               "Pruebalo en *Pruebas → 4 · Produccion*. Cuando un lote quede listo, "
               "aparece en la pagina *Ventas y Facturacion* para venderlo a un "
               "cliente.")

st.divider()

# ------------------------------------------------------------------ seguimiento
st.subheader("2 · 🔗 Órdenes vigentes en Odoo")
try:
    c1, c2 = st.columns(2)
    c1.dataframe(pd.DataFrame(odoo.listar_ordenes(100)), width="stretch", hide_index=True)
    c2.dataframe(pd.DataFrame(odoo.listar_ordenes_fabricacion(100)), width="stretch", hide_index=True)
except Exception as exc:  # noqa: BLE001
    st.error(f"No se pudo consultar Odoo: {exc}")

st.subheader("3 · Cola operativa MQTT/UNS (Odoo)")
st.caption("Secuencia, objetivo, avance MES y cantidad sincronizada viven en "
           "campos `x_ulogix_*` de `mrp.production`.")
pos = odoo.listar_mo_ulogix_activas()
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
                st.progress(avance,
                            text=f"{iconos.get(p['estado'],'⚪')} **{p['mo_name']}** · "
                                 f"{p['sku']} · {p['qty_producida']:,.0f} / "
                                 f"{p['qty_objetivo']:,.0f} un · "
                                 f"sync Odoo {p['qty_sincronizada_odoo']:,.0f}")
            with c2:
                st.caption(f"`{p['state']}`<br/>secuencia {p['x_ulogix_sequence']}",
                           unsafe_allow_html=True)

with st.expander("Auditoria (log_acciones)"):
    st.dataframe(pd.DataFrame(state_store.ultimo_log(60)), width="stretch",
                 hide_index=True)
