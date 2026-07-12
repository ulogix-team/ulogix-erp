"""
Simulador de planta v4 — publica al UNS FEMSA como lo haria Node-RED desde
Ignition: KPIs MES, mantenimiento y conteos de produccion (Process/GoodCount).

Uso:
    python tools/simulador_produccion.py                 # 12 ciclos al broker
    python tools/simulador_produccion.py --n 50 --intervalo 0.5
    python tools/simulador_produccion.py --legacy        # contrato v1 plant/...
    python tools/simulador_produccion.py --offline       # sin broker
"""
import argparse
import json
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings          # noqa: E402
from integrations import uns         # noqa: E402

LINEAS = {  # linea: (sku, produccion tipica por reporte, oee_base)
    "L1": ("P1-CC350-RGB", 9000, 0.771),
    "L2": ("P2-QT1500-PET", 2800, 0.765),
    "L3": ("P3-GARR25L", 110, 0.754),
}


def mensajes_uns(linea: str) -> list[tuple[str, str]]:
    sku, base, oee_b = LINEAS[linea]
    luns = uns.UNS_DE_LINEA[linea]
    r = uns.raiz()
    oee = min(0.95, max(0.55, random.gauss(oee_b, 0.02)))
    a = min(0.99, oee / (0.93 * 0.985) + random.gauss(0, 0.005))
    q = random.gauss(0.985, 0.003)
    p = oee / (a * q)
    qty = max(1, int(random.gauss(base, base * 0.12)))
    ahora = datetime.now(timezone.utc)
    msgs = [
        (f"{r}/{luns}/MES/KPI/Availability", f"{a:.4f}"),
        (f"{r}/{luns}/MES/KPI/Performance", f"{p:.4f}"),
        (f"{r}/{luns}/MES/KPI/Quality", f"{q:.4f}"),
        (f"{r}/{luns}/MES/KPI/OEE", f"{oee:.4f}"),
        (f"{r}/{luns}/MES/KPI/TEEP", f"{oee * 0.52:.4f}"),
        (f"{r}/{luns}/MES/KPI/DT", f"{random.gauss(14, 4):.1f}"),
        (f"{r}/{luns}/MES/KPI/MTTR", f"{random.gauss(22, 5):.1f}"),
        (f"{r}/{luns}/MES/KPI/MTBF", f"{random.gauss(340, 40):.0f}"),
        (f"{r}/{luns}/Process/GoodCount",
         json.dumps({"value": qty, "sku": sku, "requestedBy": "simulador",
                     "timestamp": ahora.isoformat(timespec="seconds")})),
    ]
    if random.random() < 0.25:
        msgs += [
            (f"{r}/{luns}/MES/Maintance/MachineID", f"{linea}-LLENADORA"),
            (f"{r}/{luns}/MES/Maintance/LastMaintance",
             (ahora - timedelta(days=random.randint(3, 30))).date().isoformat()),
            (f"{r}/{luns}/MES/Maintance/NextMaintance",
             (ahora + timedelta(days=random.randint(5, 45))).date().isoformat()),
            (f"{r}/{luns}/MES/Maintance/MaintanceStatus",
             random.choice(["OK", "OK", "OK", "PROGRAMADO", "ALERTA"])),
        ]
    return msgs


def mensaje_legacy(linea: str) -> list[tuple[str, str]]:
    sku, base, _ = LINEAS[linea]
    qty = max(1, int(random.gauss(base, base * 0.12)))
    payload = {"sku": sku, "line": linea, "qty": qty,
               "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return [(f"{settings.MQTT_TOPIC_BASE}/{linea}/production", json.dumps(payload))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--intervalo", type=float, default=1.0)
    ap.add_argument("--legacy", action="store_true")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    gen = mensaje_legacy if args.legacy else mensajes_uns

    if args.offline:
        from integrations.mqtt_middleware import Middleware
        mw = Middleware()
        for i in range(args.n):
            for topic, payload in gen(random.choice(list(LINEAS))):
                done = mw.manejar_mensaje(topic, payload)
                print(f"[{i+1:>3}] {topic} = {payload[:70]}"
                      + (f" -> POs: {[p['po_name'] for p in done]}" if done else ""))
        return

    import paho.mqtt.client as mqtt
    cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ulogix-simulador")
    if settings.MQTT_USER:
        cl.username_pw_set(settings.MQTT_USER, settings.MQTT_PASSWORD)
    cl.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=30)
    cl.loop_start()
    for i in range(args.n):
        for topic, payload in gen(random.choice(list(LINEAS))):
            cl.publish(topic, payload, qos=settings.MQTT_QOS)
            print(f"[{i+1:>3}] -> {topic}: {payload[:90]}")
        time.sleep(args.intervalo)
    cl.loop_stop(); cl.disconnect()


if __name__ == "__main__":
    main()
