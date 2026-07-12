import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from app.ui import theme
from config import settings

theme.preparar_pagina("Pruebas de integracion", "🧪")
theme.encabezado("DIAGNOSTICO · APIS Y UNS",
                 "Pruebas de comunicacion",
                 "Verifica en vivo cada integracion: MQTT/UNS (broker "
                 f"{settings.MQTT_HOST}), Odoo XML-RPC y Google Sheets. "
                 "Cada prueba es inocua: usa topicos/celdas de verificacion.")

tab_mqtt, tab_odoo, tab_sheets, tab_prod = st.tabs(
    ["📡 1 · MQTT — UNS FEMSA", "🟣 2 · Odoo — XML-RPC", "📗 3 · Google Sheets",
     "🏭 4 · Producción (orden activa)"])

# ============================================================ 1. MQTT / UNS
with tab_mqtt:
    st.caption(f"Broker: `{settings.MQTT_HOST}:{settings.MQTT_PORT}` · prueba de "
               "eco: publica en `FEMSA/_pruebas/Process/Ping` y verifica la "
               "recepcion suscribiendose al mismo topico (round-trip completo).")
    if st.button("▶ Probar MQTT (publicar + suscribir eco)", key="btn_mqtt",
                 type="primary"):
        try:
            import paho.mqtt.client as mqtt

            marca = str(uuid.uuid4())[:8]
            topico = "FEMSA/_pruebas/Process/Ping"
            recibido: dict = {}

            cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id=f"ulogix-prueba-{marca}")
            if settings.MQTT_USER:
                cl.username_pw_set(settings.MQTT_USER, settings.MQTT_PASSWORD)

            def on_msg(c, u, m):
                recibido["payload"] = m.payload.decode("utf-8", "replace")

            cl.on_message = on_msg
            t0 = time.time()
            cl.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=10)
            cl.loop_start()
            cl.subscribe(topico, qos=settings.MQTT_QOS)
            time.sleep(0.4)
            cl.publish(topico, json.dumps({"value": marca, "origen": "pagina-pruebas"}),
                       qos=settings.MQTT_QOS)
            limite = time.time() + 6
            while "payload" not in recibido and time.time() < limite:
                time.sleep(0.1)
            cl.loop_stop(); cl.disconnect()
            ms = (time.time() - t0) * 1000
            if recibido.get("payload") and marca in recibido["payload"]:
                st.success(f"✅ Conectado y eco recibido en {ms:,.0f} ms — el broker "
                           "acepta publicacion y suscripcion con QoS "
                           f"{settings.MQTT_QOS}.")
                st.code(recibido["payload"], language="json")
            else:
                st.error("Conexion establecida pero NO llego el eco en 6 s. Revisa "
                         "ACLs del broker o el firewall del puerto 1883.")
        except Exception as e:  # noqa: BLE001
            st.error(f"❌ No fue posible conectar al broker: {e}")
            st.caption("Fuera de Docker usa la IP LAN del host (no `localhost` ni "
                       "`mosquitto`). Dentro de docker-compose, el nombre del "
                       "servicio si resuelve.")

    with st.expander("Publicar un mensaje UNS manual (produccion de prueba)"):
        c1, c2, c3 = st.columns(3)
        linea_uns = c1.selectbox("Linea", ["Linea1", "Linea2", "Linea3"])
        qty = c2.number_input("GoodCount", 1, 100000, 500)
        if c3.button("Publicar a FEMSA/…/Process/GoodCount"):
            try:
                import paho.mqtt.client as mqtt
                cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                 client_id="ulogix-prueba-pub")
                if settings.MQTT_USER:
                    cl.username_pw_set(settings.MQTT_USER, settings.MQTT_PASSWORD)
                cl.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=10)
                cl.loop_start()
                cl.publish(f"FEMSA/{linea_uns}/Process/GoodCount",
                           json.dumps({"value": int(qty), "requestedBy": "dashboard"}),
                           qos=settings.MQTT_QOS)
                time.sleep(0.3); cl.loop_stop(); cl.disconnect()
                st.success(f"Publicado: FEMSA/{linea_uns}/Process/GoodCount = {qty}. "
                           "Si el middleware esta corriendo, aparecera en "
                           "Produccion (MQTT) y descontara la PO abierta.")
            except Exception as e:  # noqa: BLE001
                st.error(f"Error publicando: {e}")

