"""
Middleware MQTT v4 — colgado del UNS FEMSA. Conexion DIRECTA al broker
(no requiere Node-RED de por medio para este flujo).

  MES real o su simulacion (Coreflux) ──► MQTT (UNS FEMSA/...) ──► [MIDDLEWARE]
                                                              ├─ SQLite ERP (kpi_uns, eventos, POs)
                                                              ├─ Odoo API (valida la orden de
                                                              │  fabricacion vinculada al SKU)
                                                              └─ publica rama ERP/ (retained,
                                                                 salvo AvailableQuantity)

SUSCRIPCIONES (config/uns_femsa.yaml, integrations/uns.py: suscripciones()):
  FEMSA/+/MES/KPI/#          -> 9 KPI por linea (incl. MLT) => tabla kpi_uns
  FEMSA/+/MES/Maintance/#    -> estado de mantenimiento
  FEMSA/MES/KPI|Maintance/#  -> agregado de PLANTA COMPLETA (linea='PLANTA')
  FEMSA/+/ERP/AvailableQuantity -> **camino PRINCIPAL**: el MES reporta,
                              como valor ABSOLUTO (no delta), cuanto lleva
                              producido de la ORDEN ACTIVA de esa linea
                              (state_store.orden_activa) => cumplimiento de
                              POs/MOs
  FEMSA/+/Process/#          -> contrato LEGADO (GoodCount/Count/Produccion,
                              delta) para pruebas locales -- ya no necesario
                              en produccion, ver decision #14 de CLAUDE.md
  plant/+/production         -> contrato legado v1 (compatibilidad)

Cada PO de insumos (concentrados, etiquetas, tapas, ...) se recibe de
inmediato al crearse desde la pagina *Ordenes Odoo* (para fines practicos, sin
modelar el lead time real del proveedor) y queda vinculada a una orden de
fabricacion (mrp.production) de la BOM del sku. Protocolo UNS: **una sola
orden de fabricacion activa por linea a la vez** -- cuando `AvailableQuantity`
alcanza el objetivo de la orden activa, el middleware valida esa orden de
fabricacion (button_mark_done): Odoo descuenta los componentes de la BOM y
da entrada al producto terminado; recien entonces se publica/avanza a la
SIGUIENTE orden de la cola de ese SKU.

INVENTARIO EN VIVO (ERP local + Odoo), no solo al cerrar la orden:
- ERP local: cada avance real de `AvailableQuantity`/`GoodCount` entra de
  inmediato al inventario de `state_store` (`_aplicar_produccion_a_stock`,
  via `actualizar_disponible`/`acumular_produccion`): sube producto
  terminado y Odoo baja materia prima según su BOM nativa. Página *Inventario*,
  seccion "Stock actual".
- Odoo: cada `INTERVALO_SYNC_ODOO` s, `sincronizar_parciales_odoo()` postea
  en Odoo (via el mecanismo nativo de backorder de `mrp.production`) el
  avance acumulado desde el ultimo sync -- la orden queda parcialmente
  'done' por esa porcion (descuenta BOM, entra terminado) y Odoo crea sola
  una MO backorder por el remanente, que el middleware sigue rastreando
  (`po_tracking.mo_id`/`mo_name` se actualiza a esa backorder). El cierre
  FINAL de la orden (cuando llega a su objetivo) sigue siendo
  `completar_orden_fabricacion` (sin backorder, cubre todo lo que reste) --
  no cambia.

PUBLICACION (la suite ES el ERP del UNS): publica retained la rama
FEMSA/LineaX/ERP/{OrderNumber (= nombre de la MO), OrderStatus,
ScheduleStart/End, ActualStart/End, ReservedQuantity, OrderedQuantity} de la
orden activa de cada linea -- **`AvailableQuantity` NO se publica aqui**, es
dato de entrada del MES (ver integrations/uns.py). Se reafirma cada
`INTERVALO_REPUBLICAR` segundos (autocuracion si el broker tiene ruido
externo -- Coreflux Hub puede sobreescribir hojas del UNS via su agente de
IA, verificado) y cada vez que se crea/completa una orden.
"""
from __future__ import annotations

import json
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings
from integrations import state_store, uns
from integrations.odoo_client import OdooClient
from integrations.sheets_client import Contabilidad

INTERVALO_REPUBLICAR = 15.0  # s -- reafirma la orden activa (autocuracion contra ruido)
INTERVALO_SYNC_ODOO = 60.0   # s -- postea a Odoo (backorder parcial) el avance acumulado


def _mapa_linea_sku() -> dict[str, str]:
    # El loader central elige Sheets en operacion estricta y los fixtures
    # locales en QA/dry-run. Leer siempre Forecast_Configuracion rompia el
    # contrato offline del middleware.
    from core.forecast import cargar_parametros
    params = cargar_parametros()
    return {linea: cfg["producto"] for linea, cfg in params["lineas"].items()}


