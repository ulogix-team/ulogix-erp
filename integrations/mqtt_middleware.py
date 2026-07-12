"""
Middleware MQTT v4 — colgado del UNS FEMSA.

  Ignition/Node-RED/Tecnomatix ──► MQTT (UNS FEMSA/...) ──► [MIDDLEWARE]
                                                              ├─ SQLite ERP (kpi_uns, eventos, POs)
                                                              ├─ Odoo API (recepcion de POs)
                                                              └─ publica rama ERP/ (retained)

SUSCRIPCIONES (config/uns_femsa.yaml):
  FEMSA/+/MES/KPI/#        -> Availability, Quality, Performance, OEE, TEEP,
                              DT, MTTR, MTBF  => tabla kpi_uns
  FEMSA/+/MES/Maintance/#  -> MachineID, Last/NextMaintance, MaintanceStatus
  FEMSA/+/Process/#        -> hojas de conteo (GoodCount/Count/Produccion/value)
                              => eventos_produccion + cumplimiento de POs
  plant/+/production       -> contrato legado v1 (compatibilidad)

PUBLICACION (la suite ES el ERP del UNS): al cambiar una PO o llegar
produccion, se publica retained la rama FEMSA/LineaX/ERP/{OrderNumber,
OrderStatus, ScheduleStart/End, ActualStart/End, Available/Reserved/
OrderedQuantity} con la PO abierta mas antigua de la linea (FIFO).
"""
from __future__ import annotations

import json
import signal
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings
from integrations import state_store, uns
from integrations.odoo_client import OdooClient


def _mapa_linea_sku() -> dict[str, str]:
    with open(settings.DATA_DIR / "parametros_planta.json", encoding="utf-8") as f:
        params = json.load(f)
    return {linea: cfg["producto"] for linea, cfg in params["lineas"].items()}


