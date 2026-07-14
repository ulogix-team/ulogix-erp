"""
Configuracion central de la suite. Todo se lee de variables de entorno / .env
(ver .env.example). Ningun secreto vive en el codigo.

Modo simulacion: si una integracion no tiene credenciales, la suite NO falla;
opera en modo DRY-RUN (registra las acciones en SQLite / Excel local) para que
todo el flujo sea demostrable end-to-end sin servicios externos.
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)

def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()

def _get_bool(name: str, default: bool = False) -> bool:
    v = _get(name, str(default)).lower()
    return v in {"1", "true", "yes", "si", "sí", "on"}

# ------------------------------------------------------------------ rutas
DATA_DIR = ROOT / "data"
STATE_DB = Path(_get("STATE_DB", str(ROOT / "middleware" / "state.db")))
ASSETS_DIR = ROOT / "app" / "assets"

# ------------------------------------------------------------------ Odoo (API externa XML-RPC)
# https://www.odoo.com/documentation/17.0/developer/reference/external_api.html
ODOO_URL = _get("ODOO_URL")                    # ej. https://miempresa.odoo.com
ODOO_DB = _get("ODOO_DB")                      # nombre de la base de datos
ODOO_USER = _get("ODOO_USER")                  # email del usuario API
ODOO_API_KEY = _get("ODOO_API_KEY")            # API key (Ajustes > Seguridad de la cuenta)
ODOO_COMPANY_ID = int(_get("ODOO_COMPANY_ID", "1") or 1)
ODOO_ENABLED = bool(ODOO_URL and ODOO_DB and ODOO_USER and ODOO_API_KEY)

# ------------------------------------------------------------------ MQTT (broker del stack MES)
# Recordatorio de arquitectura: si este proceso corre FUERA de Docker usa la IP
# LAN del host (no `localhost` ni el hostname del servicio, p.ej. `mosquitto`).
MQTT_HOST = _get("MQTT_HOST", "localhost")
MQTT_PORT = int(_get("MQTT_PORT", "1883") or 1883)
MQTT_USER = _get("MQTT_USER")
MQTT_PASSWORD = _get("MQTT_PASSWORD")
MQTT_TOPIC_BASE = _get("MQTT_TOPIC_BASE", "plant")   # plant/L1/production, plant/L2/...
MQTT_CLIENT_ID = _get("MQTT_CLIENT_ID", "ulogix-middleware")
MQTT_QOS = int(_get("MQTT_QOS", "1") or 1)

# Referencia del stack (Node-RED/Tecnomatix se conectan a OPC UA; este
# middleware solo habla MQTT — el puente OPC-UA->MQTT ya existe en Node-RED).
OPCUA_ENDPOINT = _get("OPCUA_ENDPOINT", "opc.tcp://tu-ip-o-host:62451")

# ------------------------------------------------------------------ Google Sheets (contabilidad)
# Cuenta de servicio (JSON). Compartir el spreadsheet con el client_email del JSON.
GOOGLE_SA_JSON = _get("GOOGLE_SA_JSON", str(ROOT / "config" / "google_service_account.json"))
SHEETS_SPREADSHEET_ID = _get("SHEETS_SPREADSHEET_ID")
SHEETS_ENABLED = bool(SHEETS_SPREADSHEET_ID and Path(GOOGLE_SA_JSON).exists())
LEDGER_XLSX = DATA_DIR / "contabilidad_local.xlsx"   # respaldo local si no hay Sheets

# ------------------------------------------------------------------ Simulacion / horizonte
HORIZONTE_INICIO = _get("HORIZONTE_INICIO", "2026-04")   # Abr 2026
HORIZONTE_MESES = int(_get("HORIZONTE_MESES", "12") or 12)  # -> Mar 2027
MC_N = int(_get("MC_N", "10000") or 10000)               # replicas Monte Carlo pronostico
MC_N_INVENTARIO = int(_get("MC_N_INVENTARIO", "300") or 300)
SEMILLA = int(_get("SEMILLA", "42") or 42)

DRY_RUN_FORZADO = _get_bool("DRY_RUN", False)  # fuerza dry-run aunque haya credenciales
EXTERNAL_ONLY = _get_bool("EXTERNAL_ONLY", False)

def resumen_conexiones() -> dict:
    """Estado de integraciones para mostrar en el dashboard."""
    return {
        "odoo": {"habilitado": ODOO_ENABLED and not DRY_RUN_FORZADO,
                 "detalle": ODOO_URL or "sin configurar (dry-run)"},
        "mqtt": {"habilitado": True,
                 "detalle": f"{MQTT_HOST}:{MQTT_PORT} base='{MQTT_TOPIC_BASE}'"},
        "sheets": {"habilitado": SHEETS_ENABLED and not DRY_RUN_FORZADO,
                   "detalle": SHEETS_SPREADSHEET_ID or f"local: {LEDGER_XLSX.name}"},
    }
