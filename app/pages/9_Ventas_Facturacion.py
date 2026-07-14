import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from app.ui import theme
from config import settings
from integrations import state_store
from integrations.odoo_client import LineaPedido, OdooClient

theme.preparar_pagina("Ventas y Facturacion", "🧾")
theme.encabezado("ODOO · VENTAS Y CUENTAS POR COBRAR",
                 "Producto terminado -> distribuidor -> factura",
                 "Cierra el flujo del ERP que faltaba: compra-insumo -> "
                 "fabricacion -> **venta -> factura -> cobro**. Cada lote de "
                 "producto terminado (orden de fabricacion ya validada en "
                 "Odoo) se reparte entre los clientes activos de **Odoo**, "
                 "y por cada uno se crea una "
                 "`sale.order` que se confirma, se entrega (descuenta el "
                 "terminado del inventario) y se factura (cuenta por cobrar).")
theme.banner_escenario()

odoo = OdooClient()
estado = "🟢 conectado a " + settings.ODOO_URL if not odoo.dry_run else \
         "🟡 dry-run (sin credenciales en .env — las ventas se auditan en SQLite)"
st.caption(f"Estado Odoo: {estado}")

try:
    clientes_odoo = odoo.listar_clientes() if not odoo.dry_run else []
except Exception as exc:  # noqa: BLE001
    clientes_odoo = []
    st.error(f"No se pudieron leer los clientes de Odoo: {exc}")
clientes = pd.DataFrame(clientes_odoo)
if not clientes.empty:
    clientes = clientes[["id", "name", "email", "phone", "x_ulogix_participacion"]] \
        .rename(columns={"name": "nombre", "x_ulogix_participacion": "participacion"})

# ------------------------------------------------------------------ lotes vendibles
st.subheader("1 · 📦 Lotes de producto terminado disponibles")

try:
    lotes_odoo = odoo.listar_lotes_fabricados() if not odoo.dry_run else []
except Exception as exc:  # noqa: BLE001
    lotes_odoo = []
    st.error(f"No se pudieron leer los lotes fabricados de Odoo: {exc}")
disponibles = [p for p in lotes_odoo if p["cantidad_disponible"] > 1e-9]

if not disponibles:
    st.info("Aun no hay lotes de producto terminado listos para vender (o ya "
            "se vendieron todos). Completa el ciclo compra -> fabricacion en "
            "las paginas *Ordenes Odoo* y *Produccion MQTT* primero: un lote "
            "queda disponible aqui cuando su orden de fabricacion (MO) "
            "vinculada quedó `done` y conserva cantidad no comprometida en "
            "órdenes de venta no canceladas de Odoo.")
else:
    df_lotes = pd.DataFrame(disponibles)
    st.dataframe(df_lotes, width="stretch", hide_index=True)

    sel_mo = st.multiselect("Lotes a vender", df_lotes["mo_name"].tolist(),
                            default=df_lotes["mo_name"].tolist())
    st.caption("Clientes leídos de `res.partner` en Odoo. Ajusta la participación "
               "para esta corrida; se normaliza automáticamente a 100 % y no se "
               "guarda en archivos locales.")
    if clientes.empty:
        st.warning("Odoo no tiene clientes activos (`customer_rank > 0`).")
        clientes_ed = clientes
    else:
        clientes_ed = st.data_editor(
            clientes, width="stretch", hide_index=True,
            disabled=["id", "nombre", "email", "phone"],
            column_config={"participacion": st.column_config.NumberColumn(
                "Participación", min_value=0.0, max_value=1.0, format="%.2f")})

    avanzar = st.toggle("Confirmar + entregar + facturar de inmediato",
                        value=True,
                        help="Recomendado: confirma cada sale.order, valida "
                             "la entrega (descuenta el producto terminado "
                             "del inventario) y genera + contabiliza la "
                             "factura de cliente en el mismo paso. Si lo "
                             "apagas, las ordenes quedan en borrador para "
                             "gestionar a mano desde Odoo.")

    if st.button("🧾 Crear ordenes de venta en Odoo", type="primary",
                 disabled=not sel_mo or clientes.empty):
        creadas: list[str] = []
        avisos: list[str] = []
        seleccion = [p for p in disponibles if p["mo_name"] in sel_mo]
        clientes_venta = clientes_ed[clientes_ed["participacion"] > 0].copy()
        suma_part = float(clientes_venta["participacion"].sum())
        if suma_part <= 0:
            st.error("La participación total debe ser mayor que cero.")
            st.stop()
        clientes_venta["participacion"] /= suma_part
        total_pasos = max(len(seleccion) * len(clientes_venta), 1)
        barra = st.progress(0.0)
        paso = 0
        for p in seleccion:
            sku = p["sku"]
            precio = float(p["precio_venta_cop"])
            nombre_prod = p["producto"]
            for c in clientes_venta.itertuples():
                paso += 1
                barra.progress(paso / total_pasos)
                cantidad = round(p["cantidad_disponible"] * c.participacion, 2)
                if cantidad <= 0:
                    continue
                referencia = f"ULOGIX-VTA/{p['mo_name']}/{c.nombre[:16]}"
                lineas = [LineaPedido(nombre=str(nombre_prod), default_code=sku,
                                      cantidad=cantidad, precio_unitario=precio)]
                res = odoo.crear_orden_venta(c.nombre, lineas, referencia,
                                             confirmar=avanzar, entregar=avanzar,
                                             facturar=avanzar)
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
try:
    ventas_odoo = odoo.listar_ordenes_venta(200) if not odoo.dry_run else []
except Exception as exc:  # noqa: BLE001
    ventas_odoo = []
    st.error(f"No se pudieron leer las ventas de Odoo: {exc}")
if not ventas_odoo:
    st.info("Odoo aún no tiene órdenes de venta.")
else:
    st.dataframe(pd.DataFrame(ventas_odoo), width="stretch", hide_index=True,
                 column_config={"amount_total": st.column_config.NumberColumn(format="$%,.0f")})

with st.expander("Caché técnico de correlación (SQLite, solo diagnóstico)"):
    st.dataframe(pd.DataFrame(state_store.listar_ventas()), width="stretch", hide_index=True)

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
