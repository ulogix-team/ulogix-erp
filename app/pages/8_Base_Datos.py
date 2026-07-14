import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from app.ui import theme
from integrations.odoo_client import OdooClient
from integrations.sheets_client import Contabilidad

theme.preparar_pagina("Fuentes del ERP", "🗄️")
theme.encabezado("FUENTES EXTERNAS · SHEETS + ODOO",
                 "Datos conectados del ERP",
                 "Navegador de solo lectura de las fuentes de verdad. Google Sheets "
                 "gobierna planeacion, finanzas, RRHH e historicos MES; Odoo gobierna "
                 "compras, manufactura, ventas, facturacion e inventario.")

SHEETS = {
    "Demanda": "leer_demanda",
    "DemandaEscenario": "leer_demanda_escenario",
    "Inventarios": "leer_inventarios",
    "PlanCompras": "leer_plan_compras",
    "LibroProduccion": "leer_libro_produccion",
    "ResumenMensual": "leer_resumen_mensual",
    "KPIs_UNS": "leer_kpis_uns",
}
ODOO = {
    "Compras": "listar_ordenes",
    "Manufactura": "listar_ordenes_fabricacion",
    "Ventas": "listar_ordenes_venta",
    "Facturas cliente": lambda c: c.listar_facturas("out_invoice", 200),
    "Facturas proveedor": lambda c: c.listar_facturas("in_invoice", 200),
    "Inventario": "listar_stock",
    "Clientes": "listar_clientes",
}

origen = st.radio("Sistema origen", ["Google Sheets", "Odoo"], horizontal=True)
try:
    if origen == "Google Sheets":
        cli = Contabilidad()
        nombre = st.selectbox("Hoja", list(SHEETS))
        metodo = SHEETS[nombre]
        if metodo == "leer_demanda_escenario":
            df = cli.leer_demanda(escenario=True)
        else:
            df = getattr(cli, metodo)()
    else:
        cli = OdooClient()
        nombre = st.selectbox("Modelo", list(ODOO))
        metodo = ODOO[nombre]
        filas = metodo(cli) if callable(metodo) else getattr(cli, metodo)(200)
        df = pd.DataFrame(filas)
    with st.container(border=True):
        st.metric("Registros consultados", f"{len(df):,}")
        if df.empty:
            st.info(f"{nombre} no tiene registros en la fuente externa.")
        else:
            st.dataframe(df, width="stretch", hide_index=True, height=520)
            st.download_button(f"⬇ Exportar vista {nombre}.csv", df.to_csv(index=False),
                               f"{nombre}.csv", "text/csv")
except Exception as exc:  # noqa: BLE001
    st.error(f"La fuente externa no respondio: {exc}")

st.caption("SQLite conserva unicamente cache tecnico, idempotencia y diagnostico "
           "del middleware; no se presenta aqui como fuente de negocio.")
