"""Punto de entrada del middleware MQTT <-> Odoo (proceso independiente).

Uso:
    python middleware/run_middleware.py
Docker:
    servicio `middleware` en docker-compose.dashboard.yml
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.mqtt_middleware import Middleware  # noqa: E402

if __name__ == "__main__":
    print("[middleware] Ulogix — middleware de produccion (MQTT -> POs Odoo)")
    Middleware().correr()
