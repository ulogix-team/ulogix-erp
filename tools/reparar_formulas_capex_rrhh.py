"""
Repara las formulas del libro que quedaron rotas por dos cambios recientes:
1. La expansion del CAPEX a 84 filas (celdas roboticas a detalle de BOM
   real, decision #15 de CLAUDE.md) y la reorganizacion en bloques por area
   (decision #17) corrieron todas las filas debajo de la original -- las
   formulas de Reportes/Sensibilidad/Flujo_Caja/FinancieroEscenario que
   apuntaban a la celda FIJA `CAPEX!$G$34` (el total viejo) quedaron
   apuntando a una celda equivocada. El SUMIF de Dep_Amort
   (`CAPEX!$I$5:$I$29`) quedo demasiado angosto y dejo de contar la mayoria
   de las filas (silencioso: no da error, solo cuenta de menos).
2. La consolidacion de `Personal` + `Empleados` en la hoja `RRHH` (decision
   #17) borro la hoja `Personal` -- las formulas que apuntaban a
   `Personal!$D$10` (nomina OPERACION) y `Personal!$D$11` (nomina
   IMPLEMENTACION) quedaron con referencia a una hoja que ya no existe.
   Verificado el mapeo real antes de reparar (no es simetrico ni obvio):
   ER_Proyecto fila 12 "Nomina operacion" usaba D10; Flujo_Caja fila 9
   "(-) Equipo implementacion ULogix" usaba D11.

En vez de apuntar a celdas fijas (fragil: CAPEX se sigue editando en precios
y filas, va a seguir cambiando de tamano), esta reparacion usa formulas
INDEX/MATCH por ETIQUETA DE TEXTO -- sobreviven a que la fila se mueva,
mientras la etiqueta ("CAPEX TOTAL (con contingencia)", "Costo mensual
OPERACION (-> ER)", "Costo mensual IMPLEMENTACION (-> pre-op)") no cambie.

Eficiente en llamadas a la API (una lectura + una escritura por hoja, para
no pegarle al limite de "requests por minuto" de Sheets).

Uso: python tools/reparar_formulas_capex_rrhh.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.sheets_client import Contabilidad

CAPEX_TOTAL_FORMULA = ('INDEX(CAPEX!$G:$G;MATCH("CAPEX TOTAL (con contingencia)";'
                       'CAPEX!$C:$C;0))')
RRHH_OPERACION_FORMULA = ('INDEX(RRHH!$E:$E;MATCH("Costo mensual OPERACION (→ ER)";'
                          'RRHH!$A:$A;0))')
RRHH_IMPLEMENTACION_FORMULA = ('INDEX(RRHH!$E:$E;MATCH("Costo mensual IMPLEMENTACION '
                               '(→ pre-op)";RRHH!$A:$A;0))')

REEMPLAZOS = [
    ("CAPEX!$G$34", CAPEX_TOTAL_FORMULA),
    ("CAPEX!G34", CAPEX_TOTAL_FORMULA),               # variante sin anclas ($), vista en Reportes
    ("Personal!$D$10", RRHH_OPERACION_FORMULA),        # nomina OPERACION (ER_Proyecto fila 12)
    ("Personal!$D$11", RRHH_IMPLEMENTACION_FORMULA),   # nomina IMPLEMENTACION (Flujo_Caja fila 9)
]


def _col_letra(n: int) -> str:
    letras = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        letras = chr(65 + r) + letras
    return letras


def _reparar_hoja(ws, filas_min1: list[int], col_min: int, col_max: int) -> int:
    """Lee TODA la hoja como formulas de una vez, repara las filas indicadas
    dentro de [col_min, col_max] (1-based, inclusive), y escribe cada fila
    reparada en UNA sola llamada (rango contiguo)."""
    grid = ws.get(value_render_option="FORMULA")
    tocadas = 0
    for fila1 in filas_min1:
        idx0 = fila1 - 1
        if idx0 >= len(grid):
            continue
        fila = grid[idx0]
        nueva_fila = []
        cambio = False
        for c in range(col_min, col_max + 1):
            j = c - 1
            val = fila[j] if j < len(fila) else ""
            if isinstance(val, str) and val.startswith("="):
                nuevo = val
                for viejo, reemplazo in REEMPLAZOS:
                    nuevo = nuevo.replace(viejo, reemplazo)
                if nuevo != val:
                    cambio = True
                nueva_fila.append(nuevo)
            else:
                nueva_fila.append(val)
        if cambio:
            rango = f"{_col_letra(col_min)}{fila1}:{_col_letra(col_max)}{fila1}"
            ws.update([nueva_fila], rango, value_input_option="USER_ENTERED")
            tocadas += 1
            print(f"  {ws.title}!{rango} actualizada")
            time.sleep(1.1)  # respeta el limite de requests/min de Sheets
    return tocadas


def main() -> None:
    cont = Contabilidad()
    if cont.modo != "sheets":
        raise SystemExit("Sheets no esta configurado (.env).")
    ss = cont._spreadsheet()
    total = 0

    print("Reportes:")
    total += _reparar_hoja(ss.worksheet("Reportes"), [14], 2, 2)
    time.sleep(1.1)

    print("\nER_Proyecto (fila 12):")
    total += _reparar_hoja(ss.worksheet("ER_Proyecto"), [12], 2, 61)
    time.sleep(1.1)

    print("\nFlujo_Caja (filas 8 y 9):")
    total += _reparar_hoja(ss.worksheet("Flujo_Caja"), [8, 9], 2, 5)
    time.sleep(1.1)

    print("\nFinancieroEscenario (fila 14):")
    total += _reparar_hoja(ss.worksheet("FinancieroEscenario"), [14], 2, 5)
    time.sleep(1.1)

    print("\nSensibilidad (filas 10, 15, 20):")
    total += _reparar_hoja(ss.worksheet("Sensibilidad"), [10, 15, 20], 2, 5)
    time.sleep(1.1)

    print("\nDep_Amort (amplia el rango del SUMIF a 300 filas, cubre CAPEX actual y futuro):")
    ws = ss.worksheet("Dep_Amort")
    categorias = ["equipos", "automatizacion", "servicios", "intangibles", "software"]
    formulas = [[f'=SUMIF(CAPEX!$I$5:$I$300;"{cat}";CAPEX!$G$5:$G$300)'] for cat in categorias]
    ws.update(formulas, "B5:B9", value_input_option="USER_ENTERED")
    for cat, f in zip(categorias, formulas):
        print(f"  Dep_Amort!B.. ({cat}): {f[0]}")
    total += len(categorias)

    print(f"\n{total} filas/celdas reparadas.")


if __name__ == "__main__":
    main()
