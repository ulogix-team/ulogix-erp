"""
Caso de negocio del retrofit v3 — DEMANDA -> ESTADOS FINANCIEROS.

Motor mensual de 60 meses construido desde el pronostico de demanda por SKU
(v4) o desde la demanda del ESCENARIO ACTIVO del ERP, con la economia unitaria
de la base financiera (Costos_Lote: 330ml $2,200/929 · PET1.5 $5,200/2,670 ·
garrafon $10,500/6,943), y la estructura completa del modelo del proyecto:

  CASO BASE (sin proyecto)      CASO PROYECTO (retrofit)
  ventas = demanda v4           ventas = demanda x (1 + uplift 11% x monet. 31% x rampa)
  - COGS unitario               - COGS unitario
  - nomina operacion 85.9M      - nomina operacion 85.9M
  - otros fijos 250M            - otros fijos 280M - OPEX licencias 14.18M
  = EBITDA base                 = EBITDA proyecto (+ ahorro scrap + mant. evitado)

  INCREMENTAL = proyecto - base -> D&A por categorias (10/7/5/3 anios) ->
  impuesto 35% -> FCF; pre-op: CAPEX en 4 fases + equipo implementacion ULogix
  (87.16M/mes x 4) + licencias; capital de trabajo 8% del ingreso incremental
  (m5 -> recupera m60). Indicadores: VPN (TMAR 18% EA), TIR, ROI, paybacks.

CAPEX_FILAS es la FUENTE UNICA (este modulo y el generador del libro Excel la
comparten): benchmark de retrofit sin la fila generica de paletizado +
BOM REAL de las celdas + software capitalizable de licencias.
"""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings

SKUS = ["P1-CC350-RGB", "P2-QT1500-PET", "P3-GARR25L"]

# ------------------------------ parametros (espejo de Parametros en Sheets)
TRM = 3850.0
FACTOR_RFQ = 0.97
TMAR_ANUAL = 0.18
TMAR_MENSUAL = (1 + TMAR_ANUAL) ** (1 / 12) - 1
MESES, PREOP = 60, 4
UPLIFT_THROUGHPUT = 0.11
FACTOR_MONETIZACION = 0.31
RAMPA_MES5 = 0.67
SCRAP_PP = 0.0004
MANT_EVITADO_MES = 85_000_000.0
TASA_RENTA = 0.35
WC_PCT_INGRESO = 0.08
CRECIMIENTO_DEMANDA_ANUAL = 0.015
FASES_CAPEX = [0.20, 0.35, 0.27, 0.18]
NOMINA_OPERACION_MES = 85_915_382.0      # Personal (base y proyecto)
NOMINA_IMPLEMENTACION_MES = 87_161_760.0  # equipo ULogix, meses pre-op
OTROS_FIJOS_BASE_MES = 250_000_000.0
OTROS_FIJOS_PROYECTO_MES = 280_000_000.0
OPEX_LICENCIAS_MES = 14_180_736.67
CAPEX_SOFTWARE = 34_650_000.0             # licencias perpetuas capitalizables
DSO, DIO, DPO = 25, 17, 30                # dias (balance)
REF_XLSM = {"vpn": 2_180_752_718.0, "tir_anual": 0.2316,
            "ebitda_y1": 8_053_914_020.0}

