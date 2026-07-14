"""
Analisis financiero standalone: paletizado + encajonado, antes vs. despues.

Compara, para cada linea (L1 350ml vidrio retornable, L2 QuAtro 1.5L PET,
L3 garrafon 25L retornable), 3 opciones para las estaciones de FINAL de
linea (paletizado en las 3 lineas; encajonado -- empaque de producto lleno
en canastilla -- solo en L1, unico formato retornable que usa canastilla
estandar; L2 no encajona porque el PET no retornable va en bandeja/pelicula
termoencogible, no en canastilla, y L3 no encajona porque el garrafon de
25L es demasiado grande para el formato de canastilla estandar y se paletiza
a granel con separadores):

  A) ANTES (statu quo)   -- operacion 100% manual con operarios.
  B) ULOGIX (celdas)     -- CAPEX de equipo (BOM real de las celdas
                             roboticas de paletizado ya presupuestadas en
                             CAPEX_FILAS de finanzas_negocio.py, mas una
                             celda de encajonado robotico para L1 que NO
                             existe todavia en el CAPEX del proyecto -- es
                             una estimacion de ingenieria nueva, ver
                             ENCAJONADO_L1_USD) mas la tarifa de servicios
                             de ULogix (ingenieria de detalle + instalacion/
                             EPC + capacitacion, con la MISMA metodologia
                             APU/AIU ya validada en tools/
                             publicar_apu_ingenieria.py y decision #11 de
                             CLAUDE.md -- banda de mercado 25-30%, aqui
                             usamos el punto medio 27.5% sobre el CAPEX de
                             equipo de ESTA cadena de valor especifica, no
                             sobre el CAPEX del proyecto completo).
  C) COMERCIAL            -- comprar una maquina de paletizado/encajonado
                             estandar de mercado en vez de la celda
                             custom de ULogix. A diferencia de la celda
                             GANTRY de ULogix (que sirve a L1 y L2 a la
                             vez), una maquina comercial off-the-shelf no
                             esta disenada para servir dos lineas de
                             formato distinto -- se necesita una por
                             linea. Referencia de mercado usada como ancla
                             de orden de magnitud (NO cotizacion real,
                             ver nota mas abajo): la desencajonadora
                             comercial Krones Linapac-A-T-1600 (usada,
                             1998, EUR 14.000 ExWorks, ~33.000 bph,
                             formatos 0,25-1,0 L -- coincide con el
                             formato de L1) que el dueno del proyecto
                             referencio; NOTA IMPORTANTE: esa maquina es
                             una DESENCAJONADORA (retira botella vacia de
                             la canastilla ANTES del lavado, al INICIO de
                             linea), no una paletizadora ni un
                             encajonador de producto lleno -- no es
                             funcionalmente equivalente a las estaciones
                             que se comparan aqui (paletizado +
                             encajonado, AMBAS al FINAL de linea). Se usa
                             solo como referencia ilustrativa de cuanto
                             cuesta un equipo de manejo de canastillas
                             usado en el mercado europeo de segunda mano,
                             no como sustituto directo.

Todas las cifras de CAPEX de equipo de la celda de encajonado L1 y del
equipo comercial paletizador/encajonador son ESTIMACIONES DE INGENIERIA
documentadas (no hay BOM real ni cotizacion de proveedor para ninguna de
las dos, a diferencia de las celdas de paletizado GANTRY/ROBOT ARTICULADO
que si tienen BOM real de 60 items -- ver decision #15 de CLAUDE.md) --
misma logica de "supuesto documentado, a validar con RFQ real antes de
comprometer capital" que ya se uso para el split de L7 en esa misma
decision. La decision ya alimenta el modelo principal: el equipo esta en
CAPEX y el ahorro laboral monetizable se integra al EBITDA. Este modulo
conserva el comparativo; `Viabilidad_Automatizacion` es la vista viva.

Horizonte: 10 anios (vida util de "equipos" en VIDAS, finanzas_negocio.py)
descontado a TMAR_ANUAL = 18% (misma tasa del motor financiero principal,
reusada aqui por consistencia).
"""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.finanzas_negocio import TRM, FACTOR_RFQ, TMAR_ANUAL

HORIZONTE_ANIOS = 10  # = VIDAS["equipos"] en finanzas_negocio.py