# ============================================================ 2. Odoo
with tab_odoo:
    st.caption(f"URL: `{settings.ODOO_URL or 'sin configurar'}` · DB: "
               f"`{settings.ODOO_DB or '—'}` · usuario: `{settings.ODOO_USER or '—'}`")
    if settings.ODOO_USER in ("", "TU_CORREO_DE_LOGIN_ODOO"):
        st.warning("Falta **ODOO_USER** en `.env`: debe ser el correo con el que "
                   "inicias sesion en ulogix-admin.odoo.com (la API key ya esta).")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("▶ Probar conexion (authenticate + version)"):
            from integrations.odoo_client import OdooClient
            res = OdooClient().probar_conexion()
            (st.success if res.get("ok") else st.error)(json.dumps(res, indent=1,
                                                                   ensure_ascii=False))
    with c2:
        if st.button("▶ Crear orden de compra de PRUEBA (1 unidad)"):
            from integrations.odoo_client import LineaPedido, OdooClient
            cli = OdooClient()
            res = cli.crear_orden_compra(
                "Proveedor de prueba Ulogix",
                [LineaPedido(nombre="Articulo de prueba API",
                             default_code="TEST-PING",
                             cantidad=1, precio_unitario=1000.0)],
                referencia="PRUEBA-API")
            if res.get("ok"):
                st.success(f"✅ PO creada en modo `{res.get('modo')}`: "
                           f"{res.get('po_name', res)}")
                st.caption("En modo real queda como borrador 'PRUEBA-API' en Compras; "
                           "puedes cancelarla desde Odoo.")
            else:
                st.error(res)
    c3, c4 = st.columns(2)
    with c3:
        if st.button("▶ Crear orden de fabricacion de PRUEBA (P1, 1 unidad)"):
            from integrations.odoo_client import OdooClient
            res = OdooClient().crear_orden_fabricacion(
                "P1-CC350-RGB", 1, referencia="PRUEBA-API-MO")
            st.success(f"✅ MO creada en modo `{res.get('modo')}`: {res.get('name', res)}")
            st.caption("Requiere haber corrido `tools/bootstrap_odoo.py` (crea la BOM de P1).")
    with c4:
        if st.button("▶ Completar (validar) esa MO de PRUEBA"):
            from integrations.odoo_client import OdooClient
            cli = OdooClient()
            res_mo = cli.crear_orden_fabricacion("P1-CC350-RGB", 1, referencia="PRUEBA-API-MO")
            res = cli.completar_orden_fabricacion(res_mo.get("id"), res_mo.get("name", ""))
            (st.success if res.get("ok") else st.error)(json.dumps(res, indent=1,
                                                                    ensure_ascii=False))
    c5, c6 = st.columns(2)
    with c5:
        if st.button("▶ Crear orden de venta de PRUEBA (P1, 1 unidad, sin facturar)"):
            from integrations.odoo_client import LineaPedido, OdooClient
            res = OdooClient().crear_orden_venta(
                "Cliente de prueba Ulogix",
                [LineaPedido(nombre="Coca-Cola 350 ml vidrio retornable",
                             default_code="P1-CC350-RGB", cantidad=1,
                             precio_unitario=2200.0)],
                referencia="PRUEBA-API-SO", confirmar=True, entregar=True, facturar=False)
            st.success(f"✅ SO creada en modo `{res.get('modo')}`: {res.get('name', res)}")
            st.caption("Requiere que P1 exista y tenga stock (corre primero la prueba "
                       "de fabricacion de arriba).")
    with c6:
        if st.button("▶ Facturar esa orden de venta de PRUEBA"):
            from integrations.odoo_client import LineaPedido, OdooClient
            cli = OdooClient()
            res_so = cli.crear_orden_venta(
                "Cliente de prueba Ulogix",
                [LineaPedido(nombre="Coca-Cola 350 ml vidrio retornable",
                             default_code="P1-CC350-RGB", cantidad=1,
                             precio_unitario=2200.0)],
                referencia="PRUEBA-API-SO", confirmar=True, entregar=True, facturar=False)
            res = cli.facturar_orden_venta(res_so.get("id"), res_so.get("name", ""))
            (st.success if res.get("ok") else st.error)(json.dumps(res, indent=1,
                                                                    ensure_ascii=False))
    st.caption("Para poblar Odoo desde cero (productos P1/P2/P3 con EAN-13, "
               "componentes, proveedores y listas de materiales): "
               "`python tools/bootstrap_odoo.py` — es idempotente. Las pruebas de "
               "arriba tambien lo son: reintentarlas reutiliza la misma PO/MO/SO "
               "en vez de duplicarla.")

