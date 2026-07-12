import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from app.ui import theme
from app.ui.theme import COLOR_SKU, NOMBRE_CORTO
from config import settings
from integrations import state_store

theme.preparar_pagina("Produccion MQTT", "📡")
theme.encabezado("MIDDLEWARE · UNS FEMSA (MQTT)",
                 "Produccion en vivo",
                 f"Broker `{settings.MQTT_HOST}:{settings.MQTT_PORT}` · suscrito al "
                 "UNS: `FEMSA/+/MES/KPI/#`, `FEMSA/+/MES/Maintance/#`, "
                 f"`FEMSA/+/Process/#` (+ legado `{settings.MQTT_TOPIC_BASE}/+/production`) · "
                 f"publica la rama `FEMSA/LineaX/ERP/...` retained · OPC UA de referencia "
                 f"`{settings.OPCUA_ENDPOINT}` (puente via Node-RED).")

st.caption("El middleware corre como proceso aparte: `python middleware/run_middleware.py` "
           "(o el servicio `middleware` de docker-compose). Esta pagina lee su estado "
           "desde SQLite y se refresca sola.")


def _vista():
    acum = state_store.produccion_acumulada()
    with st.container(border=True):
        cols = st.columns(3)
        mapa = {a["sku"]: a for a in acum}
        for col, sku in zip(cols, COLOR_SKU):
            a = mapa.get(sku)
            with col:
                if a:
                    st.metric(NOMBRE_CORTO[sku], f"{a['qty_total']:,.0f} un",
                              f"{a['eventos']} reportes · ultimo {a['ultimo'][11:19]} UTC",
                              delta_color="off")
                else:
                    st.metric(NOMBRE_CORTO[sku], "—", "sin reportes aun", delta_color="off")

    st.subheader("✅ Cumplimiento de ordenes de compra")
    pos = state_store.listar_pos(30)
    if not pos:
        st.info("No hay POs vinculadas todavia (crealas en *Ordenes Odoo*).")
    else:
        iconos = {"abierta": "🔵", "cumplida": "🟠", "recibida_odoo": "🟢", "error": "🔴"}
        with st.container(border=True):
            for p in pos:
                avance = min(1.0, p["qty_producida"] / max(p["qty_objetivo"], 1e-9))
                st.progress(avance, text=f"{iconos.get(p['estado'],'⚪')} {p['po_name']} · "
                                         f"{p['sku']} · {p['qty_producida']:,.0f}/"
                                         f"{p['qty_objetivo']:,.0f} un · `{p['estado']}` · "
                                         f"MO `{p.get('mo_name') or '—'}`")

    st.subheader("🕒 Ultimos reportes de produccion")
    ev = state_store.ultimos_eventos(25)
    if ev:
        st.dataframe(pd.DataFrame(ev)[["ts", "linea", "sku", "qty", "topic"]],
                     width="stretch", hide_index=True)
    else:
        st.caption("Sin eventos aun. Publica en "
                   f"`{settings.MQTT_TOPIC_BASE}/L1/production` o usa el boton de prueba.")


try:  # refresco automatico (Streamlit >= 1.37)
    @st.fragment(run_every="5s")
    def _vivo():
        _vista()
    _vivo()
except Exception:  # noqa: BLE001 — fallback manual
    _vista()
    st.button("🔄 Actualizar")

st.divider()

# ------------------------------------------------------------------ publicador de prueba
st.subheader("📤 Publicar reporte de prueba — contrato LEGADO (`Process/GoodCount`)")
st.caption("El camino **principal** hoy es `AvailableQuantity` (valor absoluto que "
          "reporta el MES) — pruébalo en *Pruebas → 4 · Producción*. Este botón sigue "
          "el contrato legado (delta de unidades buenas), útil para pruebas locales "
          "rápidas sin simular un MES completo.")
c1, c2, c3 = st.columns(3)
linea = c1.selectbox("Linea", ["L1", "L2", "L3"])
sku_defecto = {"L1": "P1-CC350-RGB", "L2": "P2-QT1500-PET", "L3": "P3-GARR25L"}[linea]
qty = c2.number_input("Cantidad (un)", 1, 100000,
                      {"L1": 9000, "L2": 2800, "L3": 110}[linea])
c3.text_input("SKU", sku_defecto, disabled=True)

