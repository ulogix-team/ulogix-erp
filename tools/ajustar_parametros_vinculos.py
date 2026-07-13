"""
Ajusta la hoja 'Parametros' para: (1) neutralizar el crecimiento de demanda
interanual en TODO el modelo -- pedido explicito del dueno del proyecto
("quiero que se siga la demanda que mande el ERP siempre, sin ese
crecimiento") -- y (2) vincular con formula viva las celdas que hoy son
copias estaticas de un valor que en realidad vive en otra hoja (nomina
operacion/implementacion, que ahora vive en RRHH).

(1) crecimiento_demanda (Parametros!B10): la formula `(1+Parametros!$B$10)^N`
    esta usada ~900 veces en ER_Proyecto/FinancieroEscenario (el modelo
    NATIVO de Sheets, independiente del motor Python core.finanzas_negocio,
    que ya se ajusto por separado). En vez de tocar 900 formulas, se
    neutraliza en la RAIZ: B10 -> 0 (con B10=0, (1+0)^N=1 para cualquier N,
    osea deja de crecer sin romper ninguna formula que lo referencia).
    El motor Python (core/finanzas_negocio.py) tambien elimino por completo
    su parametro equivalente CRECIMIENTO_DEMANDA_ANUAL (ya no se lee ni de
    Sheets ni del default local).

(2) nomina_operacion_mes / nomina_implementacion_mes (B23/B24): eran
    copias estaticas de la vieja hoja 'Personal' (ya no existe, consolidada
    en 'RRHH', ver decision #17 de CLAUDE.md) -- pasan a ser formula viva
    (INDEX/MATCH por etiqueta, robusto a que RRHH cambie de tamano si se
    agregan/quitan roles) apuntando a RRHH.

Uso: python tools/ajustar_parametros_vinculos.py
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.sheets_client import Contabilidad

FORMULA_OPERACION = ('=INDEX(RRHH!$E:$E;MATCH("Costo mensual OPERACION (→ ER)";'
                     'RRHH!$A:$A;0))')
FORMULA_IMPLEMENTACION = ('=INDEX(RRHH!$E:$E;MATCH("Costo mensual IMPLEMENTACION '
                          '(→ pre-op)";RRHH!$A:$A;0))')


def main() -> None:
    cont = Contabilidad()
    if cont.modo != "sheets":
        raise SystemExit("Sheets no esta configurado (.env).")
    ss = cont._spreadsheet()
    ws = ss.worksheet("Parametros")

    cambios = [
        # fila, valor(B), nota(D)
        (10, 0, "YA NO SE APLICA -- pedido explicito del dueno del proyecto: la "
               "evaluacion financiera sigue SIEMPRE la demanda que manda el ERP "
               "(pronostico/escenario activo), sin inflarla con una tasa de "
               "crecimiento interanual aparte. Fila conservada para registro "
               "(antes 1,50% aplicado a meses 13-60 via (1+B10)^N en ER_Proyecto/"
               "FinancieroEscenario)."),
        (32, None, "Fase 1: OEE por linea x 1.05 (hoja Tiempos, bloque 'MEJORA DE OEE "
                  "A IMPLEMENTAR') -- documental, ver core/tiempos_oee.py "
                  "(data/parametros_planta.json es la fuente real que usa el ERP, "
                  "decision #1 de CLAUDE.md: OEE/TEEP no se gobierna desde Sheets)."),
    ]
    for fila, valor, nota in cambios:
        if valor is not None:
            ws.update([[valor]], f"B{fila}", value_input_option="USER_ENTERED")
        ws.update([[nota]], f"D{fila}", value_input_option="RAW")
        print(f"Parametros!fila{fila}: actualizado ({'valor+nota' if valor is not None else 'solo nota'})")

    ws.update([[FORMULA_OPERACION]], "B23", value_input_option="USER_ENTERED")
    ws.update([["RRHH (resumen por rol, en vivo -- ya no 'Personal', consolidada)"]],
             "D23", value_input_option="RAW")
    print("Parametros!B23 (nomina_operacion_mes): ahora formula -> RRHH")

    ws.update([[FORMULA_IMPLEMENTACION]], "B24", value_input_option="USER_ENTERED")
    ws.update([["RRHH (resumen por rol, en vivo -- ya no 'Personal', consolidada)"]],
             "D24", value_input_option="RAW")
    print("Parametros!B24 (nomina_implementacion_mes): ahora formula -> RRHH")

    # verificacion
    for a1, etiqueta in [("B10", "crecimiento_demanda"), ("B23", "nomina_operacion_mes"),
                         ("B24", "nomina_implementacion_mes")]:
        val = ws.acell(a1, value_render_option="FORMATTED_VALUE").value
        print(f"  verificacion {etiqueta} ({a1}) = {val}")


if __name__ == "__main__":
    main()