class Middleware:
    def __init__(self) -> None:
        self.odoo = OdooClient()
        self.linea_sku = _mapa_linea_sku()
        self.sku_linea = {v: k for k, v in self.linea_sku.items()}
        self._detener = False
        self._cliente = None          # para publicar ERP al UNS

    # ------------------------------------------------------------- ERP -> UNS
    def publicar_estado_erp(self, linea: str) -> None:
        if self._cliente is None:
            return
        pos = [p for p in state_store.listar_pos(200)
               if p["sku"] == self.linea_sku.get(linea)]
        if not pos:
            return
        abiertas = [p for p in pos if p["estado"] == "abierta"]
        po = sorted(abiertas, key=lambda p: p["creado_ts"])[0] if abiertas else pos[0]
        try:
            uns.publicar_erp(self._cliente, linea, uns.erp_desde_po(po))
        except Exception as e:  # noqa: BLE001
            state_store.log("uns", "publicar_erp ERROR", f"{linea}: {e}")

    # ------------------------------------------------------------- negocio
    def _procesar_produccion(self, linea: str, sku: str, qty: float,
                             topic: str, payload) -> list[dict]:
        state_store.registrar_evento(linea, sku, qty, topic=topic,
                                     payload=payload if isinstance(payload, dict)
                                     else {"value": payload})
        completadas = state_store.acumular_produccion(sku, qty, linea)
        for po in completadas:
            res = self.odoo.recibir_orden(po.get("odoo_id"), po["po_name"])
            estado = "recibida_odoo" if res.get("ok") else "error"
            state_store.marcar_po(po["po_name"], estado,
                                  res.get("detalle", res.get("modo", "")))
            state_store.log("middleware", f"po_{estado}",
                            f"{po['po_name']} cubierta por produccion de {sku}")
        self.publicar_estado_erp(linea)
        return completadas

    def manejar_mensaje(self, topic: str, raw: bytes | str) -> list[dict]:
        # ---------- 1) topicos del UNS
        info = uns.interpretar_topico(topic)
        if info is not None:
            valor = uns.valor_payload(raw)
            if info["rama"].startswith("MES"):
                state_store.registrar_kpi(info["linea"], info["rama"],
                                          info["hoja"], valor, topic)
                return []
            if info["rama"].startswith("Process") or info["rama"] == "Process" \
                    or info["hoja"].lower() in uns.HOJAS_PRODUCCION:
                if info["hoja"].lower() not in uns.HOJAS_PRODUCCION:
                    state_store.registrar_kpi(info["linea"], "Process",
                                              info["hoja"], valor, topic)
                    return []
                try:
                    qty = float(valor)
                except (TypeError, ValueError):
                    return []
                if qty <= 0:
                    return []
                sku = self.linea_sku.get(info["linea"], "")
                if not sku:
                    return []
                return self._procesar_produccion(info["linea"], sku, qty,
                                                 topic, valor)
            return []
        # ---------- 2) contrato legado plant/+/production
        partes = topic.split("/")
        if len(partes) >= 3 and partes[0] == settings.MQTT_TOPIC_BASE \
                and partes[2] == "production":
            try:
                data = json.loads(raw if isinstance(raw, str)
                                  else raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                try:
                    data = {"qty": float(raw)}
                except (TypeError, ValueError):
                    return []
            if not isinstance(data, dict):
                data = {"qty": float(data)}
            qty = data.get("qty", data.get("value"))
            try:
                qty = float(qty)
            except (TypeError, ValueError):
                return []
            if qty <= 0:
                return []
            linea = str(data.get("line", data.get("linea", partes[1])) or partes[1])
            sku = str(data.get("sku", "") or self.linea_sku.get(linea, ""))
            if not sku:
                return []
            return self._procesar_produccion(linea, sku, qty, topic, data)
        state_store.log("mqtt", "mensaje_ignorado", topic)
        return []

    # ------------------------------------------------------------- loop MQTT
    def correr(self) -> None:
        import paho.mqtt.client as mqtt

        cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                              client_id=settings.MQTT_CLIENT_ID,
                              protocol=mqtt.MQTTv5)
        if settings.MQTT_USER:
            cliente.username_pw_set(settings.MQTT_USER, settings.MQTT_PASSWORD)
        self._cliente = cliente

        topicos = uns.suscripciones() + [f"{settings.MQTT_TOPIC_BASE}/+/production"]

        def on_connect(cl, userdata, flags, reason_code, properties=None):
            if getattr(reason_code, "is_failure", False):
                state_store.log("mqtt", "conexion_fallida", str(reason_code))
                return
            for t in topicos:
                cl.subscribe(t, qos=settings.MQTT_QOS)
            state_store.log("mqtt", "conectado",
                            f"{settings.MQTT_HOST}:{settings.MQTT_PORT} "
                            f"sub={topicos}")
            print(f"[middleware] conectado a {settings.MQTT_HOST}:"
                  f"{settings.MQTT_PORT}; suscrito a: {', '.join(topicos)}")
            for linea in self.linea_sku:      # estado ERP inicial retenido
                self.publicar_estado_erp(linea)

        def on_message(cl, userdata, msg):
            done = self.manejar_mensaje(msg.topic, msg.payload)
            extra = (f" | POs cumplidas: {[p['po_name'] for p in done]}"
                     if done else "")
            print(f"[middleware] {msg.topic} -> {msg.payload[:100]!r}{extra}")

        cliente.on_connect = on_connect
        cliente.on_message = on_message

        def parar(*_):
            self._detener = True
        signal.signal(signal.SIGINT, parar)
        signal.signal(signal.SIGTERM, parar)

        while not self._detener:
            try:
                cliente.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=30)
                cliente.loop_start()
                while not self._detener:
                    time.sleep(0.5)
                cliente.loop_stop(); cliente.disconnect()
            except Exception as e:  # noqa: BLE001
                state_store.log("mqtt", "reconexion", str(e))
                print(f"[middleware] broker no disponible ({e}); reintento en 5 s "
                      "(fuera de Docker usa la IP LAN, no 'localhost'/'mosquitto')")
                time.sleep(5)


if __name__ == "__main__":
    Middleware().correr()