# ---------------------------------------------------------------- insumos reales
# RRHH: costo total empleador (YA cargado prestacionalmente, decision #10 de
# CLAUDE.md) del rol "Operario de linea" -- uniforme en data/empleados.csv.
COSTO_OPERARIO_MES_COP = 3_825_878

# Turnos y dias operativos reales por linea (core/tiempos_oee.py).
TURNOS = {"L1": 2, "L2": 2, "L3": 1}

# Dotacion manual de paletizado/encajonado por turno -- SUPUESTO DOCUMENTADO:
# el roster de RRHH solo tiene el rol generico "Operario de linea", no
# distingue "paletizador" de otras tareas de linea. Para L3 el modelo de
# tiempos SI ata explicitamente 2 operarios x 240 gfn/h = 480 gfn/h al
# paletizado manual (core/tiempos_oee.py, cuello de la linea) -- ese numero
# se reusa tal cual. Para L1/L2 se asume 1 operario/turno dedicado a
# paletizado (patron tipico de una estacion de paletizado manual de una
# linea de esta velocidad) y, solo en L1, 2 operarios/turno adicionales
# para encajonado manual (apilar botella de vidrio en canastilla a mano es
# mas intensivo en mano de obra que envolver con pelicula).
DOTACION_MANUAL = {
    # linea: (operarios/turno paletizado, operarios/turno encajonado)
    "L1": (1, 2),
    "L2": (1, 0),
    "L3": (2, 0),
}

# CAPEX real (BOM 60 items, decision #15) de las celdas de PALETIZADO ya
# presupuestadas en CAPEX_FILAS de finanzas_negocio.py -- USD* (cotizacion
# real, sin FACTOR_RFQ, igual que alli).
CAPEX_PALETIZADO_USD = {
    "GANTRY_L1_L2": 96_493.0,    # IRC5 IGAM baja de 18.000 a 6.500
    "ROBOT_L3": 63_332.0,        # robot EUROBOTS GBP 13.500 + resto BOM
}
# Base de reparto GANTRY L1<->L2: 50/50 por cantidad de operarios de
# paletizado liberados en cada linea (1 operario/turno en ambas, ver
# DOTACION_MANUAL) -- ambas lineas liberan la misma dotacion, reparto
# proporcional a eso.
REPARTO_GANTRY_L1 = 0.5

# ---------------------------------------------------------------- estimaciones nuevas (NO CAPEX real)
# Celda de encajonado robotico ULogix para L1 (NO existe en CAPEX_FILAS,
# no hay BOM de proveedor): estimacion de ingenieria a partir de la
# complejidad relativa a la celda GANTRY (un solo brazo pick&place con
# gripper de botella + magazine de canastilla + PLC/HMI + vallado, sin la
# logica de patron de paletizado completo) ~60% del costo BOM de GANTRY.
ENCAJONADO_L1_USD = 60_000.0
PCT_MONETIZACION_LABORAL = 0.70

# AIU (Administracion+Imprevistos+Utilidad) de la tarifa de servicios de
# ULogix (ingenieria+instalacion+capacitacion) sobre el CAPEX de equipo de
# ESTA cadena de valor -- misma banda de mercado 25-30% de decision #11,
# punto medio.
AIU_TARIFA_ULOGIX = 0.275

# Mantenimiento anual de la celda ULogix (contrato de soporte + repuestos)
# -- referencia tipica de la industria para celdas roboticas, 3% del CAPEX
# de equipo/anio.
OPEX_MTTO_ULOGIX_PCT = 0.03

