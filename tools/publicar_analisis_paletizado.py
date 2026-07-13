"""
Publica la hoja 'Analisis_Paletizado' del libro: comparacion financiera
antes/despues de automatizar paletizado (3 lineas) y encajonado (solo L1)
-- ver metodologia completa en el docstring de core/analisis_paletizado.py.

Hoja de solo-exhibicion (mismo patron que APU_Ingenieria, decision #11 de
CLAUDE.md): NO alimenta CAPEX_FILAS ni el caso de negocio principal del
proyecto (core/finanzas_negocio.py) -- es un analisis de inversion PARALELO,
especifico de la decision de paletizado/encajonado, con su propio
CAPEX/ahorro/payback/VPN/TIR a 10 anios (vida util de "equipos") descontado
a la misma TMAR de 18% E.A. del motor principal.

Uso: python tools/publicar_analisis_paletizado.py
Requiere Sheets configurado (.env); si no hay credenciales, no hace nada
util (no existe fallback local para esta hoja de solo-exhibicion).
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.sheets_client import Contabilidad
from core.analisis_paletizado import (
    calcular, DOTACION_MANUAL, TURNOS, COSTO_OPERARIO_MES_COP,
    CAPEX_PALETIZADO_USD, ENCAJONADO_L1_USD, AIU_TARIFA_ULOGIX,
    OPEX_MTTO_ULOGIX_PCT, CAPEX_COMERCIAL_USD, PCT_COMISIONAMIENTO_COMERCIAL,
    OPEX_MTTO_COMERCIAL_PCT, REF_KRONES_LINAPAC_EUR, HORIZONTE_ANIOS,
)
from core.finanzas_negocio import TRM, FACTOR_RFQ, TMAR_ANUAL

NOMBRE_LINEA = {"L1": "L1 - Coca-Cola 350ml vidrio retornable",
                "L2": "L2 - QuAtro 1.5L PET",
                "L3": "L3 - Garrafon 25L retornable"}


def _n(x: float, dec: int = 0) -> float:
    return round(float(x), dec)


def _pct(x: float) -> str:
    return "n/a (no recupera en 10a)" if x != x else f"{x*100:.1f}%"


def filas_hoja() -> list[list]:
    r = calcular()
    filas: list[list] = [
        ["Analisis financiero — Paletizado y encajonado: antes vs. ULogix vs. maquina comercial",
         "", "", "", "", "", "", ""],
        ["Compara, para cada linea, 3 opciones en las estaciones de FINAL de linea "
         "(paletizado en L1/L2/L3; encajonado — empacar producto lleno en canastilla — "
         "solo en L1, unico formato retornable en canastilla estandar; L2 no encajona "
         "porque el PET no retornable va en bandeja/pelicula, L3 no encajona porque el "
         "garrafon de 25L es demasiado grande para canastilla estandar y se paletiza a "
         "granel): (A) ANTES — operacion 100% manual con operarios; (B) ULOGIX — CAPEX de "
         "celda robotica + tarifa de servicios ULogix (ingenieria+instalacion+capacitacion, "
         "metodologia APU/AIU de la hoja APU_Ingenieria); (C) COMERCIAL — comprar maquina "
         "estandar de mercado en vez de la celda custom (una maquina POR LINEA, a diferencia "
         "de la celda GANTRY de ULogix que sirve a L1+L2 a la vez).",
         "", "", "", "", "", "", ""],
        ["Horizonte de evaluacion: 10 anios (vida util de \"equipos\" en VIDAS, "
         f"finanzas_negocio.py) descontado a TMAR {TMAR_ANUAL*100:.0f}% E.A. (misma tasa del "
         "caso de negocio principal). Este analisis es PARALELO al caso de negocio del "
         "proyecto completo (CLAUDE.md, Estado actual: VPN $15.935M / TIR 83,8%) — no lo "
         "modifica, es una evaluacion propia de la decision de automatizar paletizado/"
         "encajonado especificamente.",
         "", "", "", "", "", "", ""],
        ["ADVERTENCIA — estimaciones de ingenieria sin cotizacion real:", "", "", "", "", "", "", ""],
        [f"• CAPEX de las celdas de PALETIZADO (GANTRY L1-L2 USD* {CAPEX_PALETIZADO_USD['GANTRY_L1_L2']:,.0f}, "
         f"ROBOT L3 USD* {CAPEX_PALETIZADO_USD['ROBOT_L3']:,.0f}) SI es BOM real de 60 items "
         "(ver hoja CAPEX, decision #15 de CLAUDE.md).",
         "", "", "", "", "", "", ""],
        [f"• CAPEX de la celda de ENCAJONADO L1 (USD* {ENCAJONADO_L1_USD:,.0f}, ~60% del costo "
         "BOM de GANTRY por menor complejidad) es una ESTIMACION nueva, sin BOM de proveedor "
         "— no existe en el CAPEX real del proyecto. A validar con RFQ antes de comprometer capital.",
         "", "", "", "", "", "", ""],
        ["• Las maquinas COMERCIALES (paletizadora/encajonadora estandar off-the-shelf) son "
         "referencias de orden de magnitud de la industria, NO cotizaciones de proveedor.",
         "", "", "", "", "", "", ""],
        [f"• Referencia ilustrativa (NO sustituto funcional): la desencajonadora usada Krones "
         f"Linapac-A-T-1600 (EUR {REF_KRONES_LINAPAC_EUR:,.0f} ExWorks, 1998, ~33.000 bph, "
         "formatos 0,25-1,0L) que cotizo el dueno del proyecto retira botella VACIA de "
         "canastilla al INICIO de linea (antes del lavado) — no paletiza ni encajona producto "
         "lleno al final de linea, que es lo que se compara aqui. Se cita solo como orden de "
         "magnitud de un equipo de manejo de canastilla usado en el mercado europeo.",
         "", "", "", "", "", "", ""],
        ["", "", "", "", "", "", "", ""],
        ["SUPUESTOS", "", "", "", "", "", "", ""],
        ["parametro", "valor", "fuente", "", "", "", "", ""],
        ["Costo operario/mes (RRHH, cargado prestacionalmente)", COSTO_OPERARIO_MES_COP,
         "data/empleados.csv, rol 'Operario de linea' (uniforme)", "", "", "", "", ""],
        ["Dotacion manual paletizado L1/L2 (operarios/turno)", DOTACION_MANUAL["L1"][0],
         "Supuesto documentado — RRHH no distingue rol 'paletizador'", "", "", "", "", ""],
        ["Dotacion manual encajonado L1 (operarios/turno)", DOTACION_MANUAL["L1"][1],
         "Supuesto documentado — apilar vidrio a mano es mas intensivo que envolver PET",
         "", "", "", "", ""],
        ["Dotacion manual paletizado L3 (operarios/turno)", DOTACION_MANUAL["L3"][0],
         "Dato real del modelo de tiempos — cuello de linea (core/tiempos_oee.py)",
         "", "", "", "", ""],
        ["AIU tarifa servicios ULogix (sobre CAPEX equipo)", f"{AIU_TARIFA_ULOGIX*100:.1f}%",
         "Punto medio banda de mercado 25-30% (decision #11, APU_Ingenieria)", "", "", "", "", ""],
        ["Mantenimiento anual celda ULogix (% CAPEX equipo)", f"{OPEX_MTTO_ULOGIX_PCT*100:.0f}%",
         "Referencia industria — contrato de soporte + repuestos", "", "", "", "", ""],
        ["Comisionamiento local maquina comercial (% CAPEX)", f"{PCT_COMISIONAMIENTO_COMERCIAL*100:.0f}%",
         "Referencia industria — electrico/civil/puesta en marcha no incluido ExWorks",
         "", "", "", "", ""],
        ["Mantenimiento anual maquina comercial (% CAPEX equipo)", f"{OPEX_MTTO_COMERCIAL_PCT*100:.0f}%",
         "Referencia industria — sin soporte de ingenieria propio incluido", "", "", "", "", ""],
        ["TRM / FACTOR_RFQ", f"{TRM:,.0f} / {FACTOR_RFQ}",
         "core/finanzas_negocio.py (mismos parametros del caso de negocio principal)",
         "", "", "", "", ""],
        ["", "", "", "", "", "", "", ""],
        ["RESUMEN POR LINEA", "", "", "", "", "", "", ""],
        ["linea", "opcion", "capex_equipo_cop", "tarifa_o_comisionamiento_cop",
         "inversion_total_cop", "ahorro_neto_anual_cop", "payback_anios", "vpn_10a_cop_y_tir"],
    ]

    for linea in ("L1", "L2", "L3"):
        d = r[linea]
        filas.append([NOMBRE_LINEA[linea], "A) Antes (manual)", 0, 0, 0,
                      _n(d["costo_laboral_anual_cop"]), "-", "- (costo evitable, no inversion)"])
        u = d["ulogix"]
        filas.append([NOMBRE_LINEA[linea], "B) ULogix (celda + tarifa)",
                      _n(u["capex_equipo_cop"]), _n(u["tarifa_servicios_cop"]),
                      _n(u["inversion_total_cop"]), _n(u["ahorro_neto_anual_cop"]),
                      _n(u["payback_anios"], 2),
                      f"VPN ${u['vpn_10a_cop']:,.0f} / TIR {_pct(u['tir_anual'])}"])
        c = d["comercial"]
        filas.append([NOMBRE_LINEA[linea], "C) Maquina comercial",
                      _n(c["capex_equipo_cop"]), _n(c["comisionamiento_cop"]),
                      _n(c["inversion_total_cop"]), _n(c["ahorro_neto_anual_cop"]),
                      _n(c["payback_anios"], 2),
                      f"VPN ${c['vpn_10a_cop']:,.0f} / TIR {_pct(c['tir_anual'])}"])
        filas.append(["", "", "", "", "", "", "", ""])

    t = r["TOTAL"]
    filas.append(["TOTAL 3 LINEAS", "A) Antes (manual)", 0, 0, 0,
                  _n(t["costo_laboral_anual_cop"]), "-", "-"])
    tu = t["ulogix"]
    filas.append(["TOTAL 3 LINEAS", "B) ULogix (celda + tarifa)", "", "",
                  _n(tu["inversion_total_cop"]), _n(tu["ahorro_neto_anual_cop"]),
                  _n(tu["payback_anios"], 2),
                  f"VPN ${tu['vpn_10a_cop']:,.0f} / TIR {_pct(tu['tir_anual'])}"])
    tc = t["comercial"]
    filas.append(["TOTAL 3 LINEAS", "C) Maquina comercial", "", "",
                  _n(tc["inversion_total_cop"]), _n(tc["ahorro_neto_anual_cop"]),
                  _n(tc["payback_anios"], 2),
                  f"VPN ${tc['vpn_10a_cop']:,.0f} / TIR {_pct(tc['tir_anual'])}"])

    filas += [
        ["", "", "", "", "", "", "", ""],
        ["DETALLE CAPEX COMERCIAL POR LINEA (referencia de mercado, USD benchmark con FACTOR_RFQ)",
         "", "", "", "", "", "", ""],
        ["linea", "paletizadora_usd", "encajonadora_usd", "", "", "", "", ""],
    ]
    for linea in ("L1", "L2", "L3"):
        pal, enc = CAPEX_COMERCIAL_USD[linea]
        filas.append([NOMBRE_LINEA[linea], pal, enc or "n/a (no aplica en esta linea)",
                      "", "", "", "", ""])

    filas += [
        ["", "", "", "", "", "", "", ""],
        ["CONCLUSION", "", "", "", "", "", "", ""],
        ["ULogix vs. comercial: en las 3 lineas la celda ULogix tiene mejor retorno que la "
         "maquina comercial equivalente — dos motores estructurales, no un supuesto forzado: "
         "(1) la celda GANTRY sirve a L1+L2 a la vez (una maquina comercial no) y (2) el CAPEX "
         "de ULogix parte de costeo directo de BOM (USD*, sin margen de venta), mientras el "
         "comercial es precio de lista de mercado (USD benchmark). La opcion comercial en L2 "
         "ni siquiera recupera la inversion en 10 anios (TIR no aplica).",
         "", "", "", "", "", "", ""],
        ["L1 y L2 (ULogix) son una inversion solida por si solas: TIR "
         f"{_pct(r['L1']['ulogix']['tir_anual'])} y {_pct(r['L2']['ulogix']['tir_anual'])} "
         f"respectivamente, ambas muy por encima de la TMAR de {TMAR_ANUAL*100:.0f}%, payback "
         f"{r['L1']['ulogix']['payback_anios']:.1f} y {r['L2']['ulogix']['payback_anios']:.1f} anios.",
         "", "", "", "", "", "", ""],
        [f"L3 (ULogix) es marginal COMO DECISION AISLADA: TIR {_pct(r['L3']['ulogix']['tir_anual'])} "
         f"queda por debajo de la TMAR, payback {r['L3']['ulogix']['payback_anios']:.1f} anios — "
         "el CAPEX del brazo articulado (USD* 131.896, mas caro que el GANTRY) no se justifica "
         "solo con el ahorro de 2 operarios de 1 turno de garrafon (linea de menor volumen, 120 "
         "dias/anio). Sigue siendo parte defendible del proyecto completo porque el caso de "
         "negocio agregado del retrofit (CLAUDE.md, VPN $15.935M) se sostiene con el EBITDA "
         "incremental demand-driven de las 3 lineas juntas, no con el ahorro de mano de obra de "
         "paletizado de L3 aislado — pero si el criterio fuera SOLO esta decision de automatizar "
         "paletizado, L3 no se pagaria sola en 10 anios al ritmo de volumen actual.",
         "", "", "", "", "", "", ""],
    ]
    return filas


def main() -> None:
    cont = Contabilidad()
    if cont.modo != "sheets":
        raise SystemExit("Sheets no esta configurado (.env) — esta hoja no tiene "
                         "fallback local, es de solo exhibicion.")
    ss = cont._spreadsheet()
    filas = filas_hoja()
    try:
        ws = ss.worksheet("Analisis_Paletizado")
    except Exception:  # noqa: BLE001
        ws = ss.add_worksheet("Analisis_Paletizado", rows=max(80, len(filas) + 10), cols=8)
    ws.clear()
    ws.update(filas, "A1", value_input_option="RAW")
    print(f"Publicado Analisis_Paletizado: {len(filas)} filas")

    r = calcular()
    for linea in ("L1", "L2", "L3", "TOTAL"):
        d = r[linea]
        u, c = d["ulogix"], d["comercial"]
        print(f"  {linea}: ULogix payback {u['payback_anios']:.2f}a TIR "
             f"{_pct(u['tir_anual'])} | Comercial payback {c['payback_anios']:.2f}a TIR "
             f"{_pct(c['tir_anual'])}")


if __name__ == "__main__":
    main()
