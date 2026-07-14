"""
Convierte la columna 'CAPEX COP' (G) de la hoja CAPEX de VALORES ESTATICOS
(mezcla de numeros y texto formateado como moneda -- por eso el SUMIF de
Dep_Amort contaba de menos, en silencio) a FORMULAS VIVAS: cada fila de
datos calcula su propio COP desde cantidad x costo_unitario x el factor de
moneda correspondiente (COP directo / USD x TRM x RFQ / USD* x TRM sin
RFQ), leyendo TRM/FACTOR_RFQ/CONTINGENCIA de la hoja Parametros en vivo. Los
subtotales por bloque (decision #17) y el pie (Subtotal/Contingencia/Total)
tambien pasan a ser SUMA en vivo sobre las filas de datos, no numeros
pegados por un script.

Asi, si el usuario cambia una cantidad o un costo_unitario en CAPEX, o el
TRM/RFQ/contingencia en Parametros, TODO el libro (Dep_Amort, Sensibilidad,
Flujo_Caja, FinancieroEscenario, Reportes, ER_Proyecto -- todos reparados en
tools/reparar_formulas_capex_rrhh.py) recalcula solo, sin correr ningun
script de Python.

Uso: python tools/convertir_capex_formulas.py
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.sheets_client import Contabilidad

TRM_CELL = "Parametros!$B$5"
RFQ_CELL = "Parametros!$B$6"
CONTINGENCIA_CELL = "Parametros!$B$27"
GBP_COP_CELL = 'INDEX(Parametros!$B:$B;MATCH("gbp_cop";Parametros!$A:$A;0))'


def _formula_fila(fila: int) -> str:
    """D=cantidad, E=moneda, F=costo_unitario, G=CAPEX COP (esta celda)."""
    return (f'=IF($E{fila}="COP";$D{fila}*$F{fila};'
           f'IF($E{fila}="USD*";$D{fila}*$F{fila}*{TRM_CELL};'
           f'IF($E{fila}="GBP*";$D{fila}*$F{fila}*{GBP_COP_CELL};'
           f'$D{fila}*$F{fila}*{TRM_CELL}*{RFQ_CELL})))')


def main() -> None:
    cont = Contabilidad()
    if cont.modo != "sheets":
        raise SystemExit("Sheets no esta configurado (.env).")
    ss = cont._spreadsheet()
    ws = ss.worksheet("CAPEX")
    vals = ws.get_all_values()

    idx_header = next(i for i, r in enumerate(vals) if r and r[0].strip().lower() == "seccion")

    # identifica filas de datos (seccion no vacia), filas de subtotal por
    # bloque ('Subtotal — ...' en columna C) y el pie (Subtotal CAPEX /
    # Contingencia / CAPEX TOTAL)
    filas_datos: list[int] = []       # 1-based
    filas_subtotal_bloque: list[tuple[int, int, int]] = []  # (fila, inicio, fin) 1-based
    fila_subtotal_general = fila_contingencia = fila_total = None

    bloque_actual_inicio = None
    for i in range(idx_header + 1, len(vals)):
        fila1 = i + 1
        row = vals[i]
        seccion = row[0].strip() if row else ""
        col_c = row[2].strip() if len(row) > 2 else ""
        if seccion:
            filas_datos.append(fila1)
            if bloque_actual_inicio is None:
                bloque_actual_inicio = fila1
        elif col_c.startswith("Subtotal —"):
            if bloque_actual_inicio is not None:
                filas_subtotal_bloque.append((fila1, bloque_actual_inicio, fila1 - 1))
            bloque_actual_inicio = None
        elif col_c == "Subtotal CAPEX":
            fila_subtotal_general = fila1
        elif col_c == "Contingencia":
            fila_contingencia = fila1
        elif col_c == "CAPEX TOTAL (con contingencia)":
            fila_total = fila1

    print(f"{len(filas_datos)} filas de datos, {len(filas_subtotal_bloque)} subtotales de "
         f"bloque, pie en filas {fila_subtotal_general}/{fila_contingencia}/{fila_total}")

    # La hoja viva gobierna cantidades, costos y orden de filas. No se debe
    # volver a escribir F desde CAPEX_FILAS: despues de agrupar por L1/L2/L3
    # el orden visual ya no coincide con el seed local y hacerlo corromperia
    # costos o formulas (APU y Licencias). Este script solo reconstruye G.

    # construye la columna G completa (desde la primera fila de datos hasta
    # el pie) en un solo arreglo, para escribirla en UNA sola llamada
    primera = min(filas_datos)
    ultima = fila_total
    columna_g: list[list[str]] = []
    for fila1 in range(primera, ultima + 1):
        if fila1 in filas_datos:
            columna_g.append([_formula_fila(fila1)])
        elif any(fila1 == fs for fs, _, _ in filas_subtotal_bloque):
            _, ini, fin = next(t for t in filas_subtotal_bloque if t[0] == fila1)
            columna_g.append([f"=SUM(G{ini}:G{fin})"])
        else:
            # filas divisorias/titulo de bloque y el pie (Subtotal CAPEX/
            # Contingencia/CAPEX TOTAL): se completan mas abajo con las
            # formulas correctas, para no sumar dos veces las filas de datos
            columna_g.append([""])

    # Subtotal CAPEX general = suma de los subtotales de cada bloque (evita
    # sumar dos veces las filas de datos)
    refs_subtotales = "+".join(f"G{fs}" for fs, _, _ in filas_subtotal_bloque)
    columna_g[fila_subtotal_general - primera] = [f"={refs_subtotales}"]
    columna_g[fila_contingencia - primera] = [f"=G{fila_subtotal_general}*{CONTINGENCIA_CELL}"]
    columna_g[fila_total - primera] = [f"=G{fila_subtotal_general}+G{fila_contingencia}"]

    ws.update(columna_g, f"G{primera}:G{ultima}", value_input_option="USER_ENTERED")
    print(f"Columna G (CAPEX COP) reescrita como formulas vivas: filas {primera}-{ultima}.")

    total_final = ws.acell(f"G{fila_total}", value_render_option="FORMATTED_VALUE").value
    print(f"CAPEX TOTAL (con contingencia) recalculado en vivo: {total_final}")


if __name__ == "__main__":
    main()
