"""
Motor de escenarios v4 — factores del script 13 del repositorio (documentados,
con fuente) + ELASTICIDADES DIFERENCIADAS P1 vs P2:

El repositorio aplicaba el mismo factor a "gaseosas" (P1 y P2). v4 diferencia
por formato, con justificacion:
- Mundial 2026: el consumo en punto de venta / eventos favorece el formato
  PERSONAL (350 ml RGB) sobre el familiar (1.5 L hogar).
- Recesion: downtrading documentado por KOF hacia RETORNABLES (asequibilidad):
  P1 cae menos (-3%) y P2 mas (-7%); el blend conserva el ~-5% del escenario
  original. El garrafon (bien basico) -2%.
Los factores son multiplicativos mes a mes sobre el pronostico base; el modelo
estadistico nunca se toca. Indices de mes: 0=Abr-26 ... 11=Mar-27.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings
from core.forecast import ResultadoPronostico, pronostico_base

HOR_MESES = ["Abr", "May", "Jun", "Jul", "Ago", "Sep",
             "Oct", "Nov", "Dic", "Ene", "Feb", "Mar"]
SKUS = ["P1-CC350-RGB", "P2-QT1500-PET", "P3-GARR25L"]


def f(base: float = 1.0, overrides: dict[int, float] | None = None) -> dict[str, float]:
    """Vector de 12 factores por nombre de mes; overrides por indice (0=Abr)."""
    v = {m: base for m in HOR_MESES}
    for i, val in (overrides or {}).items():
        v[HOR_MESES[int(i)]] = val
    return v


@dataclass
class Escenario:
    nombre: str
    justificacion: str
    fuente: str
    factores: dict[str, dict[str, float]]  # sku -> {mes: factor}

    def factor(self, sku: str, mes: str) -> float:
        return self.factores.get(sku, {}).get(mes, 1.0)


def _esc(nombre, justificacion, fuente, p1=None, p2=None, p3=None) -> Escenario:
    return Escenario(nombre, justificacion, fuente, {
        "P1-CC350-RGB": p1 or f(), "P2-QT1500-PET": p2 or f(),
        "P3-GARR25L": p3 or f()})


ESCENARIOS: dict[str, Escenario] = {}

ESCENARIOS["Base"] = _esc(
    "Base", "Pronostico oficial v4 sin ajuste (HW + Bates-Granger optimo).",
    "Scripts 01-04 del repositorio; backtest un-paso 5 trimestres.")

ESCENARIOS["Mundial 2026"] = _esc(
    "Mundial 2026",
    "Plan comercial KOF para el Mundial FIFA (11-jun a 19-jul-2026). v4 "
    "diferencia formatos: el consumo personal/on-premise (P1, 350 ml) capta "
    "mas el evento que el familiar (P2, 1.5 L hogar); garrafon casi ajeno "
    "(r=0.12 con refrescos).",
    "Refs [12],[13],[20] del reporte; historico de torneos en reportes KOF.",
    p1=f(1.00, {2: 1.08, 3: 1.12, 4: 1.03}),
    p2=f(1.00, {2: 1.05, 3: 1.07, 4: 1.02}),
    p3=f(1.00, {2: 1.01, 3: 1.02}))

ESCENARIOS["Paro nacional / choque logistico"] = _esc(
    "Paro nacional / choque logistico",
    "Disrupcion de transporte ~2 semanas (ilustrada en agosto): -18% en las "
    "tres lineas por dias de despacho perdidos; octubre recupera +4% por "
    "pedidos represados.",
    "Impacto reportado por KOF/ANDI en el paro nacional de 2021.",
    p1=f(1.00, {4: 0.82, 6: 1.04}), p2=f(1.00, {4: 0.82, 6: 1.04}),
    p3=f(1.00, {4: 0.82, 6: 1.04}))

ESCENARIOS["Recesion moderada"] = _esc(
    "Recesion moderada",
    "Caida de ingreso disponible desde junio. v4 diferencia por downtrading "
    "hacia retornables (asequibilidad KOF): P1 -3%, P2 -7% (blend ~-5% del "
    "escenario original); garrafon (bien basico) -2%.",
    "Elasticidades LatAm citadas en el reporte; estrategia de asequibilidad KOF.",
    p1=f(1.00, {i: 0.97 for i in range(2, 12)}),
    p2=f(1.00, {i: 0.93 for i in range(2, 12)}),
    p3=f(1.00, {i: 0.98 for i in range(2, 12)}))

ESCENARIOS["Restriccion hidrica adicional (CAR)"] = _esc(
    "Restriccion hidrica adicional (CAR)",
    "Endurecimiento de la Resolucion CAR 347/2026 (La Calera): -15% sostenido "
    "en garrafon desde julio; P1/P2 sin efecto (acueducto, no manantial).",
    "Ref [12] del reporte; racionamiento EAAB 2024-2025.",
    p3=f(1.00, {i: 0.85 for i in range(3, 12)}))

ESCENARIOS["Repunte agresivo post-impuesto"] = _esc(
    "Repunte agresivo post-impuesto",
    "La recuperacion de refrescos tras el impuesto saludable (+9.2% interanual "
    "real en 1T-2026) se sostiene mas alla del modelo base (ya conservador, "
    "phi<1): +5% sostenido en P1 y P2.",
    "Ref [21] del reporte; Ley 2277/2022.",
    p1=f(1.05), p2=f(1.05))


def aplicar_escenario(res: ResultadoPronostico, esc: Escenario) -> pd.DataFrame:
    df = res.mensual.copy()
    for sku in SKUS:
        fac = df["mes"].map(lambda m: esc.factor(sku, m))
        for suf in ("_unidades", "_litros", "_p05", "_p95"):
            df[f"{sku}{suf}"] = (df[f"{sku}{suf}"] * fac).round().astype(int)
        df[f"{sku}_factor"] = fac
    return df


def escenario_personalizado(nombre: str, factores_p1: dict[str, float],
                            factores_p2: dict[str, float],
                            factores_p3: dict[str, float],
                            justificacion: str = "Escenario definido por el usuario",
                            fuente: str = "Dashboard Ulogix") -> Escenario:
    base = {m: 1.0 for m in HOR_MESES}
    return Escenario(nombre, justificacion, fuente, {
        "P1-CC350-RGB": {**base, **factores_p1},
        "P2-QT1500-PET": {**base, **factores_p2},
        "P3-GARR25L": {**base, **factores_p3}})


def resumen_comparativo(res: ResultadoPronostico,
                        escenarios: list[Escenario] | None = None) -> pd.DataFrame:
    escenarios = escenarios or list(ESCENARIOS.values())
    base_tot = {sku: int(res.mensual[f"{sku}_unidades"].sum()) for sku in SKUS}
    filas = []
    for esc in escenarios:
        d = aplicar_escenario(res, esc)
        fila = {"escenario": esc.nombre}
        for sku in SKUS:
            tot = int(d[f"{sku}_unidades"].sum())
            fila[f"{sku}_total"] = tot
            fila[f"{sku}_delta_pct"] = round(100 * (tot / base_tot[sku] - 1), 2)
        fila["justificacion"] = esc.justificacion
        filas.append(fila)
    return pd.DataFrame(filas)


if __name__ == "__main__":
    r = pronostico_base(mc_n=500)
    print(resumen_comparativo(r)[["escenario"] +
          [c for c in resumen_comparativo(r).columns if "delta" in c]].to_string(index=False))
