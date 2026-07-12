"""
Almacen de estado compartido (SQLite) entre el middleware MQTT, el cliente de
Odoo y el dashboard Streamlit. SQLite en modo WAL soporta el patron de un
escritor (middleware) + varios lectores (paginas del dashboard).

Tablas:
- eventos_produccion : cada mensaje MQTT de produccion recibido.
- po_tracking        : ordenes de compra vinculadas a un SKU/linea con cantidad
                       objetivo; el middleware acumula produccion y marca
                       'cumplida' / 'recibida_odoo'.
- log_acciones       : auditoria (creaciones en Odoo, dry-runs, errores).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS eventos_produccion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    linea TEXT, sku TEXT, qty REAL NOT NULL,
    topic TEXT, payload TEXT
);
CREATE TABLE IF NOT EXISTS po_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_name TEXT UNIQUE NOT NULL,
    odoo_id INTEGER,
    sku TEXT NOT NULL, linea TEXT,
    componente TEXT, proveedor TEXT,
    qty_objetivo REAL NOT NULL,
    qty_producida REAL NOT NULL DEFAULT 0,
    estado TEXT NOT NULL DEFAULT 'abierta',  -- abierta|cumplida|recibida_odoo|error
    creado_ts TEXT NOT NULL, actualizado_ts TEXT NOT NULL,
    detalle TEXT
);
CREATE TABLE IF NOT EXISTS log_acciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, origen TEXT NOT NULL,
    accion TEXT NOT NULL, detalle TEXT
);
CREATE TABLE IF NOT EXISTS pronosticos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    corrida_ts TEXT NOT NULL, escenario TEXT NOT NULL,
    sku TEXT NOT NULL, ano INTEGER, mes TEXT, etiqueta TEXT,
    litros REAL, unidades REAL, p05 REAL, p95 REAL
);
CREATE TABLE IF NOT EXISTS plan_compras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    corrida_ts TEXT NOT NULL, escenario TEXT NOT NULL,
    etiqueta_mes TEXT, producto TEXT, componente TEXT, descripcion TEXT,
    uom TEXT, cantidad REAL, proveedor TEXT, precio_unitario_cop REAL,
    subtotal_cop REAL, fecha_pedido TEXT, fecha_necesidad TEXT
);
CREATE TABLE IF NOT EXISTS inventario_politicas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, escenario TEXT, sku TEXT NOT NULL,
    punto_reorden_s REAL, stock_seguridad REAL, lote_Q REAL,
    pallets_por_lote INTEGER, fill_rate REAL, nivel_servicio REAL,
    capital_inmovilizado_cop REAL, replicas INTEGER
);
CREATE TABLE IF NOT EXISTS kpi_uns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, linea TEXT NOT NULL, rama TEXT NOT NULL,
    kpi TEXT NOT NULL, valor_num REAL, valor_txt TEXT, topic TEXT
);
"""


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def conexion():
    settings.STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(settings.STATE_DB, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.executescript(_SCHEMA)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def log(origen: str, accion: str, detalle: str = "") -> None:
    with conexion() as con:
        con.execute("INSERT INTO log_acciones (ts, origen, accion, detalle) VALUES (?,?,?,?)",
                    (_ahora(), origen, accion, detalle))


def registrar_evento(linea: str, sku: str, qty: float,
                     topic: str = "", payload: dict | None = None) -> None:
    with conexion() as con:
        con.execute(
            "INSERT INTO eventos_produccion (ts, linea, sku, qty, topic, payload) "
            "VALUES (?,?,?,?,?,?)",
            (_ahora(), linea, sku, qty, topic, json.dumps(payload or {}, ensure_ascii=False)))


def registrar_po(po_name: str, sku: str, qty_objetivo: float, linea: str = "",
                 odoo_id: int | None = None, componente: str = "",
                 proveedor: str = "", detalle: str = "") -> None:
    with conexion() as con:
        con.execute(
            "INSERT INTO po_tracking (po_name, odoo_id, sku, linea, componente, proveedor,"
            " qty_objetivo, creado_ts, actualizado_ts, detalle) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(po_name) DO UPDATE SET qty_objetivo=excluded.qty_objetivo,"
            " odoo_id=excluded.odoo_id, actualizado_ts=excluded.actualizado_ts",
            (po_name, odoo_id, sku, linea, componente, proveedor,
             qty_objetivo, _ahora(), _ahora(), detalle))


def acumular_produccion(sku: str, qty: float, linea: str = "") -> list[dict]:
    """
    Reparte `qty` producida entre las PO abiertas del SKU (FIFO por creacion).
    Devuelve la lista de POs que quedaron 'cumplida' en esta llamada.
    """
    completadas: list[dict] = []
    with conexion() as con:
        pos = con.execute(
            "SELECT * FROM po_tracking WHERE sku=? AND estado='abierta' "
            "ORDER BY creado_ts, id", (sku,)).fetchall()
        restante = qty
        for po in pos:
            if restante <= 0:
                break
            falta = po["qty_objetivo"] - po["qty_producida"]
            aplicar = min(restante, falta)
            nueva = po["qty_producida"] + aplicar
            estado = "cumplida" if nueva >= po["qty_objetivo"] - 1e-9 else "abierta"
            con.execute("UPDATE po_tracking SET qty_producida=?, estado=?, actualizado_ts=? "
                        "WHERE id=?", (nueva, estado, _ahora(), po["id"]))
            restante -= aplicar
            if estado == "cumplida":
                completadas.append(dict(po) | {"qty_producida": nueva, "estado": estado})
    return completadas


def marcar_po(po_name: str, estado: str, detalle: str = "") -> None:
    with conexion() as con:
        con.execute("UPDATE po_tracking SET estado=?, detalle=?, actualizado_ts=? "
                    "WHERE po_name=?", (estado, detalle, _ahora(), po_name))


def listar_pos(limit: int = 200) -> list[dict]:
    with conexion() as con:
        rows = con.execute("SELECT * FROM po_tracking ORDER BY id DESC LIMIT ?",
                           (limit,)).fetchall()
    return [dict(r) for r in rows]


def ultimos_eventos(limit: int = 100) -> list[dict]:
    with conexion() as con:
        rows = con.execute("SELECT * FROM eventos_produccion ORDER BY id DESC LIMIT ?",
                           (limit,)).fetchall()
    return [dict(r) for r in rows]


def produccion_acumulada() -> list[dict]:
    with conexion() as con:
        rows = con.execute(
            "SELECT sku, linea, SUM(qty) AS qty_total, COUNT(*) AS eventos, MAX(ts) AS ultimo "
            "FROM eventos_produccion GROUP BY sku, linea ORDER BY sku").fetchall()
    return [dict(r) for r in rows]


def ultimo_log(limit: int = 100) -> list[dict]:
    with conexion() as con:
        rows = con.execute("SELECT * FROM log_acciones ORDER BY id DESC LIMIT ?",
                           (limit,)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- capa ERP v4
def guardar_pronostico(mensual, escenario: str = "Base") -> str:
    """Persiste una corrida de pronostico (una fila por SKU-mes)."""
    ts = _ahora()
    skus = sorted({c.rsplit("_", 1)[0] for c in mensual.columns
                   if c.endswith("_unidades")})
    with conexion() as con:
        for _, r in mensual.iterrows():
            for sku in skus:
                con.execute(
                    "INSERT INTO pronosticos (corrida_ts, escenario, sku, ano,"
                    " mes, etiqueta, litros, unidades, p05, p95)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (ts, escenario, sku, int(r["ano"]), r["mes"], r["etiqueta"],
                     float(r.get(f"{sku}_litros", 0)), float(r[f"{sku}_unidades"]),
                     float(r.get(f"{sku}_p05", 0)), float(r.get(f"{sku}_p95", 0))))
    log("erp", "guardar_pronostico", f"{escenario} @ {ts}")
    return ts


def guardar_plan_compras(plan, escenario: str = "Base") -> str:
    ts = _ahora()
    with conexion() as con:
        for _, r in plan.iterrows():
            con.execute(
                "INSERT INTO plan_compras (corrida_ts, escenario, etiqueta_mes,"
                " producto, componente, descripcion, uom, cantidad, proveedor,"
                " precio_unitario_cop, subtotal_cop, fecha_pedido, fecha_necesidad)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, escenario, r["etiqueta_mes"], r["producto"], r["componente"],
                 r["descripcion"], r["uom"], float(r["cantidad"]), r["proveedor"],
                 float(r["precio_unitario_cop"]), float(r["subtotal_cop"]),
                 r["fecha_pedido"], r["fecha_necesidad"]))
    log("erp", "guardar_plan_compras", f"{escenario}: {len(plan)} lineas @ {ts}")
    return ts


