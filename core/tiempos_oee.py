"""
Tiempos y OEE v2 — fuente unica: 'Tiempos_Fontibon_Corregido' (auditoria APM
del archivo original de tiempos; 8 hallazgos corregidos, ver hoja Correcciones
del libro). Estas tablas son DOCUMENTALES: alimentan las hojas Tiempos/OEE_TEEP
del libro para los disenos del equipo. Los KPIs VIVOS de OEE/TEEP NO se
gestionan en el ERP: llegan por MQTT segun el UNS (FEMSA/+/MES/KPI/#) y se
consultan en las paginas Produccion y Base de datos (tabla kpi_uns).

Datos corregidos clave:
- Tasas nominales con soporte de visita: L1 42.500 bph · L2 12.000 · L3 480
  (llenadora 600 gfn/h pero el paletizado MANUAL de 2 operarios a 240 gfn/h
  por operario es el cuello real -> la celda robotica lo elimina).
- Calendario Bogota: L1/L2 286 dias-2 turnos · L3 120 dias-1 turno.
- OEE bottom-up: A=Ter/Tep=0.8902 (Tt 8h - Tip 1.167h - Tnp 0.75h),
  SE=Rp_real/Rp_diseno, RE por microparos medidos, Q=0.99932 ->
  OEE 77.1/76.5/75.4% (valida el rango 75-78% observado en la visita).
- TEEP = OEE x carga calendario: 40.3/40.0/8.3% (L3 solo 120 dias, 1 turno).
- HALLAZGO DE CAPACIDAD: con 2 turnos U_2026 = 1.25 (L1) y 1.30 (L2):
  INFACTIBLE. Con 3er turno: U = 0.83/0.86 -> factible. L3 con 1 operario
  daria U=1.61 -> la celda robotica es la que evita el 2do operario.
- Lote Q = produccion de UN turno redondeada a pallets: 262,440 / 73,080 /
  2,880 und (162 / 87 / 96 pallets). Tsu = 70 min.
- MLT (lote-turno, VSM estacion-por-estacion del archivo corregido): L1
  16.98 h · **L2 19.26 h · L3 15.57 h** (corregido 2026-07: el modulo tenia
  16.44/14.9, valores que no coincidian con el archivo fuente
  'Tiempos_Fontibon_Corregido.xlsx', hoja MLT_VSM — bug real, no solo
  redondeo, ya corregido).

Mejora de OEE a implementar: **+5% relativo, EXACTO, por linea** (no una
cifra plana aproximada) — `oee_a_implementar = oee_base * 1.05` para cada
linea. El delta en puntos porcentuales que eso exige es LIGERAMENTE distinto
por linea porque cada una parte de un OEE base distinto (L1 +3.856pp, L2
+3.825pp, L3 +3.769pp — ver `MEJORA_PP_POR_LINEA`), repartido 50/30/20% entre
disponibilidad/rendimiento/calidad (celdas roboticas de paletizado eliminan
microparos y bajan MTTR -> disponibilidad; retrofit de llenadoras estabiliza
SE/RE -> rendimiento; reasignacion de inspectoras HEUFT/Linatronic ya
existentes entre L1<->L2, capex-cero, ver 'Maquinas_Referencias' del archivo
fuente -> calidad). El +5% se alcanza al cierre del mes 4 de preoperacion
(ver `CRONOGRAMA_MEJORA_OEE`, atado a las 4 fases de CAPEX de
`core/finanzas_negocio.py: FASES_CAPEX`). La meta aspiracional de programa
(>=86%) queda documentada aparte: es un techo de largo plazo, NO la meta del
+5% estricto del caso de negocio actual — no confundir ambas.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings

# ------------------- datos corregidos (Tiempos_Fontibon_Corregido) ----------
LINEAS = ["L1", "L2", "L3"]
DATOS = {
    "L1": dict(producto="Coca-Cola 350 ml vidrio retornable", sku="P1-CC350-RGB",
               rp_nominal=42500, rp_diseno=45000, turnos=2, horas_turno=8,
               dias_ano=286, und_pallet=1620, q_lote=262440, pallets_lote=162,
               re_microparos=0.917808, mlt_lote_h=16.98),
    "L2": dict(producto="QuAtro 1.5 L PET NR", sku="P2-QT1500-PET",
               rp_nominal=12000, rp_diseno=13000, turnos=2, horas_turno=8,
               dias_ano=286, und_pallet=840, q_lote=73080, pallets_lote=87,
               re_microparos=0.931506, mlt_lote_h=19.258142),
    "L3": dict(producto="Garrafon 25 L retornable", sku="P3-GARR25L",
               rp_nominal=480, rp_diseno=520, turnos=1, horas_turno=8,
               dias_ano=120, und_pallet=30, q_lote=2880, pallets_lote=96,
               re_microparos=0.917808, mlt_lote_h=15.573906),
}
TT, TIP, TNP, TSU_MIN, Q_CALIDAD = 8.0, 1.1667, 0.75, 70, 0.99932
# reparto 50/30/20% del Δpp EXACTO que cada linea necesita para llegar a
# oee_base*1.05 (calculado en _mejora_pp_linea() -- no una cifra plana igual
# para las 3 lineas, porque cada una parte de un oee_base distinto)
REPARTO_MEJORA = {"disponibilidad": 0.50, "rendimiento": 0.30, "calidad": 0.20}
CRONOGRAMA_MEJORA_OEE = [
    # (fase, mes_preop, capex_pct_fase, palanca, componente_oee, detalle)
    (1, 1, 0.20, "Ingenieria de detalle + pedidos de celdas roboticas y llenadoras",
     None, "Sin ganancia de OEE aun -- fase de ingenieria/procura."),
    (2, 2, 0.35, "Instalacion y comisionamiento de celdas roboticas de paletizado (L1-L2/L3)",
     "disponibilidad", "Elimina microparos y esperas del paletizado manual; baja MTTR "
     "(monitoreable por UNS/MES) -> gana el componente de disponibilidad."),
    (3, 3, 0.27, "Retrofit de llenadoras (Modulfill/Contiform)",
     "rendimiento", "Estabiliza la velocidad real vs nominal (SE) y reduce microparos "
     "de llenado (RE) -> gana el componente de rendimiento."),
    (4, 4, 0.18, "Reasignacion de inspectoras existentes (HEUFT PRIME L2->L1, "
     "Linatronic 713 L1->L2, capex-cero) + arranque operativo pleno",
     "calidad", "Reduce scrap/reprocesos -> gana el componente de calidad. Al cierre "
     "de esta fase (mes 4 de preoperacion) el +5% relativo queda completo, "
     "justo antes de la rampa operativa del mes 5 (RAMPA_MES5 del modelo financiero)."),
]
NOTA_UNS = ("KPIs vivos de OEE/TEEP: NO se gestionan en el ERP; llegan por "
            "MQTT segun el UNS (FEMSA/+/MES/KPI/#).")


def _mejora_pp_linea(linea: str, factor: float = 1.05) -> dict:
    """Delta en pp EXACTO que la linea necesita para llegar a oee_base*factor,
    repartido segun REPARTO_MEJORA entre disponibilidad/rendimiento/calidad."""
    base = componentes_oee(linea)["OEE"]
    delta_pp = (base * factor - base) * 100
    return {
        "delta_total_pp": delta_pp,
        "disponibilidad_pp": delta_pp * REPARTO_MEJORA["disponibilidad"],
        "rendimiento_pp": delta_pp * REPARTO_MEJORA["rendimiento"],
        "calidad_pp": delta_pp * REPARTO_MEJORA["calidad"],
    }


def _params() -> dict:
    return json.load(open(settings.DATA_DIR / "parametros_planta.json",
                          encoding="utf-8"))


def unidades_por_pallet(linea: str) -> int:
    return DATOS[linea]["und_pallet"]


def componentes_oee(linea: str) -> dict:
    d = DATOS[linea]
    tep = TT - TIP
    ter = tep - TNP
    a = ter / tep
    se = d["rp_nominal"] / d["rp_diseno"]
    pe = d["re_microparos"] * se
    oee = a * pe * Q_CALIDAD
    carga = d["turnos"] * d["horas_turno"] * d["dias_ano"] / (24 * 365)
    return dict(A=a, SE=se, RE=d["re_microparos"], PE=pe, Q=Q_CALIDAD,
                OEE=oee, carga=carga, TEEP=oee * carga, Ter=ter, Tep=tep)


def tabla_tiempos(demanda_mensual: pd.DataFrame | None = None) -> pd.DataFrame:
    """Estudio de tiempos por linea (documental, formulas APM del archivo
    corregido): Tc, T_D, takt (si hay demanda), Tb, Tp, Rp_lote, MLT, lote."""
    filas = []
    for lin in LINEAS:
        d, c = DATOS[lin], componentes_oee(lin)
        tc = 3600 / d["rp_nominal"]
        tb_h = TSU_MIN / 60 + d["q_lote"] * tc / 3600
        tp_s = tb_h * 3600 / d["q_lote"]
        fila = dict(
            linea=lin, producto=d["producto"],
            rp_nominal_uph=d["rp_nominal"], rp_diseno_uph=d["rp_diseno"],
            ciclo_Tc_s=round(tc, 4), turnos=d["turnos"],
            horas_turno=d["horas_turno"], dias_operativos_ano=d["dias_ano"],
            tsu_alistamiento_min=TSU_MIN,
            q_lote_turno_und=d["q_lote"], pallets_por_lote=d["pallets_lote"],
            unidades_por_pallet=d["und_pallet"],
            tb_lote_h=round(tb_h, 3), tp_s_por_und=round(tp_s, 4),
            rp_lote_uph=round(3600 / tp_s, 0),
            mlt_lote_h=d["mlt_lote_h"],
            capacidad_efectiva_anual_und=round(
                d["rp_nominal"] * d["turnos"] * d["horas_turno"]
                * d["dias_ano"] * c["OEE"]),
        )
        if demanda_mensual is not None:
            sku = d["sku"]
            dem_dia = float(demanda_mensual[f"{sku}_unidades"].mean()) * 12 / d["dias_ano"]
            t_d = d["turnos"] * c["Ter"] * 3600
            fila["takt_s_por_und"] = round(t_d / max(dem_dia, 1), 4)
            fila["U_utilizacion"] = round(
                dem_dia * 12 / 12 / (fila["capacidad_efectiva_anual_und"] / d["dias_ano"]), 3)
        if lin == "L3":
            fila["nota"] = ("Cuello real: paletizado MANUAL (2 op x 240 gfn/h); "
                            "con 1 operario U=1.61 -> la celda robotica lo elimina")
        filas.append(fila)
    return pd.DataFrame(filas)


def tabla_oee() -> pd.DataFrame:
    """OEE bottom-up (documental) + mejora +5% relativo EXACTO por linea
    (no una cifra plana) + meta aspiracional 86% (largo plazo, distinta del
    +5% estricto del caso de negocio actual)."""
    p = _params()
    factor = p.get("mejora_oee", {}).get("factor", 1.05)
    meta = p.get("mejora_oee", {}).get("meta_programa_oee", 0.86)
    filas = []
    for lin in LINEAS:
        d, c = DATOS[lin], componentes_oee(lin)
        m = _mejora_pp_linea(lin, factor)
        oee_impl = c["OEE"] * factor
        filas.append(dict(
            linea=lin, producto=d["producto"],
            A_disponibilidad=round(c["A"], 4), SE_tasa=round(c["SE"], 4),
            RE_microparos=round(c["RE"], 4), PE_desempeno=round(c["PE"], 4),
            Q_calidad=Q_CALIDAD, oee_base=round(c["OEE"], 4),
            carga_calendario=round(c["carga"], 4), teep=round(c["TEEP"], 4),
            mejora_disponibilidad_pp=round(m["disponibilidad_pp"], 3),
            mejora_rendimiento_pp=round(m["rendimiento_pp"], 3),
            mejora_calidad_pp=round(m["calidad_pp"], 3),
            mejora_total_pp=round(m["delta_total_pp"], 3),
            oee_a_implementar=round(oee_impl, 4),
            meta_programa_oee=meta,
            justificacion=(
                f"+{m['disponibilidad_pp']:.2f}pp A: celdas roboticas de paletizado "
                "eliminan microparos y bajan MTTR (UNS/MES) | "
                f"+{m['rendimiento_pp']:.2f}pp SE/RE: retrofit de llenadoras | "
                f"+{m['calidad_pp']:.2f}pp Q: reasignacion de inspectoras existentes "
                "HEUFT/Linatronic (capex-cero, ver Maquinas_Referencias) -- suma "
                f"{m['delta_total_pp']:.3f}pp = exactamente +5% relativo "
                f"({c['OEE']*100:.2f}% -> {oee_impl*100:.2f}%)"),
        ))
    return pd.DataFrame(filas)


def tabla_capacidad(demanda_mensual: pd.DataFrame | None = None) -> pd.DataFrame:
    """Capacidad efectiva vs demanda (hallazgo del archivo corregido)."""
    filas = []
    dem_anual = {}
    if demanda_mensual is not None:
        for lin in LINEAS:
            dem_anual[lin] = float(
                demanda_mensual[f"{DATOS[lin]['sku']}_unidades"].sum())
    ref_2026 = {"L1": 186_953_224, "L2": 54_436_369, "L3": 277_477}
    for lin in LINEAS:
        d, c = DATOS[lin], componentes_oee(lin)
        cap = d["rp_nominal"] * d["turnos"] * d["horas_turno"] * d["dias_ano"] * c["OEE"]
        dem = dem_anual.get(lin, ref_2026[lin])
        cap3 = d["rp_nominal"] * 3 * d["horas_turno"] * 286 * c["OEE"]
        filas.append(dict(
            linea=lin, demanda_2026_und=round(dem),
            capacidad_efectiva_und=round(cap),
            U_turnos_actuales=round(dem / cap, 3),
            capacidad_3_turnos_und=round(cap3),
            U_con_3_turnos=round(dem / cap3, 3),
            dictamen=("INFACTIBLE con turnos actuales -> requiere 3er turno"
                      if dem / cap > 1 else "Factible con turnos actuales"),
        ))
    return pd.DataFrame(filas)


if __name__ == "__main__":
    pd.set_option("display.width", 240)
    print(tabla_tiempos()[["linea", "rp_nominal_uph", "q_lote_turno_und",
                           "pallets_por_lote", "tb_lote_h", "mlt_lote_h",
                           "capacidad_efectiva_anual_und"]].to_string(index=False))
    print()
    print(tabla_oee()[["linea", "A_disponibilidad", "PE_desempeno", "oee_base",
                       "teep", "oee_a_implementar"]].to_string(index=False))
    print()
    print(tabla_capacidad().to_string(index=False))
