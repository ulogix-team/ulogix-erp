import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from app.ui import theme
from app.ui.theme import COL, COLOR_SKU, NOMBRE_CORTO
from config import settings

theme.preparar_pagina("Inicio")
theme.encabezado("ULOGIX · PLANTA FONTIBON · KOF / INDEGA",
                 "Centro de planeacion y simulacion",
                 "Pronostico, escenarios, inventario, compras en Odoo, "
                 "produccion via MQTT y finanzas — sobre el pipeline 00-14 del proyecto.")

# ------------------------------------------------------------------ estado de conexiones
st.subheader("🔌 Integraciones")
with st.container(border=True):
    cols = st.columns(3)
    estado = settings.resumen_conexiones()
    iconos = {"odoo": "🟣", "mqtt": "📡", "sheets": "📗"}
    nombres = {"odoo": "Odoo (API externa)", "mqtt": "MQTT (stack MES)",
               "sheets": "Contabilidad (Sheets/Excel)"}
    for col, (clave, info) in zip(cols, estado.items()):
        with col:
            modo = "conectado" if info["habilitado"] else "dry-run / local"
            st.metric(f"{iconos[clave]} {nombres[clave]}", modo, info["detalle"])

    with st.expander("Probar conexion con Odoo"):
        if st.button("Probar ahora", type="primary"):
            from integrations.odoo_client import OdooClient
            res = OdooClient().probar_conexion()
            (st.success if res["ok"] else st.error)(f"{res['modo']}: {res['detalle']}")
        st.caption("Sin credenciales en `.env` la suite opera en dry-run: cada accion "
                   "queda auditada en SQLite y el flujo completo es demostrable.")

st.divider()

# ------------------------------------------------------------------ KPIs del pronostico
st.subheader("📈 Demanda pronosticada (Abr 2026 – Mar 2027)")
theme.banner_escenario()
nombre_esc, dem = theme.demanda_activa()
with st.container(border=True):
    cols = st.columns(3)
    for col, sku in zip(cols, COLOR_SKU):
        total = int(dem[f"{sku}_unidades"].sum())
        pico = dem.loc[dem[f"{sku}_unidades"].idxmax()]
        with col:
            st.metric(NOMBRE_CORTO[sku], f"{total:,.0f} un/año",
                      f"pico {pico['etiqueta']}: {int(pico[f'{sku}_unidades']):,}")

    base = theme.datos_pronostico()
    st.caption("Backtest del modelo (hold-out 4 trimestres): "
               + " · ".join(f"{r.producto}: MAPE {r.mape*100:.1f}%"
                            for r in base["metricas"].itertuples()))

st.divider()

# ------------------------------------------------------------------ arquitectura
st.subheader("🏗️ Arquitectura — colgada del UNS FEMSA")
st.markdown(
    f"""
```text
 Ignition 8.1 (OPC-UA) ──► Node-RED ──► MQTT · UNS FEMSA/Linea1..3/...
        ▲                                  │
        │                                  │  MES/KPI/#  MES/Maintance/#  Process/#
 Tecnomatix Plant Simulation               ▼
 (gemelos digitales, v2606)          MIDDLEWARE Ulogix ────────► Odoo API (XML-RPC)
                                       │        ▲ publica         productos · BOM · POs
                                       ▼        │ FEMSA/…/ERP/#   (tools/bootstrap_odoo.py)
                                  SQLite ERP    │ (retained)
                        pronosticos · demanda · inventario · plan de compras ·
                        po_tracking · eventos · kpi_uns
                                       │
                                       ▼
                    DASHBOARD Streamlit ──► Google Sheets (libro en Drive)
                    8 paginas: pronostico · escenarios ·      Modelo_FEMSA_Ulogix_2026
                    inventario · ordenes · UNS · finanzas ·   Parametros/Tiempos/OEE/
                    pruebas · base de datos                   Financiero/Demanda/KPIs_UNS
```
"""
)
st.markdown("**Modelo de negocio (retrofit brownfield de las 3 lineas):** "
            "🎯 **+11% throughput** · 📈 **OEE 83% → ≥86%** (fase 1: +5% relativo "
            "debidamente justificado) · 💵 **+5% flujo de caja** · 🔍 trazabilidad "
            "MES/Cloud · 🤖 celdas roboticas de paletizado (BOM real USD 239.889) · "
            "🔧 modernizacion de llenadoras unicamente · 👥 gemelo digital por equipo.")
st.caption("Regla de red del proyecto: procesos fuera de Docker se conectan por la "
           "**IP LAN del host** (no `localhost` ni hostnames de servicios Docker).")

st.divider()
c1, c2 = st.columns(2)
with c1, st.container(border=True):
    st.markdown("**🧭 Flujo sugerido**")
    st.markdown(f"""1. **Pronostico** — revisa el modelo base y su validacion.
2. **Escenarios** — elige o construye un escenario y activalo.
3. **Inventario** — simula politicas y genera el plan MRP.
4. **Ordenes Odoo** — convierte el plan en POs reales (o dry-run).
5. **Produccion MQTT** — sigue el cumplimiento en vivo.
6. **Finanzas** — margen plan vs real y sincronizacion contable.""")
with c2, st.container(border=True):
    st.markdown("**📝 Notas del proyecto**")
    st.markdown(f"""- TEEP ≈ 40% en L1/L2 es el **techo realista** a dos turnos con el
  calendario laboral de Bogota; no es bajo desempeño.
- Cuello de L3: paletizado manual (2 operarios ⇒ 480 uph).
- Pendiente: horas programadas reales para cerrar la
  inconsistencia utilizacion &gt;100% vs TEEP.
- Garrafon casi independiente de gaseosas (r = 0.12):
  programable a contraciclo.""")