# ---------------------------------------------------------------- opcion comercial (mercado)
# Maquinas comerciales estandar (off-the-shelf, NO custom ULogix): no hay
# cotizacion real de proveedor para ninguna -- rangos de orden de magnitud
# de la industria de envasado (paletizadoras/encajonadoras robotizadas
# comerciales de capacidad media), documentados como referencia, a validar
# con RFQ real antes de comprometer capital. USD benchmark -> SI lleva
# FACTOR_RFQ (igual tratamiento que las filas "USD" del CAPEX real, a
# diferencia de "USD*"). Se anota ademas, solo como ancla ilustrativa (no
# como sustituto funcional -- ver docstring del modulo), el precio real de
# la desencajonadora usada Krones Linapac-A-T-1600: EUR 14.000 ExWorks
# (~USD 15.100 a EUR/USD ~1.08), un equipo de una sola funcion de manejo de
# canastilla de 1998 -- muy por debajo de una celda robotizada nueva de
# paletizado+encajonado, coherente con ser una funcion mas simple y un
# equipo usado de 27 anios.
CAPEX_COMERCIAL_USD = {
    # linea: (paletizadora estandar, encajonadora estandar o None)
    "L1": (180_000.0, 220_000.0),
    "L2": (180_000.0, None),
    "L3": (140_000.0, None),
}
# Comisionamiento local (electrico, civil, puesta en marcha) no incluido en
# el precio ExWorks del fabricante -- referencia tipica 8% del CAPEX de
# equipo, vs. la tarifa de servicios completa (27.5% AIU) que si incluye
# ingenieria de detalle, FAT/SAT y gestion del cambio de ULogix.
PCT_COMISIONAMIENTO_COMERCIAL = 0.08
# Mantenimiento anual mas alto que la opcion ULogix: sin el soporte de
# ingenieria propio incluido en la tarifa, el mantenimiento de un equipo de
# terceros tipicamente corre mas caro -- referencia 5% del CAPEX/anio.
OPEX_MTTO_COMERCIAL_PCT = 0.05

REF_KRONES_LINAPAC_EUR = 14_000.0  # solo ilustrativo, ver docstring


def _cop_usd_estrella(usd: float) -> float:
    """USD* -- cotizacion real de BOM, sin FACTOR_RFQ (igual que CAPEX_FILAS)."""
    return usd * TRM


def _cop_usd_benchmark(usd: float) -> float:
    """USD -- referencia de mercado no confirmada, CON FACTOR_RFQ."""
    return usd * TRM * FACTOR_RFQ


def _costo_laboral_anual(linea: str) -> float:
    op_pal, op_enc = DOTACION_MANUAL[linea]
    turnos = TURNOS[linea]
    operarios = (op_pal + op_enc) * turnos
    return operarios * COSTO_OPERARIO_MES_COP * 12


def _tir_anual(flujos: np.ndarray) -> float:
    """Biseccion sobre la tasa anual -- mismo metodo que _tir_mensual() en
    finanzas_negocio.py, sin depender de numpy_financial (no es dependencia
    del proyecto)."""
    def vpn(r: float) -> float:
        return float(sum(f / (1 + r) ** t for t, f in enumerate(flujos)))
    if vpn(0.0) <= 0:
        return float("nan")  # nunca recupera la inversion
    lo, hi = 0.0, 5.0
    if vpn(hi) > 0:
        return float("nan")  # TIR fuera de rango razonable
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if vpn(mid) > 0 else (lo, mid)
    return (lo + hi) / 2


def _vpn_tir(inversion: float, ahorro_anual: float) -> tuple[float, float]:
    flujos = np.array([-inversion] + [ahorro_anual] * HORIZONTE_ANIOS)
    vpn = float(sum(f / (1 + TMAR_ANUAL) ** t for t, f in enumerate(flujos)))
    tir = _tir_anual(flujos)
    return vpn, tir


