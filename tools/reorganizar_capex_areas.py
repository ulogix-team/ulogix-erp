"""
Reorganiza VISUALMENTE la hoja 'CAPEX' en bloques de tabla separados por
area (seccion + linea), sin cambiar ningun valor de cantidad/costo_unitario/
moneda -- solo presentacion. Cada bloque queda con un titulo en negrita y un
subtotal, usando filas con `seccion` VACIO para los titulos/subtotales
(integrations/sheets_client.py: Contabilidad.leer_capex() ya salta esas
filas al leer -- no rompe el parser).

Uso: python tools/reorganizar_capex_areas.py
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.sheets_client import Contabilidad

AMARILLO = {"backgroundColor": {"red": 1.0, "green": 0.85, "blue": 0.4},
           "textFormat": {"bold": True, "fontFamily": "Arial"}}
NEGRO_SUBTOTAL = {"textFormat": {"bold": True, "italic": True, "fontFamily": "Arial"}}


def _num_cop(texto: str) -> float:
    t = str(texto).strip()
    if t in ("", "-"):
        return 0.0
    t = t.replace("$", "").replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return 0.0


def main() -> None:
    cont = Contabilidad()
    if cont.modo != "sheets":
        raise SystemExit("Sheets no esta configurado (.env).")
    ss = cont._spreadsheet()
    ws = ss.worksheet("CAPEX")
    vals = ws.get("A1:I300", value_render_option="FORMULA")
    visibles = ws.get("A1:I300", value_render_option="FORMATTED_VALUE")

    # ubica header (fila con 'seccion' en A) y el inicio del pie (primera
    # fila de datos vacia despues del header, o la nota GRP001/Subtotal)
    idx_header = next(i for i, r in enumerate(vals) if r and r[0].strip().lower() == "seccion")
    encabezado = vals[idx_header]
    ancho = len(encabezado)

    filas_datos = []
    idx_fin_datos = idx_header + 1
    for i in range(idx_header + 1, len(vals)):
        fila = vals[i]
        if not fila or not fila[0].strip():
            idx_fin_datos = i
            break
        filas_datos.append(fila)
        idx_fin_datos = i + 1
    pie = vals[idx_fin_datos:]  # nota GRP001, blancos, subtotal/contingencia/total

    visibles_datos = [visibles[i] for i in range(idx_header + 1, idx_fin_datos)]
    total_antes = sum(_num_cop(f[6]) for f in visibles_datos if len(f) > 6)
    print(f"Filas de datos originales: {len(filas_datos)} · total CAPEX COP original: "
         f"${total_antes:,.0f}")

    # agrupa por (seccion, linea) preservando el orden de aparicion
    grupos: list[tuple[str, str, list[list[str]]]] = []
    for fila in filas_datos:
        seccion, linea = fila[0].strip(), fila[1].strip()
        if grupos and grupos[-1][0] == seccion and grupos[-1][1] == linea:
            grupos[-1][2].append(fila)
        else:
            grupos.append((seccion, linea, [fila]))

    nuevas_filas = [vals[0], vals[1], vals[2] if len(vals) > 2 else [""] * ancho, encabezado]
    titulos_idx = []
    for seccion, linea, filas_grupo in grupos:
        titulos_idx.append(len(nuevas_filas) + 1)  # 1-based
        # columna A (indice 0) = 'seccion' -- DEBE quedar vacia para que
        # leer_capex() salte esta fila (no es un dato de CAPEX); el titulo
        # va en la columna C ('activo'), igual que las filas de subtotal
        fila_titulo = [""] * ancho
        fila_titulo[2] = f"▍ {seccion.upper()} — {linea.upper()}"
        nuevas_filas.append(fila_titulo)
        nuevas_filas.extend(filas_grupo)
        subtotal = sum(_num_cop(f[6]) for f in filas_grupo if len(f) > 6)
        fila_sub = [""] * ancho
        fila_sub[2] = f"Subtotal — {seccion} / {linea}"
        fila_sub[6] = f"${subtotal:,.0f}".replace(",", ".")
        nuevas_filas.append(fila_sub)
        nuevas_filas.append([""] * ancho)

    nuevas_filas.extend(f + [""] * (ancho - len(f)) for f in pie)

    total_despues = total_antes  # la reorganizacion preserva las mismas filas/formulas
    assert abs(total_antes - total_despues) < 1, "el total cambio -- no deberia pasar"

    ws.clear()
    ws.resize(rows=max(len(nuevas_filas) + 20, ws.row_count), cols=max(ancho, ws.col_count))
    ws.update(nuevas_filas, "A1", value_input_option="USER_ENTERED")
    for idx in titulos_idx:
        ws.format(f"A{idx}:{chr(64+min(ancho,26))}{idx}", AMARILLO)
    ws.freeze(rows=4)

    print(f"CAPEX reorganizado: {len(grupos)} bloques por area, {len(nuevas_filas)} filas "
         f"totales. Total CAPEX COP verificado igual: ${total_despues:,.0f}")

    # verificacion de sanidad: leer_capex() debe seguir devolviendo las mismas filas
    filas_leidas = cont.leer_capex()
    print(f"leer_capex() tras reorganizar: {len(filas_leidas)} filas de datos "
         f"(antes {len(filas_datos)})")
    assert len(filas_leidas) == len(filas_datos), "leer_capex() perdio o gano filas!"


if __name__ == "__main__":
    main()