if st.button("📤 Publicar en MQTT", type="primary"):
    try:
        import paho.mqtt.client as mqtt
        cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ulogix-dashboard-pub")
        if settings.MQTT_USER:
            cl.username_pw_set(settings.MQTT_USER, settings.MQTT_PASSWORD)
        cl.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=10)
        from integrations import uns
        topic = f"{uns.raiz()}/{uns.UNS_DE_LINEA[linea]}/Process/GoodCount"
        payload = json.dumps({"value": int(qty), "sku": sku_defecto,
                              "requestedBy": "dashboard",
                              "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        info = cl.publish(topic, payload, qos=settings.MQTT_QOS)
        info.wait_for_publish(timeout=5)
        cl.disconnect()
        st.success(f"Publicado en `{topic}`: `{payload}`")
        st.caption("Si el middleware esta corriendo, el reporte aparecera arriba en ≤5 s.")
    except Exception as e:  # noqa: BLE001
        st.error(f"No se pudo publicar en {settings.MQTT_HOST}:{settings.MQTT_PORT} — {e}")
        st.caption("Recuerda la regla de red del stack: fuera de Docker usa la IP LAN "
                   "del host del broker, no `localhost` ni hostnames de Docker.")

with st.expander("Contrato UNS (config/uns_femsa.yaml) — para Node-RED / Ignition / Tecnomatix"):
    st.markdown(f"""
**Suscripciones del middleware** (QoS {settings.MQTT_QOS}):
`FEMSA/+/MES/KPI/#` · `FEMSA/+/MES/Maintance/#` · `FEMSA/+/Process/#` ·
`FEMSA/MES/KPI/#` · `FEMSA/MES/Maintance/#` (agregado de **planta completa**,
sin linea) · legado `{settings.MQTT_TOPIC_BASE}/+/production`

**Hojas KPI por linea** (numero plano o JSON `{{"value": x}}`):
`Availability, Quality, Performance, OEE, TEEP, DT, MTTR, MTBF, MLT`
```
FEMSA/Linea1/MES/KPI/OEE            0.7712
FEMSA/Linea2/MES/Maintance/MaintanceStatus   OK
FEMSA/MES/KPI/OEE                   0.8069   (planta completa, sin linea)
```
Verificado contra el broker real (Coreflux): las mismas 9 hojas de KPI y 4 de
mantenimiento existen tambien **a nivel planta**, sin segmento de linea —
`interpretar_topico()` las reconoce como `linea='PLANTA'` y quedan en la
misma tabla `kpi_uns` y el mismo tablero de abajo, sin vista aparte.

**Produccion — camino PRINCIPAL: `ERP/AvailableQuantity` (conexion directa al
broker, sin Node-RED de por medio).** El ERP publica (retained) una sola
orden de fabricacion **activa por linea a la vez**; el MES reporta cuanto
lleva producido de esa orden como valor **ABSOLUTO** (no un delta):
```
FEMSA/Linea1/ERP/OrderNumber        WH/MO/00042   (la MO activa, la publica el ERP)
FEMSA/Linea1/ERP/OrderedQuantity    20000         (la publica el ERP)
FEMSA/Linea1/ERP/AvailableQuantity  12500         (la escribe el MES — este ERP solo la lee)
FEMSA/Linea1/ERP/ReservedQuantity   7500          (faltante, la publica el ERP)
```
Cuando `AvailableQuantity >= OrderedQuantity`, el middleware valida en Odoo la
orden de fabricacion vinculada (`mrp.production`): descuenta los componentes
de la BOM (concentrados, etiquetas, tapas, ...) — ya recibidos al crear la
PO — y da entrada al producto terminado; **recien entonces** publica la
SIGUIENTE orden de la cola de ese SKU (nunca dos activas a la vez en la misma
linea). Proteccion contra ruido: valores que retroceden se ignoran, valores
que superan el objetivo se recortan a el — el broker real (Coreflux) tiene un
agente de IA que puede inyectar valores aleatorios en cualquier hoja del UNS
(verificado). Pruebalo en *Pruebas → 4 · Produccion*.

**Contrato LEGADO** (`Process/GoodCount`, delta de unidades buenas) — la rama
`Process` esta libre en el YAML; el middleware acepta por convencion las
hojas `GoodCount / Count / Produccion / Production / value`. Sigue
funcionando (boton de prueba arriba, `tools/simulador_produccion.py`) pero ya
no es necesario en produccion:
```json
FEMSA/Linea1/Process/GoodCount
{{"value": 9000, "requestedBy": "node-red", "timestamp": "..."}}
```

Mapeo de lineas: `Linea1↔L1 (350 ml)`, `Linea2↔L2 (1.5 L)`, `Linea3↔L3 (garrafon)`.
""")

st.subheader("📊 KPIs MES recibidos del UNS")
kpis = state_store.kpis_actuales()
if kpis:
    _piv = (pd.DataFrame(kpis)
            .pivot_table(index="linea", columns="kpi", values="valor_num",
                         aggfunc="last").round(4))
    _orden = [c for c in ["OEE", "Availability", "Performance", "Quality",
                          "TEEP", "DT", "MTTR", "MTBF", "MLT"] if c in _piv.columns]
    st.dataframe(_piv[_orden + [c for c in _piv.columns if c not in _orden]],
                 width="stretch")
    if "PLANTA" in _piv.index:
        st.caption("`PLANTA` = agregado de toda la planta (broker real), no de "
                   "una linea especifica.")
else:
    st.caption("Sin KPIs aun — publica a `FEMSA/LineaX/MES/KPI/...` o corre el "
               "simulador.")

with st.expander("Auditoria del middleware (log)"):
    st.dataframe(pd.DataFrame(state_store.ultimo_log(60)), width="stretch",
                 hide_index=True)
