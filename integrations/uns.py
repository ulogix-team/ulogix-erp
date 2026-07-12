"""
UNS (Unified Namespace) FEMSA — interprete del YAML config/uns_femsa.yaml.

Reglas (mismas del YAML):
- `_templates` se ignora (solo define anchors reutilizables).
- Clave SIN valor (None)  -> HOJA  -> topico publicable.
- Clave con hijos (dict)  -> RAMA  -> subcarpeta del topico.
- `Process: {}` es una rama sin hojas definidas: la planta puede colgar ahi
  contadores; el middleware acepta por convencion las hojas
  Process/{GoodCount|Count|Produccion|Production} como conteo de produccion.

Topicos resultantes (ejemplos):
  FEMSA/Linea1/MES/KPI/OEE          FEMSA/Linea2/ERP/OrderStatus
  FEMSA/Linea3/MES/Maintance/MTTR   FEMSA/Linea1/Process/GoodCount

La suite actua como el ERP del UNS: PUBLICA la rama ERP (retained, para que
cualquier consumidor nuevo reciba el ultimo estado) y SE SUSCRIBE a MES y
Process. Mapeo de lineas: Linea1<->L1, Linea2<->L2, Linea3<->L3.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings

_YAML = Path(__file__).resolve().parents[1] / "config" / "uns_femsa.yaml"

LINEA_DE_UNS = {"Linea1": "L1", "Linea2": "L2", "Linea3": "L3"}
UNS_DE_LINEA = {v: k for k, v in LINEA_DE_UNS.items()}
HOJAS_PRODUCCION = {"goodcount", "count", "produccion", "production", "value"}


def cargar_arbol() -> dict:
    doc = yaml.safe_load(open(_YAML, encoding="utf-8"))
    return doc["uns"]


def raiz() -> str:
    return next(iter(cargar_arbol()))          # "FEMSA"


def hojas(arbol: dict | None = None, prefijo: str = "") -> list[str]:
    """Expande el arbol a la lista completa de topicos-hoja."""
    if arbol is None:
        arbol = cargar_arbol()
        return hojas(arbol[raiz()], raiz())
    out: list[str] = []
    for clave, hijo in (arbol or {}).items():
        ruta = f"{prefijo}/{clave}"
        if isinstance(hijo, dict) and hijo:
            out += hojas(hijo, ruta)
        elif isinstance(hijo, dict):           # rama vacia (Process: {})
            continue
        else:                                  # hoja (None)
            out.append(ruta)
    return out


def suscripciones() -> list[str]:
    """Lo que consume el middleware (MES + Process de todas las lineas)."""
    r = raiz()
    return [f"{r}/+/MES/KPI/#", f"{r}/+/MES/Maintance/#", f"{r}/+/Process/#"]


def interpretar_topico(topic: str) -> dict | None:
    """FEMSA/Linea1/MES/KPI/OEE -> {'linea':'L1','rama':'MES/KPI','hoja':'OEE'}"""
    partes = topic.split("/")
    if len(partes) < 4 or partes[0] != raiz():
        return None
    linea = LINEA_DE_UNS.get(partes[1])
    if linea is None:
        return None
    return {"linea": linea, "linea_uns": partes[1],
            "rama": "/".join(partes[2:-1]), "hoja": partes[-1], "topic": topic}


def valor_payload(raw: bytes | str):
    """Valor de una hoja: numero plano, o JSON {'value': x} estilo MES Engine."""
    s = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    s = s.strip()
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            return data.get("value", data.get("qty", data.get("valor")))
        return data
    except json.JSONDecodeError:
        return s


# ------------------------------------------------------------------ ERP -> UNS
CAMPOS_ERP = ["OrderNumber", "OrderStatus", "ScheduleStart", "ScheduleEnd",
              "ActualStart", "ActualEnd", "AvailableQuantity",
              "ReservedQuantity", "OrderedQuantity"]


def erp_desde_po(po: dict, primer_evento_ts: str = "") -> dict:
    """Mapea una PO rastreada (state_store.po_tracking) a la rama ERP del UNS."""
    restante = max(0.0, po["qty_objetivo"] - po["qty_producida"])
    estado = {"abierta": "IN_PROGRESS", "cumplida": "COMPLETED",
              "recibida_odoo": "CLOSED", "error": "ERROR"}.get(po["estado"], "DRAFT")
    return {"OrderNumber": po["po_name"], "OrderStatus": estado,
            "ScheduleStart": po.get("creado_ts", ""),
            "ScheduleEnd": po.get("detalle", "") or "",
            "ActualStart": primer_evento_ts,
            "ActualEnd": po["actualizado_ts"] if po["estado"] in
            ("cumplida", "recibida_odoo") else "",
            "AvailableQuantity": round(po["qty_producida"], 2),
            "ReservedQuantity": round(restante, 2),
            "OrderedQuantity": round(po["qty_objetivo"], 2)}


def publicar_erp(cliente, linea: str, campos: dict, qos: int | None = None) -> None:
    """Publica (retained) los campos ERP de una linea en el UNS."""
    r, luns = raiz(), UNS_DE_LINEA.get(linea, linea)
    qos = settings.MQTT_QOS if qos is None else qos
    for campo in CAMPOS_ERP:
        if campo in campos:
            cliente.publish(f"{r}/{luns}/ERP/{campo}",
                            json.dumps(campos[campo]) if not isinstance(
                                campos[campo], (int, float, str))
                            else str(campos[campo]),
                            qos=qos, retain=True)


if __name__ == "__main__":
    print("Raiz:", raiz())
    print("Suscripciones middleware:", suscripciones())
    hs = hojas()
    print(f"{len(hs)} topicos-hoja. Ejemplos:")
    for h in hs[:8]:
        print("  ", h)
    print("Interpretacion:", interpretar_topico("FEMSA/Linea1/MES/KPI/OEE"))
