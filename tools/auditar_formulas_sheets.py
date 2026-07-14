"""Audita formulas, literales numericos y errores del libro vivo de Sheets.

No modifica el libro. Compara la vista FORMULA con UNFORMATTED_VALUE para
detectar hojas con resultados calculados pegados como valores.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from integrations.sheets_client import Contabilidad


ERRORES = ("#VALUE!", "#REF!", "#N/A", "#DIV/0!", "#ERROR!", "#NAME?",
           "#NUM!", "#NULL!")


def _celda(grid: list[list], fila: int, columna: int):
    try:
        return grid[fila][columna]
    except IndexError:
        return ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--detalle", nargs="*", default=[],
                        help="Hojas cuyas filas se imprimen con coordenadas")
    parser.add_argument("--hojas", nargs="*", default=[],
                        help="Limita la auditoria a estas hojas sin imprimir detalle")
    parser.add_argument("--celdas", nargs="*", default=[],
                        help="Referencias Hoja!A1 para mostrar formula y valor")
    parser.add_argument("--buscar", nargs="*", default=[],
                        help="Imprime filas que contengan alguno de estos textos")
    args = parser.parse_args()
    cont = Contabilidad()
    if cont.modo != "sheets":
        raise SystemExit("Google Sheets no esta configurado en este entorno")

    ss = cont._spreadsheet()
    for ref in args.celdas:
        hoja, a1 = ref.rsplit("!", 1)
        ws = ss.worksheet(hoja)
        formula = ws.acell(a1, value_render_option="FORMULA").value
        valor = ws.acell(a1, value_render_option="FORMATTED_VALUE").value
        print(f"CELDA\t{ref}\t{formula}\t{valor}")
    total_formulas = total_literales = total_errores = 0
    print("hoja\tfilas\tcolumnas\tformulas\tliterales_numericos\terrores")
    hojas = ss.worksheets()
    if args.detalle or args.hojas:
        seleccion = set(args.detalle) | set(args.hojas)
        hojas = [ws for ws in hojas if ws.title in seleccion]
    rangos = ["'" + ws.title.replace("'", "''") + "'" for ws in hojas]
    lote_formulas = ss.values_batch_get(
        rangos, params={"valueRenderOption": "FORMULA"})["valueRanges"]
    lote_valores = ss.values_batch_get(
        rangos, params={"valueRenderOption": "UNFORMATTED_VALUE"})["valueRanges"]
    for ws, rf, rv in zip(hojas, lote_formulas, lote_valores):
        formulas = rf.get("values", [])
        valores = rv.get("values", [])
        filas = max(len(formulas), len(valores))
        columnas = max((len(f) for f in formulas + valores), default=0)
        n_formulas = n_literales = n_errores = 0
        errores_coord = []
        for i in range(filas):
            for j in range(columnas):
                formula = _celda(formulas, i, j)
                valor = _celda(valores, i, j)
                if isinstance(formula, str) and formula.startswith("="):
                    n_formulas += 1
                elif isinstance(valor, (int, float)) and not isinstance(valor, bool):
                    n_literales += 1
                if isinstance(valor, str) and valor.startswith(ERRORES):
                    n_errores += 1
                    errores_coord.append((i + 1, j + 1, valor, formula))
        total_formulas += n_formulas
        total_literales += n_literales
        total_errores += n_errores
        print(f"{ws.title}\t{filas}\t{columnas}\t{n_formulas}\t{n_literales}\t{n_errores}")
        for ef, ec, ev, eformula in errores_coord:
            print(f"  ERROR R{ef}C{ec}: {ev} | {eformula}")
        if ws.title in args.detalle:
            for i in range(filas):
                celdas = []
                for j in range(columnas):
                    formula = _celda(formulas, i, j)
                    valor = _celda(valores, i, j)
                    mostrado = formula if isinstance(formula, str) and formula.startswith("=") else valor
                    if mostrado not in ("", None):
                        letra = ""
                        n = j + 1
                        while n:
                            n, resto = divmod(n - 1, 26)
                            letra = chr(65 + resto) + letra
                        celdas.append(f"{letra}{i + 1}={mostrado}")
                if celdas:
                    print("  " + " | ".join(celdas))
        if args.buscar:
            for i in range(filas):
                texto = " | ".join(str(_celda(valores, i, j)) for j in range(columnas))
                if any(p.lower() in texto.lower() for p in args.buscar):
                    piezas = []
                    for j in range(columnas):
                        formula = _celda(formulas, i, j)
                        valor = _celda(valores, i, j)
                        mostrado = formula if isinstance(formula, str) and formula.startswith("=") else valor
                        if mostrado not in ("", None):
                            piezas.append(f"C{j + 1}={mostrado}")
                    print(f"  FILA {i + 1}: " + " | ".join(piezas))
    print(f"TOTAL\t-\t-\t{total_formulas}\t{total_literales}\t{total_errores}")


if __name__ == "__main__":
    main()
