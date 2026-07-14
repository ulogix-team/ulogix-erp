"""Pruebas funcionales de las integraciones externas del ERP.

Por defecto hace lecturas y un eco MQTT no retenido. ``--flujo-completo``
ejecuta una transaccion idempotente de una unidad: compra+recepcion+factura de
proveedor, manufactura+BOM y venta+entrega+factura de cliente. Las referencias
QA no entran en la cola MQTT de produccion (no empiezan por ``ULOGIX/``).
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import date
from pathlib import Path

import paho.mqtt.client as mqtt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import settings  # noqa: E402
from integrations.odoo_client import LineaPedido, OdooClient  # noqa: E402
from integrations.rrhh_client import leer_empleados  # noqa: E402
from integrations.sheets_client import Contabilidad  # noqa: E402


class QA:
    def __init__(self) -> None:
        self.fallos: list[str] = []
        self.avisos: list[str] = []

    def check(self, nombre: str, condicion: bool, detalle: str = "") -> None:
        print(f"[{'OK' if condicion else 'FALLA'}] {nombre}: {detalle}")
        if not condicion:
            self.fallos.append(nombre)

    def aviso(self, nombre: str, detalle: str) -> None:
        print(f"[AVISO] {nombre}: {detalle}")
        self.avisos.append(nombre)


def _mqtt_echo(qa: QA) -> None:
    topico = "FEMSA/_pruebas/Process/Ping"
    payload = f"qa-{time.time_ns()}"
    recibido = threading.Event()

    def conectado(client, userdata, flags, reason_code, properties):  # noqa: ANN001
        client.subscribe(topico, qos=settings.MQTT_QOS)

    def mensaje(client, userdata, msg):  # noqa: ANN001
        if msg.topic == topico and msg.payload.decode(errors="replace") == payload:
            recibido.set()

    cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                      client_id=f"ulogix-qa-{time.time_ns()}")
    cli.on_connect = conectado
    cli.on_message = mensaje
    if settings.MQTT_USER:
        cli.username_pw_set(settings.MQTT_USER, settings.MQTT_PASSWORD)
    cli.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=15)
    cli.loop_start()
    try:
        limite = time.time() + 8
        while not cli.is_connected() and time.time() < limite:
            time.sleep(0.1)
        time.sleep(0.5)
        info = cli.publish(topico, payload, qos=settings.MQTT_QOS, retain=False)
        info.wait_for_publish(timeout=5)
        qa.check("MQTT round-trip", recibido.wait(8),
                 f"{settings.MQTT_HOST}:{settings.MQTT_PORT} {topico}")
    finally:
        cli.loop_stop()
        cli.disconnect()


def _flujo_completo(qa: QA, odoo: OdooClient, plan: list[dict]) -> None:
    sello = date.today().strftime("%Y%m%d")
    insumo = plan[0]
    compra = odoo.crear_orden_compra(
        insumo["proveedor"],
        [LineaPedido(insumo["descripcion"], insumo["componente"], 1.0,
                     max(float(insumo["precio_unitario_cop"]), 1.0), insumo["uom"])],
        referencia=f"QA-FULL/COMPRA/{sello}", confirmar=True, recibir=True,
        facturar=True)
    qa.check("Compra + recepcion + factura proveedor",
             compra.get("recibida") and compra.get("facturada"),
             json.dumps(compra, ensure_ascii=False, default=str))

    mo = odoo.crear_orden_fabricacion(
        "P1-CC350-RGB", 1.0, referencia=f"QA-FULL/MO/{sello}/P1-CC350-RGB",
        confirmar=True, reservar=True)
    fin_mo = odoo.completar_orden_fabricacion(mo["id"], mo["name"])
    qa.check("Manufactura + consumo BOM + entrada terminado", fin_mo.get("ok", False),
             json.dumps({**mo, **fin_mo}, ensure_ascii=False, default=str))

    clientes = [c for c in odoo.listar_clientes()
                if float(c.get("x_ulogix_participacion") or 0) > 0]
    venta = odoo.crear_orden_venta(
        clientes[0]["name"],
        [LineaPedido("Coca-Cola 350 ml vidrio retornable", "P1-CC350-RGB",
                     1.0, 1800.0)],
        referencia=f"QA-FULL/VENTA/{sello}", confirmar=True, entregar=True,
        facturar=True)
    qa.check("Venta + entrega + factura cliente",
             venta.get("entregada") and venta.get("facturada"),
             json.dumps(venta, ensure_ascii=False, default=str))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--flujo-completo", action="store_true")
    args = parser.parse_args()
    qa = QA()
    sheets = Contabilidad()
    odoo = OdooClient()

    conexion = odoo.probar_conexion()
    qa.check("Conexion Odoo", conexion.get("ok", False), conexion.get("detalle", ""))
    modulos = odoo._kw("ir.module.module", "search_read", [[[
        "name", "in", ["purchase", "stock", "mrp", "sale_management", "account",
                       "hr", "hr_payroll"]]]], {"fields": ["name", "state"]})
    estados = {m["name"]: m["state"] for m in modulos}
    qa.check("Modulos ERP instalados", len(estados) == 7 and
             all(v == "installed" for v in estados.values()), str(estados))

    maestro = sheets.leer_maestro_productos()
    clientes_s = sheets.leer_clientes()
    forecast = sheets.leer_dataset_pronostico("Forecast_Pronostico_Mensual")
    qa.check("Sheets maestros/demanda", len(maestro) == 3 and len(clientes_s) == 4
             and len(forecast) == 12, "3 productos, 4 clientes, 12 meses")

    codigos = set(maestro["sku"])
    pids = odoo._kw("product.product", "search", [[["default_code", "in", list(codigos)]]])
    qa.check("Productos terminados Odoo", len(pids) == 3, f"productos={len(pids)}")
    tmpl = odoo._kw("product.product", "read", [pids, ["product_tmpl_id"]])
    tids = [p["product_tmpl_id"][0] for p in tmpl]
    boms = odoo._kw("mrp.bom", "search_count", [[["product_tmpl_id", "in", tids]]])
    qa.check("BOM de manufactura", boms == 3, f"BOM={boms}")
    proveedores = odoo._kw("product.supplierinfo", "search_count", [[]])
    qa.check("Proveedores y tarifas de compra", proveedores > 0,
             f"tarifas={proveedores}")
    stock = odoo.listar_stock()
    qa.check("Inventario Odoo", len(stock) > 0, f"saldos={len(stock)}")

    plan = odoo.plan_compras_desde_demanda(forecast, cobertura_meses=1)
    qa.check("MRP demanda -> compras Odoo", len(plan) > 0,
             f"lineas_plan={len(plan)}")
    clientes_o = [c for c in odoo.listar_clientes()
                  if float(c.get("x_ulogix_participacion") or 0) > 0]
    participacion = sum(float(c["x_ulogix_participacion"]) for c in clientes_o)
    qa.check("Clientes y reparto de ventas", len(clientes_o) == 4 and
             abs(participacion - 1) < 1e-6,
             f"clientes={len(clientes_o)}, participacion={participacion:.4f}")

    roster, origen = leer_empleados(permitir_fallback=False)
    empleados = odoo.listar_empleados_ulogix()
    costo_o = sum(float(e.get("x_ulogix_costo_empleador") or 0) for e in empleados
                  if e.get("active"))
    costo_s = float(roster.loc[roster["estado"] == "activo",
                               "salario_mensual_cop"].sum())
    qa.check("RRHH Sheets -> Odoo", len(empleados) == len(roster) and
             abs(costo_o - costo_s) <= 1,
             f"origen={origen}, Sheets={len(roster)}, Odoo={len(empleados)}, "
             f"costo_delta={costo_o-costo_s:.0f}")
    nomina = odoo.estado_nomina()
    if nomina["estructuras"] == 0:
        qa.aviso("Recibos de nomina",
                 "maestro laboral listo; falta estructura salarial colombiana validada")
    else:
        qa.check("Estructuras de nomina", nomina["estructuras"] > 0, str(nomina))

    _mqtt_echo(qa)
    if args.flujo_completo:
        _flujo_completo(qa, odoo, plan)

    qa.check("Consultas comerciales/contables",
             isinstance(odoo.listar_ordenes(), list)
             and isinstance(odoo.listar_ordenes_fabricacion(), list)
             and isinstance(odoo.listar_ordenes_venta(), list)
             and isinstance(odoo.listar_facturas("in_invoice"), list)
             and isinstance(odoo.listar_facturas("out_invoice"), list),
             "PO/MO/SO/facturas legibles")
    print(f"\nRESULTADO: {len(qa.fallos)} fallos, {len(qa.avisos)} avisos")
    if qa.fallos:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
