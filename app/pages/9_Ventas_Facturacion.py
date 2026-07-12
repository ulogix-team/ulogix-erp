import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from app.ui import theme
from config import settings
from core.forecast import cargar_maestro
from integrations import state_store
from integrations.odoo_client import LineaPedido, OdooClient

theme.preparar_pagina("Ventas y Facturacion", "🧾")
theme.encabezado("ODOO · VENTAS Y CUENTAS POR COBRAR",
                 "Producto terminado -> distribuidor -> factura",
                 "Cierra el flujo del ERP que faltaba: compra-insumo -> "
                 "fabricacion -> **venta -> factura -> cobro**. Cada lote de "
                 "producto terminado (orden de fabricacion ya validada en "
                 "Odoo) se reparte entre los clientes de `data/clientes.csv` "
                 "segun su participacion, y por cada uno se crea una "
                 "`sale.order` que se confirma, se entrega (descuenta el "
                 "terminado del inventario) y se factura (cuenta por cobrar).")
theme.banner_escenario()

odoo = OdooClient()
estado = "🟢 conectado a " + settings.ODOO_URL if not odoo.dry_run else \
         "🟡 dry-run (sin credenciales en .env — las ventas se auditan en SQLite)"
st.caption(f"Estado Odoo: {estado}")

maestro = cargar_maestro().set_index("sku")
clientes = pd.read_csv(settings.DATA_DIR / "clientes.csv")

# ------------------------------------------------------------------ lotes vendibles
st.subheader("1 · 📦 Lotes de producto terminado disponibles")

pos = state_store.listar_pos()
ventas = state_store.listar_ventas()
mo_vendidas = {v["mo_name"] for v in ventas if v.get("mo_name")}

lotes: dict[str, dict] = {}
for p in pos:
    if p["estado"] != "recibida_odoo" or not p.get("mo_name"):
        continue
    lotes.setdefault(p["mo_name"], p)  # una fila por MO: una MO por producto+mes
disponibles = [p for mo, p in lotes.items() if mo not in mo_vendidas]

if not disponibles:
    st.info("Aun no hay lotes de producto terminado listos para vender (o ya "
            "se vendieron todos). Completa el ciclo compra -> fabricacion en "
            "las paginas *Ordenes Odoo* y *Produccion MQTT* primero: un lote "
            "queda disponible aqui cuando su orden de fabricacion (MO) "
            "vinculada quedo `recibida_odoo`.")
else:
    df_lotes = pd.DataFrame([{
        "mo_name": p["mo_name"], "producto": p["sku"],
        "cantidad_disponible": p["qty_objetivo"], "lote": p.get("detalle", "")
    } for p in disponibles])
    st.dataframe(df_lotes, width="stretch", hide_index=True)

    sel_mo = st.multiselect("Lotes a vender", df_lotes["mo_name"].tolist(),
                            default=df_lotes["mo_name"].tolist())
    st.caption("La cantidad de cada lote se reparte entre estos clientes "
               "segun `participacion` (suma 1.0 en `data/clientes.csv`):")
    st.dataframe(clientes, width="stretch", hide_index=True)

    avanzar = st.toggle("Confirmar + entregar + facturar de inmediato",
                        value=True,
                        help="Recomendado: confirma cada sale.order, valida "
                             "la entrega (descuenta el producto terminado "
                             "del inventario) y genera + contabiliza la "
                             "factura de cliente en el mismo paso. Si lo "
                             "apagas, las ordenes quedan en borrador para "
                             "gestionar a mano desde Odoo.")

    if st.button("🧾 Crear ordenes de venta en Odoo", type="primary",
                 disabled=not sel_mo):
        creadas: list[str] = []
        avisos: list[str] = []
        seleccion = [p for p in disponibles if p["mo_name"] in sel_mo]
        total_pasos = max(len(seleccion) * len(clientes), 1)
        barra = st.progress(0.0)
        paso = 0
        for p in seleccion:
            sku = p["sku"]
            precio = float(maestro.loc[sku, "precio_venta_cop"]) if sku in maestro.index else 0.0
            nombre_prod = maestro.loc[sku, "nombre"] if sku in maestro.index else sku
            for c in clientes.itertuples():
                paso += 1
                barra.progress(paso / total_pasos)
                cantidad = round(p["qty_objetivo"] * c.participacion, 2)
                if cantidad <= 0:
                    continue
                referencia = f"ULOGIX-VTA/{p['mo_name']}/{c.nombre[:16]}"
                lineas = [LineaPedido(nombre=str(nombre_prod), default_code=sku,
                                      cantidad=cantidad, precio_unitario=precio)]
                res = odoo.crear_orden_venta(c.nombre, lineas, referencia,
                                             confirmar=avanzar, entregar=avanzar,
                                             facturar=avanzar)
                estado_venta = ("facturada" if res.get("facturada") else
                                "entregada" if res.get("entregada") else
                                "confirmada" if avanzar else "creada")
                state_store.registrar_venta(so_name=res["name"], sku=sku,
                                            cliente=c.nombre, cantidad=cantidad,
                                            precio_unitario_cop=precio,
                                            mo_name=p["mo_name"], odoo_id=res.get("id"),
                                            estado=estado_venta, detalle=referencia)
                creadas.append(f"{res['name']} → {c.nombre} ({cantidad:,.0f} un)")
                if avanzar and not res.get("entregada"):
                    avisos.append(f"⚠️ {res['name']}: la entrega no se pudo validar "
                                  "(ver log_acciones para el detalle).")
                if avanzar and not res.get("facturada"):
                    avisos.append(f"⚠️ {res['name']}: la factura no se pudo generar "
                                  "(ver log_acciones para el detalle).")
        st.success(f"{len(creadas)} ordenes de venta "
                   f"{'creadas en Odoo' if not odoo.dry_run else 'registradas (dry-run)'}: "
                   + "; ".join(creadas))
        for a in avisos:
            st.warning(a)

st.divider()

# ------------------------------------------------------------------ seguimiento
st.subheader("2 · 💰 Seguimiento de ventas")
ventas = state_store.listar_ventas()
if not ventas:
    st.info("Aun no hay ventas registradas. Crea ordenes de venta arriba.")
else:
    iconos = {"creada": "⚪", "confirmada": "🔵", "entregada": "🟠",
             "facturada": "🟢", "error": "🔴"}
    df_v = pd.DataFrame(ventas)
    st.dataframe(
        df_v[["so_name", "cliente", "sku", "cantidad", "subtotal_cop", "estado",
              "mo_name", "actualizado_ts"]],
        width="stretch", hide_index=True,
        column_config={"subtotal_cop": st.column_config.NumberColumn(format="$%,.0f"),
                       "estado": st.column_config.TextColumn()})
    st.caption(" · ".join(f"{iconos.get(k,'⚪')} {k}" for k in iconos))

with st.expander("Ordenes y facturas en Odoo (lectura directa de la API)"):
    c1, c2, c3 = st.columns(3)
    if c1.button("Consultar sale.order"):
        st.dataframe(pd.DataFrame(odoo.listar_ordenes_venta()), width="stretch",
                     hide_index=True)
    if c2.button("Consultar facturas de cliente"):
        st.dataframe(pd.DataFrame(odoo.listar_facturas("out_invoice")), width="stretch",
                     hide_index=True)
    if c3.button("Consultar facturas de proveedor"):
        st.dataframe(pd.DataFrame(odoo.listar_facturas("in_invoice")), width="stretch",
                     hide_index=True)
with st.expander("Auditoria (log_acciones)"):
    st.dataframe(pd.DataFrame(state_store.ultimo_log(60)), width="stretch",
                 hide_index=True)