# ------------------------------ CAPEX (fuente unica; el Excel la importa)
# (seccion, linea, activo, cant, moneda, costo_unit, vida_anios, categoria_dep)
CAPEX_FILAS = [
    ("Benchmark retrofit", "L2 330 mL", "Upgrade lavadora retornable / prewash (KRONES Lavatec)", 1, "USD", 450_000, 10, "equipos"),
    ("Benchmark retrofit", "L2 330 mL", "Inspeccion envase vacio (HEUFT SPECTRUM II SX)", 1, "USD", 180_000, 7, "automatizacion"),
    ("Benchmark retrofit", "L2 330 mL", "Retrofit llenadora / tapadora (KRONES Modulfill HES)", 1, "USD", 650_000, 10, "equipos"),
    ("Benchmark retrofit", "L2 330 mL", "Etiquetadora y sincronizacion (servos)", 1, "USD", 120_000, 7, "automatizacion"),
    ("Benchmark retrofit", "L2 330 mL", "Conveyors, motores y VFD (ABB retrofit)", 1, "USD", 160_000, 7, "equipos"),
    ("Benchmark retrofit", "L3 PET 1.5 L", "Bloc soplado-llenado-tapado retrofit (KRONES Contiform)", 1, "USD", 850_000, 10, "equipos"),
    ("Benchmark retrofit", "L3 PET 1.5 L", "Inspeccion botella llena (HEUFT PRIME)", 1, "USD", 160_000, 7, "automatizacion"),
    ("Benchmark retrofit", "L3 PET 1.5 L", "Etiquetado / empaque PET", 1, "USD", 140_000, 7, "equipos"),
    ("Benchmark retrofit", "L3 PET 1.5 L", "Conveyors / transporte PET", 1, "USD", 210_000, 10, "equipos"),
    ("Benchmark retrofit", "L7 Agua 25 L", "Lavado y sanitizacion garrafon", 1, "USD", 230_000, 10, "equipos"),
    ("Benchmark retrofit", "L7 Agua 25 L", "Skid tratamiento de agua (KRONES Hydronomic)", 1, "USD", 320_000, 10, "equipos"),
    ("Benchmark retrofit", "L7 Agua 25 L", "Llenado / taponado / inspeccion garrafon", 1, "USD", 240_000, 10, "equipos"),
    ("Benchmark retrofit", "L7 Agua 25 L", "Conveyors y manipulacion de garrafon", 1, "USD", 110_000, 7, "equipos"),
    ("Benchmark retrofit", "Comun", "PLC panels / I/O / seguridad (CompactLogix + safety)", 3, "USD", 106_667, 7, "automatizacion"),
    ("Benchmark retrofit", "Comun", "HMIs / estaciones SCADA", 6, "USD", 10_000, 5, "automatizacion"),
    ("Benchmark retrofit", "Comun", "Camaras y vision artificial (Cognex)", 1, "USD", 95_000, 5, "automatizacion"),
    ("Benchmark retrofit", "Comun", "Sensores / transmisores / valvulas (pack)", 1, "USD", 55_000, 5, "automatizacion"),
    ("Benchmark retrofit", "Comun", "Red industrial y ciberseguridad (switches/FW/UPS)", 1, "USD", 75_000, 5, "automatizacion"),
    ("Benchmark retrofit", "Comun", "Servidor edge / historian / gateway MES-UNS (MQTT)", 1, "USD", 90_000, 5, "automatizacion"),
    ("Servicios", "Comun", "Ingenieria de detalle, FAT/SAT y PMO", 1, "COP", 1_164_000_000, 5, "servicios"),
    ("Servicios", "Comun", "Instalacion y puesta en marcha (EPC)", 1, "COP", 970_000_000, 5, "servicios"),
    ("Servicios", "Comun", "Capacitacion y gestion del cambio", 1, "COP", 242_500_000, 3, "intangibles"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Celda GANTRY de paletizado — BOM real (36 items)", 1, "USD*", 107_993, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Celda ROBOT ARTICULADO — BOM real (IRB 5710 + Omnicore)", 1, "USD*", 131_896, 10, "equipos"),
    ("Software", "Comun", "Licencias perpetuas capitalizables (Studio 5000)", 1, "COP", CAPEX_SOFTWARE, 3, "software"),
]
CONTINGENCIA = 0.10


def _cop(fila) -> float:
    _, _, _, cant, mon, unit, _, _ = fila
    if mon == "USD":
        return cant * unit * TRM * FACTOR_RFQ
    if mon == "USD*":                      # cotizacion real: sin factor RFQ
        return cant * unit * TRM
    return cant * unit


def capex() -> dict:
    total_filas = sum(_cop(f) for f in CAPEX_FILAS)
    celdas = sum(_cop(f) for f in CAPEX_FILAS if f[0].startswith("Celdas"))
    por_cat: dict[str, float] = {}
    for f in CAPEX_FILAS:
        por_cat[f[7]] = por_cat.get(f[7], 0.0) + _cop(f)
    return {"subtotal_cop": total_filas, "celdas_roboticas_cop": celdas,
            "contingencia_cop": total_filas * CONTINGENCIA,
            "total_cop": total_filas * (1 + CONTINGENCIA),
            "depreciable_por_categoria": por_cat}