def guardar_politica_inventario(res: dict, escenario: str = "Base") -> None:
    with conexion() as con:
        con.execute(
            "INSERT INTO inventario_politicas (ts, escenario, sku, punto_reorden_s,"
            " stock_seguridad, lote_Q, pallets_por_lote, fill_rate, nivel_servicio,"
            " capital_inmovilizado_cop, replicas) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (_ahora(), escenario, res["sku"], res["punto_reorden_s"],
             res["stock_seguridad"], res["lote_Q"], res["pallets_por_lote"],
             res["fill_rate_prom"], res["nivel_servicio_objetivo"],
             res["capital_inmovilizado_cop"], res["replicas"]))
    log("erp", "guardar_politica_inventario", res["sku"])


def politicas_inventario_actuales() -> list[dict]:
    """Ultima politica (s,Q) guardada por SKU (para la hoja Inventarios)."""
    with conexion() as con:
        filas = con.execute(
            "SELECT ts, escenario, sku, punto_reorden_s, stock_seguridad, lote_Q,"
            " pallets_por_lote, fill_rate, capital_inmovilizado_cop"
            " FROM inventario_politicas WHERE id IN"
            " (SELECT MAX(id) FROM inventario_politicas GROUP BY sku)"
            " ORDER BY sku").fetchall()
    return [dict(f) for f in filas]