def calcular() -> dict:
    lineas = ["L1", "L2", "L3"]
    resultado = {}

    for linea in lineas:
        costo_laboral = _costo_laboral_anual(linea)
        op_pal, op_enc = DOTACION_MANUAL[linea]
        turnos = TURNOS[linea]

        # ---- CAPEX equipo ULogix (paletizado + encajonado si aplica)
        capex_pal_usd = (CAPEX_PALETIZADO_USD["GANTRY_L1_L2"] * REPARTO_GANTRY_L1
                          if linea == "L1" else
                          CAPEX_PALETIZADO_USD["GANTRY_L1_L2"] * (1 - REPARTO_GANTRY_L1)
                          if linea == "L2" else
                          CAPEX_PALETIZADO_USD["ROBOT_L3"])
        capex_enc_usd = ENCAJONADO_L1_USD if linea == "L1" else 0.0
        capex_equipo_ulogix_cop = _cop_usd_estrella(capex_pal_usd + capex_enc_usd)
        tarifa_ulogix_cop = capex_equipo_ulogix_cop * AIU_TARIFA_ULOGIX
        inversion_ulogix = capex_equipo_ulogix_cop + tarifa_ulogix_cop
        mtto_ulogix = capex_equipo_ulogix_cop * OPEX_MTTO_ULOGIX_PCT
        ahorro_ulogix = costo_laboral * PCT_MONETIZACION_LABORAL - mtto_ulogix
        vpn_u, tir_u = _vpn_tir(inversion_ulogix, ahorro_ulogix)
        payback_u = inversion_ulogix / ahorro_ulogix if ahorro_ulogix > 0 else float("inf")

        # ---- CAPEX equipo comercial
        pal_usd, enc_usd = CAPEX_COMERCIAL_USD[linea]
        equipo_com_usd = pal_usd + (enc_usd or 0.0)
        capex_equipo_com_cop = _cop_usd_benchmark(equipo_com_usd)
        comisionamiento_cop = capex_equipo_com_cop * PCT_COMISIONAMIENTO_COMERCIAL
        inversion_comercial = capex_equipo_com_cop + comisionamiento_cop
        mtto_comercial = capex_equipo_com_cop * OPEX_MTTO_COMERCIAL_PCT
        ahorro_comercial = costo_laboral * PCT_MONETIZACION_LABORAL - mtto_comercial
        vpn_c, tir_c = _vpn_tir(inversion_comercial, ahorro_comercial)
        payback_c = (inversion_comercial / ahorro_comercial
                     if ahorro_comercial > 0 else float("inf"))

        resultado[linea] = {
            "turnos": turnos,
            "operarios_paletizado_turno": op_pal,
            "operarios_encajonado_turno": op_enc,
            "operarios_totales_liberados": (op_pal + op_enc) * turnos,
            "costo_laboral_anual_cop": costo_laboral,
            "antes": {"capex_cop": 0.0, "opex_anual_cop": costo_laboral},
            "ulogix": {
                "capex_equipo_cop": capex_equipo_ulogix_cop,
                "tarifa_servicios_cop": tarifa_ulogix_cop,
                "inversion_total_cop": inversion_ulogix,
                "opex_mtto_anual_cop": mtto_ulogix,
                "ahorro_neto_anual_cop": ahorro_ulogix,
                "payback_anios": payback_u,
                "vpn_10a_cop": vpn_u,
                "tir_anual": tir_u,
            },
            "comercial": {
                "capex_equipo_cop": capex_equipo_com_cop,
                "comisionamiento_cop": comisionamiento_cop,
                "inversion_total_cop": inversion_comercial,
                "opex_mtto_anual_cop": mtto_comercial,
                "ahorro_neto_anual_cop": ahorro_comercial,
                "payback_anios": payback_c,
                "vpn_10a_cop": vpn_c,
                "tir_anual": tir_c,
            },
        }

    # ---- agregado 3 lineas
    for opcion in ("ulogix", "comercial"):
        inv = sum(resultado[l][opcion]["inversion_total_cop"] for l in lineas)
        ahorro = sum(resultado[l][opcion]["ahorro_neto_anual_cop"] for l in lineas)
        vpn, tir = _vpn_tir(inv, ahorro)
        resultado.setdefault("TOTAL", {})[opcion] = {
            "inversion_total_cop": inv,
            "ahorro_neto_anual_cop": ahorro,
            "payback_anios": inv / ahorro if ahorro > 0 else float("inf"),
            "vpn_10a_cop": vpn,
            "tir_anual": tir,
        }
    resultado["TOTAL"]["costo_laboral_anual_cop"] = sum(
        resultado[l]["costo_laboral_anual_cop"] for l in lineas)
    resultado["TOTAL"]["operarios_totales_liberados"] = sum(
        resultado[l]["operarios_totales_liberados"] for l in lineas)

    return resultado


if __name__ == "__main__":
    r = calcular()
    for linea in ("L1", "L2", "L3", "TOTAL"):
        d = r[linea]
        print(f"\n=== {linea} ===")
        if linea != "TOTAL":
            print(f"  operarios liberados: {d['operarios_totales_liberados']} "
                  f"({d['operarios_paletizado_turno']} paletizado + "
                  f"{d['operarios_encajonado_turno']} encajonado, x{d['turnos']} turnos)")
        print(f"  costo laboral antes: ${d['costo_laboral_anual_cop']:,.0f} COP/anio")
        for opcion in ("ulogix", "comercial"):
            o = d[opcion]
            print(f"  {opcion}: inversion ${o['inversion_total_cop']:,.0f} -> "
                  f"ahorro neto ${o['ahorro_neto_anual_cop']:,.0f}/anio -> "
                  f"payback {o['payback_anios']:.2f} anios -> "
                  f"VPN(10a) ${o['vpn_10a_cop']:,.0f} -> TIR {o['tir_anual']*100:.1f}%")
