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

GOBIERNO DE PARAMETROS (Sheets manda, Python es el fallback).
Todos los parametros escalares de abajo (TRM, TMAR, nomina, otros fijos,
licencias, vidas utiles, fases de CAPEX...), el CAPEX tabular (CAPEX_FILAS) y
las unit economics por SKU se leen en cada llamada desde la hoja 'Parametros'
(pares clave-valor) y la hoja 'CAPEX' (tabla) del libro de Google Sheets via
`integrations.sheets_client.Contabilidad`, con TTL corto en memoria de proceso
para no golpear la API en cada rerun de Streamlit. Los valores hardcodeados en
este modulo (constantes de mayuscula abajo) son el DEFAULT/FALLBACK: si Sheets
no esta configurado, la celda esta vacia o el valor no castea a numero, el
motor sigue funcionando exactamente igual que antes de esta capa. Este modulo
sigue siendo puro (sin Streamlit); la lectura de Sheets vive en
integrations/sheets_client.py y aqui solo se invoca.

Decision de diseno #3 de CLAUDE.md (historial): hasta esta version,
CAPEX_FILAS aqui era la FUENTE UNICA y el generador del libro Excel
(../femsa-modelo-financiero) la importaba. Por pedido explicito del dueño del
proyecto esa direccion se invierte: ahora el libro de Sheets es la fuente
viva y estas constantes son el "seed"/fallback inicial (ver CLAUDE.md).
"""
from __future__ import annotations

from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings

SKUS = ["P1-CC350-RGB", "P2-QT1500-PET", "P3-GARR25L"]

# ------------------------------ parametros (defaults; ver hoja Parametros en Sheets)
TRM = 3248.87  # SFC, vigente 11-14 jul-2026
GBP_COP = 4437.0  # referencia GBP/COP jul-2026; editable en Parametros
FACTOR_RFQ = 0.97
TMAR_ANUAL = 0.18
MESES, PREOP = 60, 4
UPLIFT_THROUGHPUT = 0.11
FACTOR_MONETIZACION = 0.31
RAMPA_MES5 = 0.67
SCRAP_PP = 0.0004
MANT_EVITADO_MES = 85_000_000.0
AHORRO_LABORAL_MES = 26_781_146.0  # 10 FTE equivalentes x 70% monetizable
TASA_RENTA = 0.35
WC_PCT_INGRESO = 0.08
FASES_CAPEX = [0.20, 0.35, 0.27, 0.18]
NOMINA_OPERACION_MES = 85_915_382.0      # Personal (base y proyecto)
NOMINA_IMPLEMENTACION_MES = 87_161_760.0  # equipo ULogix, meses pre-op
OTROS_FIJOS_BASE_MES = 250_000_000.0
OTROS_FIJOS_PROYECTO_MES = 280_000_000.0
OPEX_LICENCIAS_MES = 14_180_736.67
CAPEX_SOFTWARE = 34_650_000.0             # licencias perpetuas capitalizables
DSO, DIO, DPO = 25, 17, 30                # dias (balance) — no gobernados por Sheets aun
REF_XLSM = {"vpn": 2_180_752_718.0, "tir_anual": 0.2316,
            "ebitda_y1": 8_053_914_020.0}

# ------------------------------ CAPEX (default/fallback; ver hoja CAPEX en Sheets)
# (seccion, linea, activo, cant, moneda, costo_unit, vida_anios, categoria_dep)
#
# 2026-07: alcance del proyecto reducido por pedido explicito del dueño --
# ya no se compran lavadoras ni elementos de inspeccion de linea (quedan en
# cantidad=0, no se borran, para conservar el registro de que se evaluaron y
# se excluyeron). Las 2 filas resumen de celdas roboticas se expandieron a
# detalle de componente real a partir de las BOM de ingenieria de las celdas
# de paletizado (GANTRY L1-L2, brazo articulado L3) -- ver decision de diseno
# #15 de CLAUDE.md. moneda "USD*" = cotizacion real de la BOM (sin el factor
# RFQ de "USD", que es solo un benchmark no confirmado).
CAPEX_FILAS = [
    ("Benchmark retrofit", "L2 330 mL", "Upgrade lavadora retornable / prewash (KRONES Lavatec)", 0, "USD", 450_000, 10, "equipos"),
    ("Benchmark retrofit", "L2 330 mL", "Inspeccion envase vacio (HEUFT SPECTRUM II SX)", 0, "USD", 180_000, 7, "automatizacion"),
    ("Maquinaria usada", "L1 350 mL RGB", "Llenadora/tapadora KRONES usada 44.000 bph (VODM/Modulfill; reserva RFQ)", 1, "USD", 550_000, 10, "equipos"),
    ("Benchmark retrofit", "L2 330 mL", "Etiquetadora y sincronizacion (servos)", 0, "USD", 120_000, 7, "automatizacion"),
    ("Maquinaria usada", "L1 350 mL RGB", "Conveyors, motores y VFD para llenado y encajonado", 1, "USD", 100_000, 7, "equipos"),
    ("Diseño ULogix", "L1 350 mL RGB", "Encajonadora custom para canastilla 30x30 (BOM de ingenieria; reserva RFQ)", 1, "USD", 60_000, 10, "automatizacion"),
    ("Maquinaria usada", "L2 PET 1.5 L", "Llenadora KRONES usada CSD PET 18.000 bph (Mecafill/Contiform; reserva RFQ)", 1, "USD", 425_000, 10, "equipos"),
    ("Benchmark retrofit", "L3 PET 1.5 L", "Inspeccion botella llena (HEUFT PRIME)", 0, "USD", 160_000, 7, "automatizacion"),
    ("Maquinaria usada", "L2 PET 1.5 L", "KRONES Variopac 459 usada para termoencogible (Machinio)", 1, "USD*", 79_900, 7, "equipos"),
    ("Maquinaria usada", "L2 PET 1.5 L", "Conveyors / transporte PET y enlace al GANTRY compartido", 1, "USD", 90_000, 10, "equipos"),
    ("Benchmark retrofit", "L7 Agua 25 L", "Lavado y sanitizacion garrafon", 0, "USD", 230_000, 10, "equipos"),
    ("Benchmark retrofit", "L7 Agua 25 L", "Skid tratamiento de agua (KRONES Hydronomic)", 0, "USD", 320_000, 10, "equipos"),
    # split de "Llenado / taponado / inspeccion garrafon" ($240k, mismo patron que
    # ya uso el usuario en L2/L3 al separar llenado de inspeccion en filas propias.
    # Sin desglose real del proveedor para garrafon: se estima inspeccion ~15% del
    # combo (banda baja vs. L2 180k/830k=21.7% y L3 160k/1010k=15.8%, razonable
    # porque garrafon es la linea mas lenta -- 480 und/h, core/tiempos_oee.py -- y
    # un chequeo de nivel de llenado ahi es mecanicamente mas simple que la vision
    # de envase vacio/lleno de L2/L3). Suma exacta = 240_000 (204_000 + 36_000).
    ("Fuera de alcance", "L3 Garrafon 25 L", "Llenado / taponado garrafon (equipo existente suficiente)", 0, "USD", 204_000, 10, "equipos"),
    ("Benchmark retrofit", "L7 Agua 25 L", "Inspeccion garrafon", 0, "USD", 36_000, 10, "automatizacion"),
    ("Fuera de alcance", "L3 Garrafon 25 L", "Conveyors generales de garrafon (manejo de celda ya esta en BOM)", 0, "USD", 110_000, 7, "equipos"),
    ("Benchmark retrofit", "Comun", "PLC panels / I/O / seguridad (CompactLogix + safety)", 3, "USD", 106_667, 7, "automatizacion"),
    ("Benchmark retrofit", "Comun", "HMIs / estaciones SCADA", 6, "USD", 10_000, 5, "automatizacion"),
    ("Benchmark retrofit", "Comun", "Camaras y vision artificial (Cognex)", 0, "USD", 95_000, 5, "automatizacion"),
    ("Benchmark retrofit", "Comun", "Sensores / transmisores / valvulas (pack)", 1, "USD", 55_000, 5, "automatizacion"),
    ("Benchmark retrofit", "Comun", "Red industrial y ciberseguridad (switches/FW/UPS)", 1, "USD", 75_000, 5, "automatizacion"),
    ("Benchmark retrofit", "Comun", "Servidor edge / historian / gateway MES-UNS (MQTT)", 1, "USD", 90_000, 5, "automatizacion"),
    ("Servicios", "Comun", "Ingenieria de detalle, FAT/SAT y PMO", 1, "COP", 546_493_840, 5, "servicios"),
    ("Servicios", "Comun", "Instalacion y puesta en marcha (EPC)", 1, "COP", 964_336_128, 5, "servicios"),
    ("Servicios", "Comun", "Capacitacion y gestion del cambio", 1, "COP", 179_252_096, 3, "intangibles"),
    # --- Celda GANTRY de paletizado L1-L2 -- BOM real (36 items, total USD 107,993;
    # ver decision de diseno #6: GRP001 de 4 mordazas aqui es DISTINTO del GRP001 de
    # 3 ventosas de L3 mas abajo -- no consolidar, quedan marcados con su referencia.
    ("Celdas roboticas (BOM real)", "L1-L2", "Servomotor MU 300 (ABB)", 1, "USD*", 2_800, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Servomotor MU 200 (ABB)", 1, "USD*", 2_000, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Controlador IRC5 (ABB) - cotizacion IGAM, envio/logistica incluidos", 1, "USD*", 6_500, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Reductor AB115-005-S2-P2 (Apex Dynamics)", 1, "USD*", 1_100, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Eje lineal Rexroth_CKK280_S2200 (Bosch-Rexroth)", 1, "USD*", 5_500, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Eje lineal Rexroth_CKR280_S4600 (Bosch-Rexroth)", 1, "USD*", 7_500, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Acople ACP001 (Manufacturado)", 1, "USD*", 450, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Perfil de soporte gantry SP001 (Manufacturado)", 2, "USD*", 1_200, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Gripper neumatico GRP001 4 mordazas 40 kg (Manufacturado)", 1, "USD*", 9_000, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Cilindro neumatico DSBC-80-150-PPSA-N3 (Festo)", 8, "USD*", 220, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Valvula antirretorno HGL-3/8-QS-8 (Festo)", 8, "USD*", 55, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Electrovalvula VUVS-L30-B52-D-G38-F8-1B2 (Festo)", 1, "USD*", 220, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Regulador de caudal GRLA-3/8-QS-8-D (Festo)", 8, "USD*", 28, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Sensor de posicion SMAT-8M-U-E-2,5-OE (Festo)", 4, "USD*", 60, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Unidad FRL MS4-LFR-1/4-D6-E-R-M (Festo)", 1, "USD*", 240, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Transportador PM 9710 (Interroll)", 8, "USD*", 5_500, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Sensor de posicion OBR7500-R100-2EP-IO-V31 (Pepper+Fuchs)", 3, "USD*", 220, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Vallado modular ImpactGuard System-H3120-S60-T30 (Satech)", 6, "USD*", 220, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Panel perimetral W300-H2960 (Satech)", 5, "USD*", 420, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Panel perimetral W200-H2960 (Satech)", 1, "USD*", 380, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Panel perimetral W700-H1480 (Satech)", 1, "USD*", 220, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Panel perimetral W800-H1480 (Satech)", 4, "USD*", 240, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Panel perimetral W1000-H1480 (Satech)", 1, "USD*", 260, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Puerta Single Leaf Door ImpactGuard-H3120-S60-T30 (Satech)", 1, "USD*", 750, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Interlock AZM 415-02/02ZPK 24VAC/DC (Satech/Schmerzal)", 1, "USD*", 320, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Cortina optica ADMIRAL AD 1651 (ReeR)", 2, "USD*", 1_100, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Interfaz cortina optica SR ONE M (ReeR)", 2, "USD*", 380, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Torre de senalizacion KS72 Classic RM (Werma)", 2, "USD*", 210, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Parada de emergencia Serie 45-Ø40mm-2NC (EAO)", 1, "USD*", 35, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Parada de emergencia Serie 84-Ø32mm-IP67-M12 (EAO)", 1, "USD*", 70, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Breaker termomagnetico S203-K25 (ABB)", 1, "USD*", 70, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "RCD F204 B-40/0.3 (ABB)", 1, "USD*", 350, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Mini-breaker 1P 1A S201-C1 (ABB)", 8, "USD*", 18, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Gabinete electrico NSYCRN75250 (Schneider Electric)", 1, "USD*", 260, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "Fuente de alimentacion DC CP-E 24/10.0 (ABB)", 1, "USD*", 190, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L1-L2", "HMI CP620 (ABB)", 1, "USD*", 650, 10, "equipos"),
    # --- Celda ROBOT ARTICULADO L3 -- BOM real (24 items, total USD 131,896)
    ("Celdas roboticas (BOM real)", "L3", "Robot ABB para garrafones - cotizacion EUROBOTS, envio/logistica incluidos", 1, "GBP*", 13_500, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Controlador del robot (incluido en paquete EUROBOTS; no duplicar)", 0, "USD*", 22_000, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Transportador PM 9710 (Interroll)", 5, "USD*", 5_500, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Gripper neumatico GRP001 3 ventosas 15.5 kg (Manufacturado)", 1, "USD*", 4_500, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Generador de vacio OVEM-14-L-B-QO-CE-N-1P (Festo)", 3, "USD*", 320, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Acumulador de vacio CRVZS-0.1 (Festo)", 3, "USD*", 45, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Filtro de vacio VAF-PK-6 (Festo)", 3, "USD*", 55, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Unidad FRL MS4-LFR-1/4-D6-C-P-M-AG-BAR-B (Festo)", 1, "USD*", 220, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Vallado modular ImpactGuard System-H3120-S60-T30 (Satech)", 20, "USD*", 220, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Puerta Single Leaf Door ImpactGuard-H3120-S60-T30 (Satech)", 1, "USD*", 750, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Interlock AZM 415-02/02ZPK 24VAC/DC (Satech/Schmerzal)", 1, "USD*", 320, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Cortina optica ADMIRAL AD 1651 (ReeR)", 2, "USD*", 1_100, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Cortina optica ADMIRAL AD 2B (ReeR)", 1, "USD*", 550, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Interfaz cortina optica SR ONE M (ReeR)", 2, "USD*", 380, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Interfaz cortina optica SR ONE (ReeR)", 1, "USD*", 260, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Torre de senalizacion KS72 Classic RM (Werma)", 2, "USD*", 210, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Parada de emergencia Serie 45-Ø40mm-2NC (EAO)", 1, "USD*", 35, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Parada de emergencia Serie 84-Ø32mm-IP67-M12 (EAO)", 1, "USD*", 70, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Breaker termomagnetico S203-K32 (ABB)", 1, "USD*", 75, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "RCD F204 B-40/0.3 (ABB)", 1, "USD*", 350, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Mini-breaker 1P 1A S201-C1 (ABB)", 7, "USD*", 18, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Gabinete electrico NSYCRN75250 (Schneider Electric)", 1, "USD*", 260, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "Fuente de alimentacion DC CP-E 24/10.0 (ABB)", 1, "USD*", 190, 10, "equipos"),
    ("Celdas roboticas (BOM real)", "L3", "HMI CP620 (ABB)", 1, "USD*", 650, 10, "equipos"),
    ("Software", "Comun", "Licencias perpetuas capitalizables (Studio 5000)", 1, "COP", CAPEX_SOFTWARE, 3, "software"),
]
CONTINGENCIA = 0.10

VIDAS = {"equipos": 10, "automatizacion": 7, "servicios": 5,
         "intangibles": 3, "software": 3}


# ------------------------------ overrides desde Sheets (TTL corto, in-proceso)
_TTL_SEG = 60.0
_CACHE: dict[str, tuple[float, object]] = {}


def _cacheado(clave: str, cargar, forzar: bool = False):
    """Cache en memoria del proceso con TTL corto: cada rerun de Streamlit
    puede releer Sheets sin golpear la API en cada widget-interaction, y el
    boton "Refrescar desde Sheets" de la UI puede forzar una lectura fresca
    pasando forzar=True."""
    ahora = time.time()
    if not forzar and clave in _CACHE and ahora - _CACHE[clave][0] < _TTL_SEG:
        return _CACHE[clave][1]
    valor = cargar()
    _CACHE[clave] = (ahora, valor)
    return valor


def _num(valor, default: float) -> float:
    """Castea un valor de celda de Sheets a float. El libro real usa formato
    colombiano (punto = separador de miles, coma = separador decimal:
    "3.850" -> 3850, "18,00%" -> 0.18) via
    `integrations.sheets_client.numero_cop()` -- NO el formato ingles. Ante
    celda vacia o texto no numerico cae al default local — una celda mal
    diligenciada nunca revienta el motor financiero."""
    if valor is None or valor == "":
        return default
    if isinstance(valor, (int, float)):
        return float(valor)
    from integrations.sheets_client import numero_cop
    es_pct = str(valor).strip().endswith("%")
    v = numero_cop(valor, None)
    if v is None:
        return default
    return v / 100 if es_pct else v


_CLAVES_PARAMETROS = {
    "TRM", "GBP_COP", "FACTOR_RFQ", "TMAR_ANUAL", "UPLIFT_THROUGHPUT", "FACTOR_MONETIZACION",
    "RAMPA_MES5", "SCRAP_PP", "MANT_EVITADO_MES", "AHORRO_LABORAL_MES", "TASA_RENTA", "WC_PCT_INGRESO",
    "FASES_CAPEX", "NOMINA_OPERACION_MES",
    "NOMINA_IMPLEMENTACION_MES", "OTROS_FIJOS_BASE_MES", "OTROS_FIJOS_PROYECTO_MES",
    "OPEX_LICENCIAS_MES", "CAPEX_SOFTWARE", "CONTINGENCIA",
} | {f"VIDA_{cat}" for cat in VIDAS} | {
    f"{campo}_{sku}" for campo in ("precio_venta_cop", "costo_material_cop") for sku in SKUS
}

# Alias de las claves REALES del libro (minusculas, en español -- las que
# trae hoy la hoja Parametros, poblada por el generador del repo hermano) a
# las claves canonicas de arriba. Las claves canonicas tambien se aceptan
# directamente (sin distinguir mayusculas/minusculas), para no depender de
# que nadie mantenga este alias sincronizado con el libro a futuro.
_ALIAS_PARAMETROS = {
    "trm_cop_usd": "TRM",
    "gbp_cop": "GBP_COP",
    "factor_rfq_benchmark": "FACTOR_RFQ",
    "tmar_anual": "TMAR_ANUAL",
    "tasa_renta": "TASA_RENTA",
    "uplift_throughput": "UPLIFT_THROUGHPUT",
    "factor_monetizacion": "FACTOR_MONETIZACION",
    "rampa_mes5": "RAMPA_MES5",
    "scrap_pp": "SCRAP_PP",
    "mant_evitado_mes": "MANT_EVITADO_MES",
    "ahorro_laboral_monetizable_mes": "AHORRO_LABORAL_MES",
    "wc_pct_ingreso": "WC_PCT_INGRESO",
    "nomina_operacion_mes": "NOMINA_OPERACION_MES",
    "nomina_implementacion_mes": "NOMINA_IMPLEMENTACION_MES",
    "otros_fijos_base_mes": "OTROS_FIJOS_BASE_MES",
    "otros_fijos_proyecto_mes": "OTROS_FIJOS_PROYECTO_MES",
    "contingencia_capex": "CONTINGENCIA",
    "precio_p1_330ml": "precio_venta_cop_P1-CC350-RGB",
    "precio_p1_350ml": "precio_venta_cop_P1-CC350-RGB",
    "precio_p2_pet15": "precio_venta_cop_P2-QT1500-PET",
    "precio_p3_garrafon": "precio_venta_cop_P3-GARR25L",
}


def _normalizar_overrides(crudo: dict) -> dict:
    """Traduce las claves reales del libro (`_ALIAS_PARAMETROS`) a las
    claves canonicas de `_CLAVES_PARAMETROS`. `fase_capex_1..4` (filas
    separadas en el libro real, una por fase) se combinan en un solo
    'FASES_CAPEX' (cada valor ya pasado por `_num` para evitar comas
    anidadas al unirlas)."""
    crudo = {str(k).strip(): v for k, v in crudo.items() if str(k).strip()}
    out: dict[str, object] = {}
    for k, v in crudo.items():
        canon = _ALIAS_PARAMETROS.get(k.lower()) or (
            k.upper() if k.upper() in _CLAVES_PARAMETROS else None)
        if canon:
            out[canon] = v
    fases_crudo = [crudo.get(f"fase_capex_{i}") for i in range(1, PREOP + 1)]
    if "FASES_CAPEX" not in out and all(f not in (None, "") for f in fases_crudo):
        out["FASES_CAPEX"] = ",".join(str(_num(f, 0.0)) for f in fases_crudo)
    return out


def _overrides_parametros(forzar: bool = False) -> dict:
    def _cargar():
        try:
            from integrations.sheets_client import Contabilidad
            cont = Contabilidad()
            crudo = cont.leer_parametros()
            crudo.update(cont.leer_licencias())  # CAPEX_SOFTWARE / OPEX_LICENCIAS_MES
            return _normalizar_overrides(crudo)
        except Exception:  # noqa: BLE001 — Sheets no disponible: sin overrides
            return {}
    return _cacheado("parametros", _cargar, forzar)


def _overrides_capex(forzar: bool = False) -> list[tuple]:
    def _cargar():
        try:
            from integrations.sheets_client import Contabilidad
            return Contabilidad().leer_capex()
        except Exception:  # noqa: BLE001
            return []
    return _cacheado("capex_filas", _cargar, forzar)


def _parametros(forzar: bool = False) -> dict:
    """Parametros escalares activos: default local salvo que Sheets (hoja
    Parametros) traiga un valor valido para esa clave."""
    ov = _overrides_parametros(forzar)
    fases = FASES_CAPEX
    fases_raw = ov.get("FASES_CAPEX")
    if fases_raw not in (None, ""):
        try:
            partes = [float(x) for x in str(fases_raw).split(",")]
            if len(partes) == PREOP and abs(sum(partes) - 1) < 0.02:
                fases = partes
        except ValueError:
            pass
    return {
        "trm": _num(ov.get("TRM"), TRM),
        "gbp_cop": _num(ov.get("GBP_COP"), GBP_COP),
        "factor_rfq": _num(ov.get("FACTOR_RFQ"), FACTOR_RFQ),
        "tmar_anual": _num(ov.get("TMAR_ANUAL"), TMAR_ANUAL),
        "uplift_throughput": _num(ov.get("UPLIFT_THROUGHPUT"), UPLIFT_THROUGHPUT),
        "factor_monetizacion": _num(ov.get("FACTOR_MONETIZACION"), FACTOR_MONETIZACION),
        "rampa_mes5": _num(ov.get("RAMPA_MES5"), RAMPA_MES5),
        "scrap_pp": _num(ov.get("SCRAP_PP"), SCRAP_PP),
        "mant_evitado_mes": _num(ov.get("MANT_EVITADO_MES"), MANT_EVITADO_MES),
        "ahorro_laboral_mes": _num(ov.get("AHORRO_LABORAL_MES"), AHORRO_LABORAL_MES),
        "tasa_renta": _num(ov.get("TASA_RENTA"), TASA_RENTA),
        "wc_pct_ingreso": _num(ov.get("WC_PCT_INGRESO"), WC_PCT_INGRESO),
        "fases_capex": fases,
        "nomina_operacion_mes": _num(ov.get("NOMINA_OPERACION_MES"), NOMINA_OPERACION_MES),
        "nomina_implementacion_mes": _num(ov.get("NOMINA_IMPLEMENTACION_MES"),
                                          NOMINA_IMPLEMENTACION_MES),
        "otros_fijos_base_mes": _num(ov.get("OTROS_FIJOS_BASE_MES"), OTROS_FIJOS_BASE_MES),
        "otros_fijos_proyecto_mes": _num(ov.get("OTROS_FIJOS_PROYECTO_MES"),
                                         OTROS_FIJOS_PROYECTO_MES),
        "opex_licencias_mes": _num(ov.get("OPEX_LICENCIAS_MES"), OPEX_LICENCIAS_MES),
        "capex_software": _num(ov.get("CAPEX_SOFTWARE"), CAPEX_SOFTWARE),
        "contingencia": _num(ov.get("CONTINGENCIA"), CONTINGENCIA),
        "vidas": {cat: _num(ov.get(f"VIDA_{cat}"), anios) for cat, anios in VIDAS.items()},
    }


def _capex_filas_activas(forzar: bool = False) -> list[tuple]:
    """CAPEX_FILAS activo: la tabla de la hoja 'CAPEX' de Sheets si trae al
    menos una fila valida; si no, el default local de este modulo."""
    filas = _overrides_capex(forzar)
    return filas if filas else CAPEX_FILAS


def _parseable(valor) -> bool:
    """True si _num() lograria castear `valor` a numero (no si cayo al
    default por celda vacia/invalida) — para reportar en la UI solo los
    overrides que de verdad estan gobernando el motor."""
    centinela = object()
    return _num(valor, centinela) is not centinela  # type: ignore[comparison-overlap]


def estado_fuente_financiera(forzar: bool = False) -> dict:
    """Diagnostico para la UI: que tan 'vivo' es el dato ahora mismo — modo de
    Contabilidad (sheets/excel), que claves de Parametros estan efectivamente
    sobreescribiendo el default (parseadas con exito, no solo presentes en la
    hoja), si el CAPEX viene de la hoja CAPEX, y el TTL del cache in-proceso."""
    ov = _overrides_parametros(forzar)
    filas_ov = _overrides_capex(forzar)
    try:
        from integrations.sheets_client import Contabilidad
        modo = Contabilidad().modo
    except Exception:  # noqa: BLE001
        modo = "excel"
    return {
        "modo_contabilidad": modo,
        "parametros_desde_sheets": sorted(k for k in ov if k in _CLAVES_PARAMETROS
                                          and _parseable(ov.get(k))),
        "capex_desde_sheets": bool(filas_ov),
        "n_filas_capex_sheets": len(filas_ov),
        "ttl_seg": _TTL_SEG,
    }


def _cop(fila, p: dict) -> float:
    _, _, _, cant, mon, unit, _, _ = fila
    if mon == "USD":
        return cant * unit * p["trm"] * p["factor_rfq"]
    if mon == "USD*":                      # cotizacion real: sin factor RFQ
        return cant * unit * p["trm"]
    if mon == "GBP*":                      # cotizacion real en libras
        return cant * unit * p["gbp_cop"]
    return cant * unit


def capex(forzar: bool = False, parametros: dict | None = None,
          filas: list[tuple] | None = None) -> dict:
    p = parametros or _parametros(forzar)
    filas = filas if filas is not None else _capex_filas_activas(forzar)
    total_filas = sum(_cop(f, p) for f in filas)
    celdas = sum(_cop(f, p) for f in filas if f[0].startswith("Celdas"))
    por_cat: dict[str, float] = {}
    for f in filas:
        por_cat[f[7]] = por_cat.get(f[7], 0.0) + _cop(f, p)
    return {"subtotal_cop": total_filas, "celdas_roboticas_cop": celdas,
            "contingencia_cop": total_filas * p["contingencia"],
            "total_cop": total_filas * (1 + p["contingencia"]),
            "depreciable_por_categoria": por_cat}


def dep_mensual_total(forzar: bool = False, parametros: dict | None = None) -> float:
    p = parametros or _parametros(forzar)
    cx = capex(forzar, p)["depreciable_por_categoria"]
    return sum(base / (p["vidas"][cat] * 12) for cat, base in cx.items())


def _maestro(forzar: bool = False) -> pd.DataFrame:
    """Unit economics por SKU; Sheets es la fuente operativa viva.

    El CSV solo existe como semilla/fallback cuando EXTERNAL_ONLY esta apagado.
    """
    ov = _overrides_parametros(forzar)
    if settings.EXTERNAL_ONLY:
        from integrations.sheets_client import Contabilidad
        df = Contabilidad().leer_maestro_productos().set_index("sku")
        faltan = [s for s in SKUS if s not in df.index]
        if faltan:
            raise RuntimeError("EXTERNAL_ONLY=true: faltan SKU en Maestro_Productos "
                               f"de Sheets: {', '.join(faltan)}")
        return df
    df = pd.read_csv(settings.DATA_DIR / "maestro_productos.csv").set_index("sku")
    for s in SKUS:
        if s not in df.index:
            continue
        df.loc[s, "precio_venta_cop"] = _num(ov.get(f"precio_venta_cop_{s}"),
                                             float(df.loc[s, "precio_venta_cop"]))
        df.loc[s, "costo_material_cop"] = _num(ov.get(f"costo_material_cop_{s}"),
                                               float(df.loc[s, "costo_material_cop"]))
    return df


def _demanda_base() -> pd.DataFrame:
    if settings.EXTERNAL_ONLY:
        from integrations.sheets_client import Contabilidad
        df = Contabilidad().leer_demanda()
        if df.empty:
            raise RuntimeError("EXTERNAL_ONLY=true: hoja Demanda vacia")
        return df
    csv = settings.DATA_DIR / "pronostico_base_mensual.csv"
    if csv.exists():
        return pd.read_csv(csv)
    from core.forecast import pronostico_base
    return pronostico_base().mensual


def flujos_desde_demanda(demanda_mensual: pd.DataFrame | None = None,
                         forzar_refresco: bool = False) -> dict:
    dem12 = (demanda_mensual if demanda_mensual is not None
             else _demanda_base()).reset_index(drop=True)
    p = _parametros(forzar_refresco)
    ma = _maestro(forzar_refresco)
    precio = {s: float(ma.loc[s, "precio_venta_cop"]) for s in SKUS}
    costo = {s: float(ma.loc[s, "costo_material_cop"]) for s in SKUS}
    cx = capex(forzar_refresco, p)
    dep_mes = dep_mensual_total(forzar_refresco, p)

    # Sin supuesto de crecimiento interanual: el patron de 12 meses que
    # manda el ERP (pronostico o escenario activo) se repite tal cual en
    # los 5 anios del horizonte -- pedido explicito del dueno del proyecto,
    # la evaluacion financiera sigue SIEMPRE la demanda del ERP, sin
    # inflarla con una tasa de crecimiento aparte.
    ingreso_b = np.zeros(MESES); cogs_b = np.zeros(MESES); u = np.zeros(MESES)
    for m in range(1, MESES + 1):
        fila = dem12.iloc[(m - 1) % 12]
        for s in SKUS:
            q = float(fila[f"{s}_unidades"])
            u[m - 1] += q
            ingreso_b[m - 1] += q * precio[s]
            cogs_b[m - 1] += q * costo[s]

    rampa = np.zeros(MESES)
    rampa[PREOP] = p["rampa_mes5"]
    rampa[PREOP + 1:] = 1.0
    factor_v = 1 + rampa * p["uplift_throughput"] * p["factor_monetizacion"]
    ingreso_p, cogs_p = ingreso_b * factor_v, cogs_b * factor_v

    op = np.arange(1, MESES + 1) > PREOP
    ebitda_b = (ingreso_b - cogs_b - p["nomina_operacion_mes"] - p["otros_fijos_base_mes"])
    ahorro_scrap = cogs_p * p["scrap_pp"] * rampa
    ebitda_p = (ingreso_p - cogs_p - p["nomina_operacion_mes"]
                - np.where(op, p["otros_fijos_proyecto_mes"], p["otros_fijos_base_mes"])
                - p["opex_licencias_mes"] + ahorro_scrap
                + p["mant_evitado_mes"] * rampa
                + p["ahorro_laboral_mes"] * rampa)
    ebitda_inc = ebitda_p - ebitda_b

    dep = np.where(op, dep_mes, 0.0)
    impuesto = p["tasa_renta"] * np.maximum(ebitda_inc - dep, 0.0)
    fcf = ebitda_inc - impuesto
    fcf[:PREOP] = (-cx["total_cop"] * np.array(p["fases_capex"])
                   - p["nomina_implementacion_mes"] - p["opex_licencias_mes"])
    wc = p["wc_pct_ingreso"] * float((ingreso_p - ingreso_b)[PREOP + 1])
    fcf[PREOP] -= wc
    fcf[-1] += wc

    return {"fcf": fcf, "ebitda_incremental": ebitda_inc,
            "ebitda_base": ebitda_b, "ebitda_proyecto": ebitda_p,
            "ingreso_base": ingreso_b, "ingreso_proyecto": ingreso_p,
            "cogs_base": cogs_b, "cogs_proyecto": cogs_p,
            "ahorro_scrap": ahorro_scrap,
            "ahorro_laboral": p["ahorro_laboral_mes"] * rampa,
            "depreciacion": dep,
            "impuesto": impuesto, "capital_trabajo": wc, "capex": cx,
            "unidades": u, "dep_mensual": dep_mes, "parametros": p}


def _tir_mensual(flujos: np.ndarray) -> float:
    lo, hi = -0.5, 1.0
    def vpn(r):
        return float(np.sum(flujos / (1 + r) ** np.arange(1, len(flujos) + 1)))
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if vpn(mid) > 0 else (lo, mid)
    return (lo + hi) / 2


def indicadores(demanda_mensual: pd.DataFrame | None = None,
                escenario: str = "Base", forzar_refresco: bool = False) -> dict:
    d = flujos_desde_demanda(demanda_mensual, forzar_refresco)
    p = d["parametros"]
    tmar_mensual = (1 + p["tmar_anual"]) ** (1 / 12) - 1
    f = d["fcf"]
    t = np.arange(1, MESES + 1)
    desc = f / (1 + tmar_mensual) ** t
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
            "dep_mensual_cop": d["dep_mensual"], "tmar_anual": p["tmar_anual"],
            "delta_vs_modelo_original": {
                "vpn_pct": round((vpn / REF_XLSM["vpn"] - 1) * 100, 1),
                "nota": "referencia: xlsm (flujo agregado no ligado a demanda)"},
            "flujos": f, "flujos_descontados": desc,
            "acumulado_descontado": acum_desc, "detalle": d}


def sensibilidad(demanda_mensual: pd.DataFrame | None = None,
                 forzar_refresco: bool = False) -> pd.DataFrame:
    """Tres escenarios de la base financiera: factores sobre EBITDA inc./CAPEX
    y TMAR distinta (mismos del xlsm: Conservador/Base/Optimista). Los
    factores de sensibilidad son de analisis (no se leen de Sheets); el CAPEX,
    nomina y licencias de base si respetan los overrides activos."""
    d = flujos_desde_demanda(demanda_mensual, forzar_refresco)
    p = d["parametros"]
    casos = [("Conservador", 0.95, 1.15, 0.20), ("Base", 1.00, 1.00, 0.18),
             ("Optimista", 1.05, 0.90, 0.16)]
    filas = []
    for nombre, f_v, f_cx, tmar in casos:
        ebitda = d["ebitda_incremental"] * f_v
        dep = d["depreciacion"]
        imp = p["tasa_renta"] * np.maximum(ebitda - dep, 0.0)
        f = ebitda - imp
        f[:PREOP] = (-d["capex"]["total_cop"] * f_cx * np.array(p["fases_capex"])
                     - p["nomina_implementacion_mes"] - p["opex_licencias_mes"])
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
    print(f"Fuente parametros: {estado_fuente_financiera()}")
    print("\nSensibilidad:")
    print(sensibilidad().to_string(index=False))