def registrar_kpi(linea: str, rama: str, kpi: str, valor, topic: str = "") -> None:
    try:
        num, txt = float(valor), None
    except (TypeError, ValueError):
        num, txt = None, str(valor)
    with conexion() as con:
        con.execute("INSERT INTO kpi_uns (ts, linea, rama, kpi, valor_num,"
                    " valor_txt, topic) VALUES (?,?,?,?,?,?,?)",
                    (_ahora(), linea, rama, kpi, num, txt, topic))


def ultimos_kpis(limit: int = 200) -> list[dict]:
    with conexion() as con:
        rows = con.execute("SELECT * FROM kpi_uns ORDER BY id DESC LIMIT ?",
                           (limit,)).fetchall()
    return [dict(r) for r in rows]


def kpis_actuales() -> list[dict]:
    """Ultimo valor de cada KPI numerico por linea (vista tipo tablero)."""
    with conexion() as con:
        rows = con.execute(
            "SELECT linea, kpi, valor_num, MAX(ts) AS ts FROM kpi_uns "
            "WHERE valor_num IS NOT NULL GROUP BY linea, kpi ORDER BY linea").fetchall()
    return [dict(r) for r in rows]


TABLAS_ERP = ["pronosticos", "plan_compras", "inventario_politicas",
              "po_tracking", "eventos_produccion", "kpi_uns", "log_acciones"]


def leer_tabla(nombre: str, limit: int = 500) -> list[dict]:
    if nombre not in TABLAS_ERP:
        raise ValueError(f"tabla desconocida: {nombre}")
    with conexion() as con:
        rows = con.execute(f"SELECT * FROM {nombre} ORDER BY id DESC LIMIT ?",
                           (limit,)).fetchall()
    return [dict(r) for r in rows]


def resumen_tablas() -> dict[str, int]:
    with conexion() as con:
        return {t: con.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
                for t in TABLAS_ERP}
