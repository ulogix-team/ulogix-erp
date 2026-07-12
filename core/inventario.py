"""
Simulacion de inventario y explosion MRP.

INVENTARIO (producto terminado, por SKU):
- Demanda diaria ~ Normal(mu_dia, sigma_dia) derivada del pronostico mensual
  del escenario activo (sigma del backtest, distribucion Normal aceptada por
  KS/AD/chi-cuadrado en el estudio original).
- Politica (s, Q): punto de reorden s = mu_LT + z * sigma_LT; Q por EOQ
  redondeado a pallets completos (lote = produccion de un turno, redondeado a
  pallets, criterio del estudio de tiempos).
- Monte Carlo de trayectorias diarias -> fill rate, dias de quiebre,
  inventario promedio y capital inmovilizado.

MRP (componentes, por proveedor):
- Explosion de la demanda mensual del escenario activo via data/bom.csv
  (+ scrap parametrizable), neteo de inventario inicial, redondeo a MOQ y
  fecha de pedido = fecha de necesidad - lead time del proveedor.
- El plan resultante es exactamente lo que la pagina de Odoo convierte en
  ordenes de compra (purchase.order) via API.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import math

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings
from core.forecast import cargar_maestro, cargar_parametros, MESES

_DIAS_MES = 286 / 12  # dias operativos promedio (calendario Ley Emiliani)
_Z = {0.90: 1.2816, 0.95: 1.6449, 0.975: 1.9600, 0.98: 2.0537, 0.99: 2.3263}


def _z_de_nivel(nivel: float) -> float:
    from statistics import NormalDist
    return _Z.get(round(nivel, 3), NormalDist().inv_cdf(nivel))


# ------------------------------------------------------------------ inventario PT
@dataclass
class ParametrosInventario:
    sku: str
    lead_time_dias: float = 3.0          # reposicion interna (produccion)
    nivel_servicio: float = 0.95
    costo_pedido_cop: float = 350_000    # setup/cambio de formato
    tasa_mantener_anual: float = 0.22    # % del costo unitario / ano
    inventario_inicial: float | None = None


def simular_inventario(demanda_mensual: pd.DataFrame, p: ParametrosInventario,
                       sigma_rel: float = 0.05, n_rep: int | None = None,
                       semilla: int | None = None) -> dict:
    """Simula 1 ano operativo (dias operativos) con politica (s, Q)."""
    n_rep = n_rep or settings.MC_N_INVENTARIO
    rng = np.random.default_rng(settings.SEMILLA if semilla is None else semilla)
    maestro = cargar_maestro().set_index("sku")
    prod = maestro.loc[p.sku]

    unidades_mes = demanda_mensual[f"{p.sku}_unidades"].to_numpy(dtype=float)
    mu_dia_mes = unidades_mes / _DIAS_MES
    dias_por_mes = int(round(_DIAS_MES))
    mu_dia = np.repeat(mu_dia_mes, dias_por_mes)
    horizonte = len(mu_dia)
    sigma_dia = mu_dia * sigma_rel * math.sqrt(_DIAS_MES)  # sigma mensual -> diario

    # politica
    z = _z_de_nivel(p.nivel_servicio)
    mu_lt = float(np.mean(mu_dia)) * p.lead_time_dias
    sigma_lt = float(np.mean(sigma_dia)) * math.sqrt(p.lead_time_dias)
    ss = z * sigma_lt
    s = mu_lt + ss
    D_anual = float(unidades_mes.sum())
    H = prod["costo_material_cop"] * p.tasa_mantener_anual
    eoq = math.sqrt(2 * D_anual * p.costo_pedido_cop / max(H, 1e-9))
    upp = prod["unidades_por_caja"] * prod["cajas_por_pallet"]  # unidades por pallet
    Q = max(upp, round(eoq / upp) * upp)                        # pallets completos

    inv0 = p.inventario_inicial if p.inventario_inicial is not None else s + Q / 2

    quiebres = np.zeros(n_rep)
    fill = np.zeros(n_rep)
    inv_prom = np.zeros(n_rep)
    trayectoria_ej = None
    for k in range(n_rep):
        inv = inv0
        pipeline: list[tuple[int, float]] = []   # (dia_llegada, qty)
        servida = demandada = 0.0
        inv_acum = 0.0
        dias_quiebre = 0
        tray = np.zeros(horizonte)
        for d in range(horizonte):
            llegadas = [q for (dd, q) in pipeline if dd == d]
            inv += sum(llegadas)
            pipeline = [(dd, q) for (dd, q) in pipeline if dd != d]
            dem = max(0.0, rng.normal(mu_dia[d], max(sigma_dia[d], 1e-9)))
            vendido = min(inv, dem)
            servida += vendido; demandada += dem
            if dem > inv:
                dias_quiebre += 1
            inv -= vendido
            pos = inv + sum(q for _, q in pipeline)
            if pos <= s:
                pipeline.append((d + int(round(p.lead_time_dias)), Q))
            inv_acum += inv
            tray[d] = inv
        quiebres[k] = dias_quiebre
        fill[k] = servida / max(demandada, 1e-9)
        inv_prom[k] = inv_acum / horizonte
        if k == 0:
            trayectoria_ej = tray

    return {
        "sku": p.sku,
        "punto_reorden_s": round(s),
        "stock_seguridad": round(ss),
        "lote_Q": int(Q),
        "pallets_por_lote": int(Q / upp),
        "eoq_teorico": round(eoq),
        "fill_rate_prom": float(np.mean(fill)),
        "fill_rate_p05": float(np.percentile(fill, 5)),
        "dias_quiebre_prom": float(np.mean(quiebres)),
        "inventario_prom_unidades": round(float(np.mean(inv_prom))),
        "capital_inmovilizado_cop": round(float(np.mean(inv_prom)) * prod["costo_material_cop"]),
        "trayectoria_ejemplo": trayectoria_ej,
        "nivel_servicio_objetivo": p.nivel_servicio,
        "replicas": n_rep,
    }


# ------------------------------------------------------------------ MRP -> plan de compras
def cargar_bom() -> pd.DataFrame:
    return pd.read_csv(settings.DATA_DIR / "bom.csv")


def plan_compras(demanda_mensual: pd.DataFrame, scrap: float = 0.02,
                 inventario_inicial: dict[str, float] | None = None,
                 cobertura_meses: int | None = None) -> pd.DataFrame:
    """
    Explosion MRP mensual -> lineas de pedido por componente/mes/proveedor.
    Devuelve columnas listas para crear purchase.order en Odoo.
    """
    bom = cargar_bom()
    inv = dict(inventario_inicial or {})
    filas = []
    meses = demanda_mensual[["ano", "mes", "etiqueta"]].values.tolist()
    if cobertura_meses:
        meses = meses[:cobertura_meses]
    for ano, mes, etiqueta in meses:
        m = demanda_mensual[(demanda_mensual["ano"] == ano) & (demanda_mensual["mes"] == mes)].iloc[0]
        # requerimiento bruto por (producto, componente) en el mes — se conserva
        # el producto para poder vincular cada PO a un SKU rastreable por MQTT
        for _, b in bom.iterrows():
            unidades = float(m[f"{b['producto']}_unidades"])
            bruto = unidades * b["cantidad_por_unidad"] * (1 + scrap)
            comp, info = b["componente"], b
            disponible = inv.get(comp, 0.0)
            usado = min(disponible, bruto)
            inv[comp] = disponible - usado
            neto = bruto - usado
            if neto <= 0:
                continue
            moq = float(info["moq"])
            qty = math.ceil(neto / moq) * moq
            mes_num = MESES.index(mes) + 1
            necesidad = pd.Timestamp(int(ano), mes_num, 1)
            pedido = necesidad - pd.Timedelta(days=int(info["lead_time_dias"]))
            filas.append({
                "etiqueta_mes": etiqueta,
                "producto": b["producto"],
                "unidades_producto_mes": round(unidades),
                "componente": comp,
                "descripcion": info["descripcion"],
                "uom": info["uom"],
                "cantidad": round(qty, 2),
                "requerimiento_neto": round(neto, 2),
                "proveedor": info["proveedor"],
                "precio_unitario_cop": float(info["precio_unitario_cop"]),
                "subtotal_cop": round(qty * float(info["precio_unitario_cop"])),
                "lead_time_dias": int(info["lead_time_dias"]),
                "fecha_pedido": pedido.date().isoformat(),
                "fecha_necesidad": necesidad.date().isoformat(),
            })
    return pd.DataFrame(filas)


if __name__ == "__main__":
    from core.forecast import pronostico_base
    r = pronostico_base(mc_n=1000)
    res = simular_inventario(r.mensual, ParametrosInventario("P1-CC350-RGB"),
                             sigma_rel=0.023, n_rep=50)
    print({k: v for k, v in res.items() if k != "trayectoria_ejemplo"})
    pc = plan_compras(r.mensual, cobertura_meses=2)
    print(pc.head(10).to_string(index=False))
    print("Total plan 2 meses: $", f"{pc['subtotal_cop'].sum():,.0f} COP")