class Middleware:
    def __init__(self) -> None:
        self.odoo = OdooClient()
        self.contabilidad = Contabilidad()
        self.linea_sku = _mapa_linea_sku()
        self.sku_linea = {v: k for k, v in self.linea_sku.items()}
        self._detener = False
        self._cliente = None          # para publicar ERP al UNS

    def _persistir_produccion_externa(self, linea: str, sku: str,
                                      cantidad_delta: float) -> None:
        """Anexa el avance real a LibroProduccion usando costos de Sheets.

        Para AvailableQuantity se recibe el delta validado, no el contador
        absoluto, evitando duplicar unidades en el libro financiero.
        """
        if cantidad_delta <= 0:
            return
        try:
            from core.finanzas_negocio import _maestro
            self.contabilidad.registrar_produccion([{
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "linea": linea, "sku": sku, "qty": cantidad_delta,
            }], _maestro().reset_index())
        except Exception as exc:  # noqa: BLE001
            state_store.log("sheets", "LibroProduccion ERROR", str(exc))
            if settings.EXTERNAL_ONLY:
                raise

    def _persistir_kpi_externo(self, linea: str, rama: str, kpi: str,
                               valor, topic: str) -> None:
        try:
            try:
                numero, texto = float(valor), ""
            except (TypeError, ValueError):
                numero, texto = None, str(valor)
            self.contabilidad.registrar_kpis_uns([{
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "linea": linea, "rama": rama, "kpi": kpi,
                "valor_num": numero, "valor_txt": texto, "topic": topic,
            }])
        except Exception as exc:  # noqa: BLE001
            state_store.log("sheets", "KPIs_UNS ERROR", str(exc))
            if settings.EXTERNAL_ONLY:
                raise

    # ------------------------------------------------------------- ERP -> UNS
    def publicar_estado_erp(self, linea: str) -> None:
        """Publica (retained) la orden ACTIVA de esa linea -- la mas antigua
        'abierta' de su sku (state_store.orden_activa). Si no hay ninguna
        abierta (cola vacia), no publica nada nuevo: el ultimo estado
        retenido queda como 'CLOSED'/'COMPLETED' de la ultima que se hizo."""
        if self._cliente is None:
            return
        po = self.odoo.orden_activa_ulogix(linea)
        if po is None:
            return
        po.setdefault("po_name", po["mo_name"])
        po.setdefault("creado_ts", "")
        po.setdefault("actualizado_ts", "")
        po.setdefault("detalle", po.get("x_ulogix_mes") or "")
        try:
            uns.publicar_erp(self._cliente, linea, uns.erp_desde_po(po))
        except Exception as e:  # noqa: BLE001
            state_store.log("uns", "publicar_erp ERROR", f"{linea}: {e}")

    # ------------------------------------------------------------- negocio
    def _completar_orden(self, linea: str, sku: str, po: dict) -> None:
        """Cierra el ciclo cuando la orden activa queda 'cumplida': valida
        la orden de fabricacion en Odoo (descuenta la BOM -- tapas,
        etiquetas, concentrado... -- y da entrada al terminado) y
        publica/avanza a la SIGUIENTE orden de la cola de ese SKU (implicito:
        `publicar_estado_erp` vuelve a consultar `orden_activa`, que ya
        excluye la que se acaba de cerrar)."""
        res = self.odoo.completar_orden_fabricacion(po.get("mo_id"), po.get("mo_name", ""))
        estado = "recibida_odoo" if res.get("ok") else "error"
        if self.odoo.dry_run:
            state_store.marcar_po(po["po_name"], estado)
        state_store.log("middleware", f"mo_{estado}",
                        f"{po.get('mo_name')} cubierta por produccion de {sku}")
        self.publicar_estado_erp(linea)

    def sincronizar_parciales_odoo(self) -> None:
        """Cada `INTERVALO_SYNC_ODOO` s: para cada orden 'abierta' que avanzo
        localmente desde el ultimo sync (`state_store.pos_para_sincronizar_odoo`),
        postea ese avance en Odoo con `avanzar_produccion_parcial` (backorder
        parcial -- descuenta la BOM y entra el terminado por esa porcion, SIN
        esperar a que la orden completa cierre) y actualiza el puntero local
        a la MO backorder que queda abierta. Es la razon por la que el
        inventario de Odoo se mueve *a medida que se produce* y no solo al
        completar la orden entera -- ver decision de diseno correspondiente
        en CLAUDE.md. El cierre FINAL de cada orden lo sigue haciendo
        `_completar_orden`/`completar_orden_fabricacion` (sin backorder,
        cubre todo lo que reste)."""
        for po in self.odoo.listar_mo_ulogix_activas():
            delta = po["qty_producida"] - po["qty_sincronizada_odoo"]
            if delta <= 0 or not po.get("mo_id"):
                continue
            res = self.odoo.avanzar_produccion_parcial(po["mo_id"], po.get("mo_name", ""),
                                                        delta)
            if res.get("ok"):
                nuevo_id = res.get("mo_id_nuevo", po["mo_id"])
                nuevo_nombre = res.get("mo_name_nuevo", po.get("mo_name", ""))
                self.odoo.heredar_trazabilidad_backorder(
                    po, nuevo_id, nuevo_nombre, po["qty_producida"])
            else:
                state_store.log("odoo", "sync_parcial_odoo ERROR",
                                f"{po['po_name']}: {res.get('detalle')}")

    def _procesar_disponible(self, linea: str, sku: str, disponible: float,
                             topic: str, payload) -> list[dict]:
        """Camino PRINCIPAL: el MES reporta `AvailableQuantity` (valor
        ABSOLUTO, no delta) de la orden activa de esa linea."""
        state_store.registrar_evento(linea, sku, disponible, topic=topic,
                                     payload=payload if isinstance(payload, dict)
                                     else {"value": payload})
        actualizada = self.odoo.actualizar_disponible_ulogix(linea, disponible)
        if actualizada is None:
            return []
        self._persistir_produccion_externa(linea, sku, actualizada["delta"])
        if actualizada["completada"]:
            self._completar_orden(linea, sku, actualizada)
            return [actualizada]
        return []

    def _procesar_produccion(self, linea: str, sku: str, qty: float,
                             topic: str, payload) -> list[dict]:
        """Contrato LEGADO `Process/GoodCount` (delta de unidades buenas, no
        valor absoluto) -- sigue funcionando para pruebas locales
        (tools/simulador_produccion.py, boton de prueba de la pagina
        Produccion MQTT), pero el camino principal en produccion es
        `AvailableQuantity` (ver `_procesar_disponible`)."""
        activa = self.odoo.orden_activa_ulogix(linea)
        if activa is None:
            return []
        return self._procesar_disponible(
            linea, sku, float(activa["qty_producida"]) + qty, topic, payload)

    def manejar_mensaje(self, topic: str, raw: bytes | str) -> list[dict]:
        # ---------- 1) topicos del UNS
        info = uns.interpretar_topico(topic)
        if info is not None:
            valor = uns.valor_payload(raw)
            if info["rama"] == "ERP" and info["hoja"] == "AvailableQuantity":
                sku = self.linea_sku.get(info["linea"], "")
                if not sku:
                    return []
                try:
                    disponible = float(valor)
                except (TypeError, ValueError):
                    return []
                if disponible < 0:
                    return []
                return self._procesar_disponible(info["linea"], sku,
                                                  disponible, topic, valor)
            if info["rama"].startswith("MES"):
                state_store.registrar_kpi(info["linea"], info["rama"],
                                          info["hoja"], valor, topic)
                self._persistir_kpi_externo(info["linea"], info["rama"],
                                             info["hoja"], valor, topic)
                return []
            if info["rama"].startswith("Process") or info["rama"] == "Process" \
                    or info["hoja"].lower() in uns.HOJAS_PRODUCCION:
                if info["hoja"].lower() not in uns.HOJAS_PRODUCCION:
                    state_store.registrar_kpi(info["linea"], "Process",
                                              info["hoja"], valor, topic)
                    self._persistir_kpi_externo(info["linea"], "Process",
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
                ultimo_republicar = ultimo_sync_odoo = time.time()
                while not self._detener:
                    time.sleep(0.5)
                    # autocuracion: reafirma la orden activa de cada linea
                    # cada INTERVALO_REPUBLICAR s -- pisa cualquier ruido
                    # externo que haya sobreescrito OrderNumber/etc (ver
                    # docstring del modulo) y publica ordenes nuevas creadas
                    # desde el dashboard sin esperar un mensaje de produccion
                    if time.time() - ultimo_republicar >= INTERVALO_REPUBLICAR:
                        for linea in self.linea_sku:
                            self.publicar_estado_erp(linea)
                        ultimo_republicar = time.time()
                    # inventario de Odoo "a medida que se produce": postea a
                    # Odoo el avance acumulado desde el ultimo sync (backorder
                    # parcial), sin esperar a que la orden completa cierre
                    if time.time() - ultimo_sync_odoo >= INTERVALO_SYNC_ODOO:
                        self.sincronizar_parciales_odoo()
                        ultimo_sync_odoo = time.time()
                cliente.loop_stop(); cliente.disconnect()
            except Exception as e:  # noqa: BLE001
                state_store.log("mqtt", "reconexion", str(e))
                print(f"[middleware] broker no disponible ({e}); reintento en 5 s "
                      "(fuera de Docker usa la IP LAN, no 'localhost'/'mosquitto')")
                time.sleep(5)


if __name__ == "__main__":
    Middleware().correr()
