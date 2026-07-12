"""
Analisis de sensibilidad (tornado, one-at-a-time).

Variable de respuesta: margen bruto anual (COP) = sum(unidades x (precio -
costo_material)) sobre el horizonte, para el escenario activo. Cada parametro
se perturba individualmente entre su cota baja y alta manteniendo el resto en
el valor base — el ranking del tornado identifica donde vale la pena invertir
en mejor informacion (p. ej., resolver la inconsistencia TEEP/utilizacion con
horas programadas reales antes que refinar el precio del film stretch).
"""
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.forecast import cargar_maestro, cargar_parametros

PARAMETROS = [
    # (nombre, low, high, tipo)
    ("Demanda sostenida (factor)", 0.95, 1.05, "demanda_todos"),
    ("Participacion planta Bogota", 0.90, 1.10, "demanda_todos"),
    ("Participacion SKU en categoria", 0.90, 1.10, "demanda_todos"),
    ("Precio de venta", 0.95, 1.05, "precio"),
    ("Costo de materiales", 0.90, 1.10, "costo"),
    ("OEE (+/-5 pts sobre ~77%)", 0.935, 1.065, "capacidad"),
]


def _margen(dem_mensual: pd.DataFrame, maestro: pd.DataFrame,
            f_dem: float = 1.0, f_precio: float = 1.0, f_costo: float = 1.0,
            f_cap: float = 1.0) -> float:
    params = cargar_parametros()
    total = 0.0
    for _, p in maestro.iterrows():
        unidades = dem_mensual[f"{p['sku']}_unidades"].sum() * f_dem
        # tope de capacidad anual de la linea (OEE perturbado)
        linea = params["lineas"][p["linea"]]
        cap = (linea["vel_nominal_uph"] * linea["horas_turno"] * linea["turnos"]
               * params["calendario"]["dias_operativos_ano"] * linea["oee"] * f_cap)
        unidades = min(unidades, cap)
        total += unidades * (p["precio_venta_cop"] * f_precio
                             - p["costo_material_cop"] * f_costo)
    return total


def tornado(dem_mensual: pd.DataFrame) -> pd.DataFrame:
    maestro = cargar_maestro()
    base = _margen(dem_mensual, maestro)
    filas = []
    for nombre, lo, hi, tipo in PARAMETROS:
        kw_lo, kw_hi = {}, {}
        key = {"demanda_todos": "f_dem", "precio": "f_precio",
               "costo": "f_costo", "capacidad": "f_cap"}[tipo]
        kw_lo[key], kw_hi[key] = lo, hi
        m_lo = _margen(dem_mensual, maestro, **kw_lo)
        m_hi = _margen(dem_mensual, maestro, **kw_hi)
        filas.append({
            "parametro": nombre,
            "margen_low_cop": round(m_lo),
            "margen_high_cop": round(m_hi),
            "delta_low_pct": round(100 * (m_lo / base - 1), 2),
            "delta_high_pct": round(100 * (m_hi / base - 1), 2),
            "amplitud_pct": round(100 * abs(m_hi - m_lo) / base, 2),
        })
    df = pd.DataFrame(filas).sort_values("amplitud_pct", ascending=False)
    df.attrs["margen_base_cop"] = round(base)
    return df


if __name__ == "__main__":
    from core.forecast import pronostico_base
    r = pronostico_base(mc_n=500)
    t = tornado(r.mensual)
    print("Margen base: $", f"{t.attrs['margen_base_cop']:,.0f} COP")
    print(t.to_string(index=False))
