"""Publica alcance 2026-07: divisas, proveedores, viabilidad y formulas financieras.

No crea ordenes de compra en Odoo. Actualiza el libro que gobierna el ERP y
deja cotizaciones/benchmarks trazables; cualquier adjudicacion exige RFQ.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.sheets_client import Contabilidad

TRM = 3248.87
GBP_COP = 4437.0


def _asegurar_parametro(ws, clave, valor, unidad, nota) -> int:
    vals = ws.get_all_values()
    for i, row in enumerate(vals, 1):
        if row and row[0].strip().lower() == clave.lower():
            ws.update([[valor, unidad, nota]], f"B{i}:D{i}", value_input_option="USER_ENTERED")
            return i
    fila = max(len(vals) + 1, 5)
    ws.update([[clave, valor, unidad, nota]], f"A{fila}:D{fila}",
              value_input_option="USER_ENTERED")
    return fila


def actualizar_parametros(ss) -> None:
    ws = ss.worksheet("Parametros")
    _asegurar_parametro(ws, "trm_cop_usd", TRM, "COP/USD",
                        "Superfinanciera; vigencia 11-14 jul-2026")
    _asegurar_parametro(ws, "gbp_cop", GBP_COP, "COP/GBP",
                        "Referencia de mercado jul-2026 para cotizacion EUROBOTS")
    _asegurar_parametro(ws, "fte_manual_equivalente", 10, "FTE",
                        "L1: 6 (encajonado+paletizado, 2 turnos); L2: 2; L3: 2")
    fila_pct = _asegurar_parametro(ws, "pct_monetizacion_ahorro_laboral", 0.70, "%",
                                   "Conservador: reconoce reasignacion; editable")
    formula = (f'=INDEX(Viabilidad_Automatizacion!$B:$B;MATCH('
               f'"Ahorro laboral bruto mensual";Viabilidad_Automatizacion!$A:$A;0))*B{fila_pct}')
    _asegurar_parametro(ws, "ahorro_laboral_monetizable_mes", formula, "COP/mes",
                        "Formula viva: costo FTE RRHH x FTE equivalentes x monetizacion")


def publicar_proveedores(ss) -> None:
    filas = [
        ["PROVEEDORES Y FUENTES DEL CAPEX — registro de procura", "", "", "", "", "", "", "", "", ""],
        ["Los valores 'cotizacion usuario' incluyen la logistica indicada. Los benchmarks usados requieren inspeccion, RFQ y validacion de formato/voltaje antes de adjudicar.", "", "", "", "", "", "", "", "", ""],
        [],
        ["linea", "equipo / alcance", "proveedor", "tipo_fuente", "valor", "moneda",
         "logistica", "capacidad / criterio", "url / referencia", "estado"],
        ["L3", "Robot ABB celda garrafones", "EUROBOTS", "Cotizacion informada por propietario",
         13500, "GBP", "Envio y logistica incluidos", "Llenadora existente 600 gfn/h; robot elimina cuello manual",
         "Cotizacion directa; solicitar PDF y seriales", "Seleccionado / validar alcance del controlador"],
        ["L1-L2", "Controlador ABB IRC5 GANTRY compartido", "IGAM", "Cotizacion informada por propietario",
         6500, "USD", "Envio y logistica incluidos", "Un controlador para celda compartida y alternada L1/L2",
         "Cotizacion directa; solicitar PDF", "Seleccionado"],
        ["L2", "KRONES Variopac 459 usada", "Machinio / vendedor Chicago", "Listado publico usado",
         79900, "USD", "No confirmada", "28-30 paquetes/min; formatos hasta 1,5 L",
         "https://www.machinio.com/cat/variopac", "Benchmark con precio; RFQ pendiente"],
        ["L2", "KRONES Variopac Pro TFS-4-DS 2021", "MachinePoint", "Listado publico usado",
         "Precio a consultar", "USD/EUR", "Servicios de transporte disponibles", "45 paquetes/min; 1.200 h",
         "https://www.machinepoint.com/machinepoint/inventory.nsf/idmaquina/300047107?ln=es&opendocument=", "Alternativa RFQ"],
        ["L1", "KRONES VODM usada 2012", "MachinePoint", "Listado publico usado",
         "Precio a consultar", "EUR", "No confirmada", "44.000 bph; cumple demanda con holgura",
         "https://www.machinepoint.com/machinepoint/inventory.nsf/idmaquina/300049529?ln=en&opendocument=", "Alternativa RFQ / inspeccion"],
        ["L1", "KRONES glass line 4.000 L/h (1997)", "Truck1 / vendedor italiano", "Listado publico usado",
         138000, "EUR", "No confirmada", "≈11.429 bph a 350 ml: NO cumple capacidad L1",
         "https://www.truck1.eu/industrial-equipment/liquid-filling-machines/used-krones-filling-line-for-flat-drinks-in-glass-a11361978.html", "Descartado por capacidad"],
        ["L1", "KRONES CSD vidrio 36.000 bph usada 2012", "Used German Machines", "Listado publico usado",
         "Precio a consultar", "EUR", "No confirmada", "36.000 bph: menor holgura que alternativa 44.000",
         "https://used-german-machines.de/machines/99922681", "Alternativa condicionada"],
        ["L2", "KRONES PET CSD usada 18.000 bph", "Used Bottling Lines / Exapro", "Listado publico usado",
         "Precio a consultar", "EUR/USD", "No confirmada", "18.000 bph a 1,5 L; amplia holgura",
         "https://www.exapro.com/krones-ultra-clean-pet-p260108037/", "Base tecnica; RFQ pendiente"],
        ["Comun", "Sensores, neumatica, seguridad y tableros", "ABB / Festo / ReeR / Satech / Interroll", "Fabricantes BOM",
         "Ver CAPEX", "USD", "Segun RFQ", "Referencias detalladas en BOM de celdas",
         "Hojas CAPEX y APU_Ingenieria", "RFQ por paquete"],
        ["Digital", "Ignition SCADA / MES / Coreflux UNS / Siemens / ABB RobotStudio", "Inductive Automation / Coreflux / Siemens / ABB", "Fabricante / alcance ULogix",
         "Ver Licencias y APU", "COP/USD", "Digital", "SCADA, MES, MQTT, simulacion y gemelos digitales",
         "Hojas Licencias y APU_Ingenieria", "Incluido en arquitectura"],
    ]
    try:
        ws = ss.worksheet("Proveedores_CAPEX")
    except Exception:
        ws = ss.add_worksheet("Proveedores_CAPEX", rows=100, cols=12)
    ws.clear(); ws.update(filas, "A1", value_input_option="USER_ENTERED")
    ws.freeze(rows=4)
    ws.format("B5:B100", {"numberFormat": {"type": "TEXT"}})
    ws.format("E5:E100", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}})


def publicar_viabilidad(ss) -> None:
    filas = [
        ["VIABILIDAD ECONOMICA DE AUTOMATIZACION — ANTES vs ULOGIX vs MERCADO", "", "", "", "", ""],
        ["Se monetiza 70% del ahorro laboral equivalente para reconocer reasignacion. El porcentaje se edita en Parametros; no supone despidos automaticos.", "", "", "", "", ""],
        [],
        ["Concepto", "Valor", "Unidad", "L1", "L2", "L3"],
        ["Costo unitario mensual operador", '=INDEX(RRHH!$G:$G;MATCH("Operarios de linea (3 turnos)";RRHH!$A:$A;0))', "COP/FTE-mes", "", "", ""],
        ["FTE manual paletizado", "=SUM(D6:F6)", "FTE", 2, 2, 2],
        ["FTE manual encajonado", "=SUM(D7:F7)", "FTE", 4, 0, 0],
        ["FTE manual equivalente", "=SUM(B6:B7)", "FTE", "=D6+D7", "=E6+E7", "=F6+F7"],
        ["Costo manual mensual por linea", "=SUM(D9:F9)", "COP/mes", "=D8*$B$5", "=E8*$B$5", "=F8*$B$5"],
        ["Costo manual anual", "=B9*12", "COP/año", "=D9*12", "=E9*12", "=F9*12"],
        [],
        ["Ahorro laboral bruto mensual", "=B9", "COP/mes", "", "", ""],
        ["Porcentaje monetizable", '=INDEX(Parametros!$B:$B;MATCH("pct_monetizacion_ahorro_laboral";Parametros!$A:$A;0))', "%", "", "", ""],
        ["Ahorro laboral monetizable mensual", "=B12*B13", "COP/mes", "", "", ""],
        ["Ahorro laboral monetizable anual", "=B14*12", "COP/año", "", "", ""],
        [],
        ["CAPEX automatizacion ULogix", '=SUMIF(CAPEX!$A:$A;"Celdas roboticas (BOM real)";CAPEX!$G:$G)+SUMIF(CAPEX!$A:$A;"Diseño ULogix";CAPEX!$G:$G)', "COP", "", "", ""],
        ["Mantenimiento anual ULogix", "=B17*3%", "COP/año", "", "", ""],
        ["Ahorro neto anual ULogix", "=B15-B18", "COP/año", "", "", ""],
        ["Payback simple ULogix", "=B17/B19", "años", "", "", ""],
        ["VPN ULogix 10 años", "=NPV(Parametros!$B$7;B19;B19;B19;B19;B19;B19;B19;B19;B19;B19)-B17", "COP", "", "", ""],
        [],
        ["CAPEX mercado equivalente", '=INDEX(Parametros!$B:$B;MATCH("trm_cop_usd";Parametros!$A:$A;0))*(400000+180000+140000)', "COP", "", "", ""],
        ["Nota mercado", "Paletizadora+encajonadora L1, paletizadora L2 y robot L3 independientes; no comparten GANTRY", "", "", "", ""],
        ["Conclusión", '=IF(B21>0;"ULogix es viable por ahorro laboral aun sin contar uplift/OEE";"Revisar monetizacion y RFQ")', "", "", "", ""],
    ]
    try:
        ws = ss.worksheet("Viabilidad_Automatizacion")
    except Exception:
        ws = ss.add_worksheet("Viabilidad_Automatizacion", rows=100, cols=8)
    ws.clear(); ws.update(filas, "A1", value_input_option="USER_ENTERED")
    ws.freeze(rows=4)
    ws.format("B5:B23", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}})
    ws.format("B13", {"numberFormat": {"type": "PERCENT", "pattern": "0%"}})
    for rango in ("B5", "B9:B10", "B12", "B14:B19", "B21", "B23"):
        ws.format(rango, {"numberFormat": {"type": "CURRENCY", "pattern": "$#,##0"}})
    ws.format("B20", {"numberFormat": {"type": "NUMBER", "pattern": "0.00"}})
    try:
        legado = ss.worksheet("Analisis_Paletizado")
        legado.clear()
        legado.update([
            ["ANALISIS DE PALETIZADO — MIGRADO"],
            ["La evaluacion vigente esta en Viabilidad_Automatizacion y ya alimenta el modelo principal."],
            ["Motivo", "El analisis anterior era paralelo y contenia CAPEX previos a las cotizaciones EUROBOTS/IGAM."],
        ], "A1", value_input_option="USER_ENTERED")
    except Exception:
        pass


def integrar_formulas(ss) -> None:
    p = ('INDEX(Parametros!$B:$B;MATCH("ahorro_laboral_monetizable_mes";'
         'Parametros!$A:$A;0))')
    er = ss.worksheet("ER_Proyecto")
    formulas = er.get("B23:BI23", value_render_option="FORMULA")[0]
    meses = er.get("B4:BI4", value_render_option="UNFORMATTED_VALUE")[0]
    nuevas = []
    for col, formula in zip(meses, formulas):
        if "+INDEX(Parametros!$B:$B" not in str(formula):
            rampa = f'IF({col}<=4;0;IF({col}=5;Parametros!$B$13;1))'
            formula = f"={str(formula).lstrip('=')}+{p}*{rampa}"
        nuevas.append(formula)
    er.update([nuevas], "B23:BI23", value_input_option="USER_ENTERED")
    er.update([["Proyecto incluye ahorro laboral monetizable vinculado a Viabilidad_Automatizacion/Parametros; porcentaje editable y conservador."]],
              "A2", value_input_option="USER_ENTERED")

    fe = ss.worksheet("FinancieroEscenario")
    formulas = fe.get("B11:BI11", value_render_option="FORMULA")[0]
    meses = fe.get("B5:BI5", value_render_option="UNFORMATTED_VALUE")[0]
    nuevas = []
    for mes, formula in zip(meses, formulas):
        if "+INDEX(Parametros!$B:$B" not in str(formula):
            rampa = f'IF({mes}<=4;0;IF({mes}=5;Parametros!$B$13;1))'
            formula = f"={str(formula).lstrip('=')}+{p}*{rampa}"
        nuevas.append(formula)
    fe.update([nuevas], "B11:BI11", value_input_option="USER_ENTERED")


def main() -> None:
    cont = Contabilidad()
    if cont.modo != "sheets":
        raise SystemExit("Sheets no configurado")
    ss = cont._spreadsheet()
    publicar_viabilidad(ss)
    actualizar_parametros(ss)
    publicar_proveedores(ss)
    integrar_formulas(ss)
    print("Parametros, Proveedores_CAPEX, Viabilidad_Automatizacion y formulas actualizados.")


if __name__ == "__main__":
    main()