# ============================================================ 3. Google Sheets
with tab_sheets:
    sa_email = "—"
    try:
        sa_email = json.load(open(settings.GOOGLE_SA_JSON))["client_email"]
    except Exception:  # noqa: BLE001
        pass
    st.caption(f"Credencial: `{settings.GOOGLE_SA_JSON}` · cuenta: `{sa_email}` · "
               f"spreadsheet: `{settings.SHEETS_SPREADSHEET_ID or 'SIN ID — pega el '
               'ID del libro en .env'}`")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("▶ Probar Sheets (escribir + releer)"):
            from integrations.sheets_client import Contabilidad
            res = Contabilidad().probar()
            (st.success if res.get("ok") else st.error)(json.dumps(res, indent=1,
                                                                   ensure_ascii=False))
    with c2:
        if st.button("▶ Publicar hojas Tiempos y OEE"):
            from integrations.sheets_client import Contabilidad
            cli = Contabilidad()
            d1 = cli.publicar_tiempos(theme.datos_pronostico()["mensual"])
            d2 = cli.publicar_oee()
            st.success(f"Hoja **Tiempos** → {d1} · hoja **OEE** → {d2}")
    with c3:
        if st.button("▶ Leer hoja Parametros del libro"):
            from integrations.sheets_client import Contabilidad
            par = Contabilidad().leer_parametros()
            if par:
                st.dataframe(pd.DataFrame(list(par.items()),
                                          columns=["parametro", "valor"]),
                             width="stretch", hide_index=True)
            else:
                st.warning("No se pudo leer 'Parametros' (¿libro compartido con la "
                           "cuenta de servicio y con ID en .env?).")
    st.info("**Como conectar el libro**: sube `Modelo_FEMSA_Ulogix_2026.xlsx` a "
            "Drive → abrelo como Google Sheets → botón *Compartir* → agrega "
            f"`{sa_email}` como **Editor** → copia el ID de la URL "
            "(`docs.google.com/spreadsheets/d/`**`ID`**`/edit`) → pegalo en `.env` "
            "como `SHEETS_SPREADSHEET_ID` y reinicia la app.")

# ============================================================ 4. Produccion (orden activa)
with tab_prod:
    from integrations import state_store

    st.caption(
        "El ERP publica (retained) **una sola orden de fabricación activa por "
        "línea a la vez**: `FEMSA/LineaX/ERP/OrderNumber` (= la MO), "
        "`OrderedQuantity`, etc. El **MES** reporta el avance en "
        "`FEMSA/LineaX/ERP/AvailableQuantity` como **valor absoluto** (no un "
        "delta) — cuando alcanza el objetivo, el middleware valida esa MO en "
        "Odoo (descuenta la BOM: tapas, etiquetas, concentrado...) y **avanza "
        "solo** a la siguiente orden de la cola de ese SKU. Protección contra "
        "ruido: valores que retroceden se ignoran, valores que superan el "
        "objetivo se recortan a él (el broker real de Coreflux tiene un agente "
        "de IA que puede inyectar valores aleatorios — verificado).")

    st.subheader("Orden activa por línea (estado real, sin MQTT)")
    with open(settings.DATA_DIR / "parametros_planta.json", encoding="utf-8") as _f:
        _linea_sku = {ln: cfg["producto"] for ln, cfg in json.load(_f)["lineas"].items()}
    filas_activas = []
    for linea, sku in _linea_sku.items():
        po = state_store.orden_activa(sku)
        if po:
            filas_activas.append({
                "linea": linea, "sku": sku, "po_name": po["po_name"],
                "mo_name": po.get("mo_name") or "—",
                "qty_producida": po["qty_producida"], "qty_objetivo": po["qty_objetivo"],
                "avance_pct": round(100 * po["qty_producida"] / max(po["qty_objetivo"], 1e-9), 1),
                "estado": po["estado"]})
        else:
            filas_activas.append({"linea": linea, "sku": sku, "po_name": "— cola vacía —",
                                  "mo_name": "—", "qty_producida": 0, "qty_objetivo": 0,
                                  "avance_pct": 0, "estado": "—"})
    st.dataframe(pd.DataFrame(filas_activas), width="stretch", hide_index=True)
    st.caption("Recarga la página (o usa el botón de abajo) para refrescar tras publicar.")

    st.divider()
    st.subheader("Prueba LOCAL (sin MQTT — llama la lógica directamente)")
    st.caption("Prueba `state_store.actualizar_disponible()` sin depender de que el "
               "middleware esté corriendo como proceso aparte — útil para validar la "
               "lógica de ruido/recorte/avance de cola al instante.")
    cl1, cl2, cl3 = st.columns(3)
    linea_local = cl1.selectbox("Línea", list(_linea_sku), key="linea_local_aq")
    sku_local = _linea_sku[linea_local]
    disponible_local = cl2.number_input("AvailableQuantity a simular", 0, 10_000_000, 100,
                                        key="disp_local")
    if cl3.button("▶ Aplicar localmente", type="primary"):
        antes = state_store.orden_activa(sku_local)
        completada = state_store.actualizar_disponible(sku_local, float(disponible_local))
        despues = state_store.orden_activa(sku_local)
        if antes is None:
            st.warning(f"No hay ninguna orden abierta para {sku_local} — créala primero "
                      "en *Órdenes Odoo*.")
        elif completada:
            st.success(f"✅ {completada['po_name']} quedó **cumplida** "
                      f"({completada['qty_producida']:,.0f}/{completada['qty_objetivo']:,.0f}). "
                      "En el middleware real esto dispara `completar_orden_fabricacion()` "
                      "(Odoo) y avanza la cola.")
            if despues:
                st.caption(f"Siguiente orden activa: **{despues['po_name']}** "
                          f"({despues['qty_producida']:,.0f}/{despues['qty_objetivo']:,.0f})")
            else:
                st.caption("Cola vacía: no queda ninguna otra orden abierta para ese SKU.")
        elif despues and antes and despues["qty_producida"] == antes["qty_producida"]:
            st.info(f"Sin cambio: {disponible_local:,.0f} no es mayor que el avance ya "
                   f"registrado ({antes['qty_producida']:,.0f}) — tratado como ruido "
                   "(la producción real nunca retrocede) y descartado.")
        else:
            st.info(f"Avance registrado sin completar la orden todavía: "
                   f"{despues['qty_producida']:,.0f}/{despues['qty_objetivo']:,.0f}.")

    st.divider()
    st.subheader("Prueba REAL por MQTT (requiere el middleware corriendo aparte)")
    st.caption("Publica de verdad en `FEMSA/LineaX/ERP/AvailableQuantity` — si "
               "`python middleware/run_middleware.py` (o el contenedor `middleware`) "
               "está corriendo, procesará el mensaje igual que lo haría un MES real.")
    cm1, cm2, cm3 = st.columns(3)
    linea_mqtt = cm1.selectbox("Línea", list(_linea_sku), key="linea_mqtt_aq")
    disponible_mqtt = cm2.number_input("AvailableQuantity a publicar", 0, 10_000_000, 100,
                                       key="disp_mqtt")
    if cm3.button("📤 Publicar en MQTT", key="btn_pub_aq"):
        try:
            import paho.mqtt.client as mqtt
            cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ulogix-prueba-aq")
            if settings.MQTT_USER:
                cl.username_pw_set(settings.MQTT_USER, settings.MQTT_PASSWORD)
            cl.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=10)
            topico = f"FEMSA/{linea_mqtt}/ERP/AvailableQuantity"
            payload = json.dumps({"value": int(disponible_mqtt), "unit": "u"})
            info = cl.publish(topico, payload, qos=settings.MQTT_QOS, retain=True)
            info.wait_for_publish(timeout=5)
            cl.disconnect()
            st.success(f"Publicado `{topico}` = {payload}. Revisa la tabla de arriba en "
                      "unos segundos (o el log de auditoría abajo) para ver si el "
                      "middleware lo procesó.")
        except Exception as e:  # noqa: BLE001
            st.error(f"No se pudo publicar en {settings.MQTT_HOST}:{settings.MQTT_PORT} — {e}")

    with st.expander("Auditoría de producción (últimos eventos + log)"):
        st.dataframe(pd.DataFrame(state_store.ultimos_eventos(30))
                    [["ts", "linea", "sku", "qty", "topic"]] if state_store.ultimos_eventos(1)
                    else pd.DataFrame(), width="stretch", hide_index=True)
        st.dataframe(pd.DataFrame(state_store.ultimo_log(30)), width="stretch",
                    hide_index=True)
