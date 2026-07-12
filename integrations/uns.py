"""
UNS (Unified Namespace) FEMSA — interprete del YAML config/uns_femsa.yaml.

Reglas (mismas del YAML):
- `_templates` se ignora (solo define anchors reutilizables).
- Clave SIN valor (None)  -> HOJA  -> topico publicable.
- Clave con hijos (dict)  -> RAMA  -> subcarpeta del topico.
- `Process: {}` es una rama sin hojas definidas: contrato LEGADO de conteo
  de produccion (`GoodCount|Count|Produccion|Production`) -- ya no es el
  camino principal, ver mas abajo.

Topicos resultantes (ejemplos):
  FEMSA/Linea1/MES/KPI/OEE          FEMSA/Linea2/ERP/OrderStatus
  FEMSA/Linea3/MES/Maintance/MTTR   FEMSA/Linea1/ERP/AvailableQuantity
  FEMSA/MES/KPI/OEE                 (agregado de PLANTA COMPLETA, sin linea)

Reparto de responsabilidades en la rama ERP (decision #14 de CLAUDE.md,
conexion directa al broker -- no requiere Node-RED de por medio):
- El **ERP** (esta suite) PUBLICA (retained) que hay que producir: una sola
  orden de fabricacion ACTIVA por linea a la vez (`OrderNumber` = nombre de
  la MO, `OrderedQuantity`, `ScheduleStart/End`, `OrderStatus`,
  `ReservedQuantity`). Solo cuando esa orden se completa (el MES reporta
  `AvailableQuantity >= OrderedQuantity`) el ERP publica la SIGUIENTE de la
  cola de ese SKU -- nunca dos ordenes activas a la vez en la misma linea.
- El **MES** (planta real o su simulacion en el broker) ESCRIBE
  `AvailableQuantity`: cuanto lleva producido de la orden activa. El ERP se
  SUSCRIBE a esa hoja como dato de ENTRADA (no la publica el mismo) y la usa
  para marcar la orden 'cumplida' -> validar la orden de fabricacion en Odoo
  (descuenta la BOM: tapas, etiquetas, concentrado...) -> avanzar a la
  siguiente. El contrato legado `Process/GoodCount` (delta, no valor
  absoluto) sigue funcionando para pruebas locales
  (`tools/simulador_produccion.py`) pero ya no es necesario en produccion.

`FEMSA/MES/...` (sin segmento de linea) es un agregado de PLANTA COMPLETA
que el broker real (Coreflux) tambien publica -- verificado conectandose
directo al broker y suscribiendo a `#`. `interpretar_topico()` lo reconoce
como `linea='PLANTA'` (sentinela, no esta en `LINEA_DE_UNS`) para que quede
en la misma tabla `kpi_uns` y los mismos tableros que las lineas reales, sin
duplicar codigo.

**Ojo con el ruido del broker real**: Coreflux Hub tiene un agente de IA
("BrokerAgent") que puede sobreescribir cualquier hoja del UNS a pedido
(verificado: `Agent/traces` mostro la tarea "cambia el performance de la
linea uno en el KPI a 32.08"). Los valores de `AvailableQuantity`/
`OrderNumber`/etc. vistos alli NO tenian continuidad logica (saltaban al
azar, subian y bajaban) -- por eso `actualizar_disponible()` en
state_store.py exige que el avance sea MONOTONO (nunca decrece) y lo
recorta al objetivo antes de aceptarlo como produccion real.
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
    """Lo que consume el middleware: MES + Process de cada linea, el
    agregado MES de planta completa ('FEMSA/MES/...', sin comodin de linea
    porque esa posicion es literalmente 'MES'), y `ERP/AvailableQuantity`
    -- la UNICA hoja de la rama ERP que escribe el MES (avance real de
    produccion de la orden activa de esa linea; el resto de la rama ERP la
    publica este ERP, no se suscribe a su propio output -- ver decision #14
    de CLAUDE.md)."""
    r = raiz()
    return [f"{r}/+/MES/KPI/#", f"{r}/+/MES/Maintance/#", f"{r}/+/Process/#",
            f"{r}/MES/KPI/#", f"{r}/MES/Maintance/#",
            f"{r}/+/ERP/AvailableQuantity"]


def interpretar_topico(topic: str) -> dict | None:
    """FEMSA/Linea1/MES/KPI/OEE -> {'linea':'L1','rama':'MES/KPI','hoja':'OEE'}
    FEMSA/MES/KPI/OEE          -> {'linea':'PLANTA','rama':'MES/KPI','hoja':'OEE'}
    (agregado de planta completa, sin segmento de linea -- ver docstring del modulo)"""
    partes = topic.split("/")
    if len(partes) < 4 or partes[0] != raiz():
        return None
    if partes[1] in LINEA_DE_UNS:
        linea, linea_uns, resto = LINEA_DE_UNS[partes[1]], partes[1], partes[2:]
    elif partes[1] == "MES":
        linea, linea_uns, resto = "PLANTA", raiz(), partes[1:]
    else:
        return None
    if len(resto) < 2:
        return None
    return {"linea": linea, "linea_uns": linea_uns,
            "rama": "/".join(resto[:-1]), "hoja": resto[-1], "topic": topic}


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
# 'AvailableQuantity' se excluye A PROPOSITO: es dato de ENTRADA del ERP (lo
# escribe el MES -- avance real de produccion), no de salida. Publicarlo
# nosotros pisaria lo que reporta el MES y crearia un eco/carrera con
# nuestra propia suscripcion a esa misma hoja. Ver decision #14 de CLAUDE.md.
CAMPOS_ERP = ["OrderNumber", "OrderStatus", "ScheduleStart", "ScheduleEnd",
              "ActualStart", "ActualEnd", "ReservedQuantity", "OrderedQuantity"]


def erp_desde_po(po: dict, primer_evento_ts: str = "") -> dict:
    """Mapea la orden ACTIVA (state_store.orden_activa) a la rama ERP del
    UNS que el ERP publica: QUE hay que producir (numero de orden de
    fabricacion, cantidad pedida, ventana programada, estado), no CUANTO se
    ha producido -- eso lo reporta el MES en `AvailableQuantity`, que este
    ERP solo lee (ver `manejar_mensaje()` en mqtt_middleware.py)."""
    restante = max(0.0, po["qty_objetivo"] - po["qty_producida"])
    estado = {"abierta": "IN_PROGRESS", "cumplida": "COMPLETED",
              "recibida_odoo": "CLOSED", "error": "ERROR"}.get(po["estado"], "DRAFT")
    return {"OrderNumber": po.get("mo_name") or po["po_name"], "OrderStatus": estado,
            "ScheduleStart": po.get("creado_ts", ""),
            "ScheduleEnd": po.get("detalle", "") or "",
            "ActualStart": primer_evento_ts,
            "ActualEnd": po["actualizado_ts"] if po["estado"] in
            ("cumplida", "recibida_odoo") else "",
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