VIDAS = {"equipos": 10, "automatizacion": 7, "servicios": 5,
         "intangibles": 3, "software": 3}


def dep_mensual_total() -> float:
    cx = capex()["depreciable_por_categoria"]
    return sum(base / (VIDAS[cat] * 12) for cat, base in cx.items())


def _maestro() -> pd.DataFrame:
    return pd.read_csv(settings.DATA_DIR / "maestro_productos.csv").set_index("sku")


def _demanda_base() -> pd.DataFrame:
    csv = settings.DATA_DIR / "pronostico_base_mensual.csv"
    if csv.exists():
        return pd.read_csv(csv)
    from core.forecast import pronostico_base
    return pronostico_base().mensual


def flujos_desde_demanda(demanda_mensual: pd.DataFrame | None = None) -> dict:
    dem12 = (demanda_mensual if demanda_mensual is not None
             else _demanda_base()).reset_index(drop=True)
    ma = _maestro()
    precio = {s: float(ma.loc[s, "precio_venta_cop"]) for s in SKUS}
    costo = {s: float(ma.loc[s, "costo_material_cop"]) for s in SKUS}
    cx = capex()
    dep_mes = dep_mensual_total()

    ingreso_b = np.zeros(MESES); cogs_b = np.zeros(MESES); u = np.zeros(MESES)
    for m in range(1, MESES + 1):
        fila = dem12.iloc[(m - 1) % 12]
        crec = (1 + CRECIMIENTO_DEMANDA_ANUAL) ** ((m - 1) // 12)
        for s in SKUS:
            q = float(fila[f"{s}_unidades"]) * crec
            u[m - 1] += q
            ingreso_b[m - 1] += q * precio[s]
            cogs_b[m - 1] += q * costo[s]

    rampa = np.zeros(MESES); rampa[PREOP] = RAMPA_MES5; rampa[PREOP + 1:] = 1.0
    factor_v = 1 + rampa * UPLIFT_THROUGHPUT * FACTOR_MONETIZACION
    ingreso_p, cogs_p = ingreso_b * factor_v, cogs_b * factor_v

    op = np.arange(1, MESES + 1) > PREOP
    ebitda_b = (ingreso_b - cogs_b - NOMINA_OPERACION_MES - OTROS_FIJOS_BASE_MES)
    ahorro_scrap = cogs_p * SCRAP_PP * rampa
    ebitda_p = (ingreso_p - cogs_p - NOMINA_OPERACION_MES
                - np.where(op, OTROS_FIJOS_PROYECTO_MES, OTROS_FIJOS_BASE_MES)
                - OPEX_LICENCIAS_MES + ahorro_scrap + MANT_EVITADO_MES * rampa)
    ebitda_inc = ebitda_p - ebitda_b

    dep = np.where(op, dep_mes, 0.0)
    impuesto = TASA_RENTA * np.maximum(ebitda_inc - dep, 0.0)
    fcf = ebitda_inc - impuesto
    fcf[:PREOP] = (-cx["total_cop"] * np.array(FASES_CAPEX)
                   - NOMINA_IMPLEMENTACION_MES - OPEX_LICENCIAS_MES)
    wc = WC_PCT_INGRESO * float((ingreso_p - ingreso_b)[PREOP + 1])
    fcf[PREOP] -= wc
    fcf[-1] += wc

    return {"fcf": fcf, "ebitda_incremental": ebitda_inc,
            "ebitda_base": ebitda_b, "ebitda_proyecto": ebitda_p,
            "ingreso_base": ingreso_b, "ingreso_proyecto": ingreso_p,
            "cogs_base": cogs_b, "cogs_proyecto": cogs_p,
            "ahorro_scrap": ahorro_scrap, "depreciacion": dep,
            "impuesto": impuesto, "capital_trabajo": wc, "capex": cx,
            "unidades": u, "dep_mensual": dep_mes}


def _tir_mensual(flujos: np.ndarray) -> float:
    lo, hi = -0.5, 1.0
    def vpn(r):
        return float(np.sum(flujos / (1 + r) ** np.arange(1, len(flujos) + 1)))
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if vpn(mid) > 0 else (lo, mid)
    return (lo + hi) / 2


def indicadores(demanda_mensual: pd.DataFrame | None = None,
                escenario: str = "Base") -> dict:
    d = flujos_desde_demanda(demanda_mensual)
    f = d["fcf"]
    t = np.arange(1, MESES + 1)
    desc = f / (1 + TMAR_MENSUAL) ** t
    acum, acum_desc = np.cumsum(f), np.cumsum(desc)
    inversion = -float(f[:PREOP].sum())
    tir_m = _tir_mensual(f)
    pb = int(np.argmax(acum > 0) + 1) if (acum > 0).any() else None
    pbd = int(np.argmax(acum_desc > 0) + 1) if (acum_desc > 0).any() else None
    roi = float(f.sum()) / inversion
    vpn = float(desc.sum())
    return {"escenario": escenario, "capex_total_cop": d["capex"]["total_cop"],
            "capex_celdas_cop": d["capex"]["celdas_roboticas_cop"],
            "inversion_preoperativa_cop": inversion,
            "vpn_cop": vpn, "tir_mensual": tir_m,
            "tir_anual": (1 + tir_m) ** 12 - 1,
            "roi_horizonte_60m": roi,
            "roi_anualizado": (1 + roi) ** (12 / MESES) - 1,
            "payback_simple_meses": pb, "payback_descontado_meses": pbd,
            "ebitda_incremental_y1_cop": float(d["ebitda_incremental"][PREOP:PREOP + 12].sum()),
            "capital_trabajo_cop": d["capital_trabajo"],
            "dep_mensual_cop": d["dep_mensual"], "tmar_anual": TMAR_ANUAL,
            "delta_vs_modelo_original": {
                "vpn_pct": round((vpn / REF_XLSM["vpn"] - 1) * 100, 1),
                "nota": "referencia: xlsm (flujo agregado no ligado a demanda)"},
            "flujos": f, "flujos_descontados": desc,
            "acumulado_descontado": acum_desc, "detalle": d}


def sensibilidad(demanda_mensual: pd.DataFrame | None = None) -> pd.DataFrame:
    """Tres escenarios de la base financiera: factores sobre EBITDA inc./CAPEX
    y TMAR distinta (mismos del xlsm: Conservador/Base/Optimista)."""
    d = flujos_desde_demanda(demanda_mensual)
    casos = [("Conservador", 0.95, 1.15, 0.20), ("Base", 1.00, 1.00, 0.18),
             ("Optimista", 1.05, 0.90, 0.16)]
    filas = []
    for nombre, f_v, f_cx, tmar in casos:
        ebitda = d["ebitda_incremental"] * f_v
        dep = d["depreciacion"]
        imp = TASA_RENTA * np.maximum(ebitda - dep, 0.0)
        f = ebitda - imp
        f[:PREOP] = (-d["capex"]["total_cop"] * f_cx * np.array(FASES_CAPEX)
                     - NOMINA_IMPLEMENTACION_MES - OPEX_LICENCIAS_MES)
        f[PREOP] -= d["capital_trabajo"]; f[-1] += d["capital_trabajo"]
        i_m = (1 + tmar) ** (1 / 12) - 1
        desc = f / (1 + i_m) ** np.arange(1, MESES + 1)
        tir_m = _tir_mensual(f)
        filas.append(dict(escenario=nombre, factor_ventas=f_v, factor_capex=f_cx,
                          tmar_anual=tmar, vpn_cop=float(desc.sum()),
                          tir_anual=(1 + tir_m) ** 12 - 1))
    return pd.DataFrame(filas)


if __name__ == "__main__":
    ind = indicadores()
    print(f"CAPEX total: $ {ind['capex_total_cop']/1e6:,.0f} M "
          f"(D&A {ind['dep_mensual_cop']/1e6:,.1f} M/mes por categorias)")
    print(f"EBITDA inc. 12m operativos: $ {ind['ebitda_incremental_y1_cop']/1e6:,.0f} M")
    print(f"VPN $ {ind['vpn_cop']/1e6:,.0f} M · TIR {ind['tir_anual']*100:.2f}% EA · "
          f"ROI60m {ind['roi_horizonte_60m']*100:.1f}% · payback "
          f"{ind['payback_simple_meses']}/{ind['payback_descontado_meses']} m")
    print(f"Δ vs xlsm: {ind['delta_vs_modelo_original']['vpn_pct']:+.1f}%")
    print("\nSensibilidad:")
    print(sensibilidad().to_string(index=False))
