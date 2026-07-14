"""
Publica en la hoja 'CAPEX' de Google Sheets el CAPEX corregido: sin lavadoras
ni elementos de inspeccion de linea (cantidad=0, no se borran las filas -- se
conserva el registro de que se evaluaron y excluyeron), con el garrafon
separado en llenado/taponado vs inspeccion (mismo patron que ya uso el
usuario en L2/L3), y las 2 filas resumen de celdas roboticas expandidas a
detalle de componente real (60 items) segun las BOM de ingenieria de las
celdas de paletizado GANTRY (L1-L2) y brazo articulado (L3).

Motivo del cambio de alcance y todos los supuestos de precio (p.ej. el split
del garrafon) estan documentados como comentarios junto a `CAPEX_FILAS` en
core/finanzas_negocio.py -- ese modulo es el "seed" que este script publica
a Sheets (decision de diseno #3 de CLAUDE.md: Sheets gobierna en operacion,
Python es el default/fallback; este script es la migracion puntual que
sincroniza la hoja real con el seed corregido, no un generador recurrente).

Preserva EXACTAMENTE las filas 1-4 (titulo, nota, blanco, encabezado) tal
como estan en el libro real -- no se toca el texto del encabezado. Reescribe
las filas de datos (antes 25, ahora 84) y el pie (nota GRP001 + Subtotal +
Contingencia + CAPEX TOTAL), recalculando las formulas de la columna
'CAPEX COP' por fila segun la moneda:
  USD  (benchmark, no confirmado)  -> cantidad x costo_unitario x TRM x FACTOR_RFQ
  USD* (cotizacion real de BOM)    -> cantidad x costo_unitario x TRM (sin RFQ)
  GBP* (cotizacion real proveedor) -> cantidad x costo_unitario x GBP/COP
  COP  (directo)                   -> cantidad x costo_unitario

Uso: python tools/actualizar_capex_celdas.py
Requiere Sheets configurado (.env) -- si no hay credenciales, no hace nada
util (la hoja CAPEX en modo fallback local se corrige de otra forma: solo
hace falta que el fallback de Python, ya corregido, se use directamente).
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.finanzas_negocio import CAPEX_FILAS
from integrations.sheets_client import Contabilidad

FILA_ENCABEZADO = 4          # fila 1-indexada del encabezado real en Sheets
FILA_PRIMER_DATO = FILA_ENCABEZADO + 1

NOTA_GRP001 = (
    "⚠ GRP001: dos grippers distintos con el mismo codigo (4 mordazas 40 kg "
    "vs 3 ventosas 15.5 kg). NO consolidados; validar con el taller antes de "
    "la RFQ."
)


def _formula_capex_cop(fila_num: int, moneda: str) -> str:
    if moneda == "USD":
        return f"=D{fila_num}*F{fila_num}*Parametros!$B$5*Parametros!$B$6"
    if moneda == "USD*":
        return f"=D{fila_num}*F{fila_num}*Parametros!$B$5"
    if moneda == "GBP*":
        return (f'=D{fila_num}*F{fila_num}*INDEX(Parametros!$B:$B;'
                'MATCH("gbp_cop";Parametros!$A:$A;0))')
    return f"=D{fila_num}*F{fila_num}"  # COP directo


def filas_datos() -> list[list]:
    filas = []
    for i, (seccion, linea, activo, cantidad, moneda, costo_unitario,
            vida_anios, categoria_dep) in enumerate(CAPEX_FILAS):
        fila_num = FILA_PRIMER_DATO + i
        filas.append([
            seccion, linea, activo, cantidad, moneda, costo_unitario,
            _formula_capex_cop(fila_num, moneda), vida_anios, categoria_dep,
        ])
    return filas


def filas_pie(fila_ultimo_dato: int) -> list[list]:
    fila_nota = fila_ultimo_dato + 1
    fila_blanco = fila_ultimo_dato + 2
    fila_subtotal = fila_ultimo_dato + 3
    fila_contingencia = fila_ultimo_dato + 4
    fila_total = fila_ultimo_dato + 5
    return [
        ["", "", NOTA_GRP001, "", "", "", "", "", ""],
        ["", "", "", "", "", "", "", "", ""],
        ["", "", "Subtotal CAPEX", "", "", "",
         f"=SUM(G{FILA_PRIMER_DATO}:G{fila_ultimo_dato})", "", ""],
        ["", "", "Contingencia", "", "", "",
         f"=G{fila_subtotal}*Parametros!$B$27", "", ""],
        ["", "", "CAPEX TOTAL (con contingencia)", "", "", "",
         f"=G{fila_subtotal}*(1+Parametros!$B$27)", "", ""],
    ], fila_total


def main() -> None:
    cont = Contabilidad()
    if cont.modo != "sheets":
        raise SystemExit(
            "Sheets no esta configurado (.env) -- nada que publicar. El "
            "fallback local (core.finanzas_negocio.CAPEX_FILAS) ya quedo "
            "corregido y se usa automaticamente cuando Sheets no responde."
        )
    ss = cont._spreadsheet()
    ws = ss.worksheet("CAPEX")

    encabezado_actual = ws.get_all_values()[:FILA_ENCABEZADO]
    if len(encabezado_actual) < FILA_ENCABEZADO:
        raise SystemExit(
            f"La hoja CAPEX tiene menos de {FILA_ENCABEZADO} filas -- "
            "no se reconoce el encabezado esperado, abortando por seguridad."
        )

    datos = filas_datos()
    fila_ultimo_dato = FILA_PRIMER_DATO + len(datos) - 1
    pie, _ = filas_pie(fila_ultimo_dato)

    todas = encabezado_actual + datos + pie

    ws.clear()
    ws.update(todas, "A1", value_input_option="USER_ENTERED")

    print(f"Publicado CAPEX: {len(datos)} filas de datos (antes 25) + "
          f"encabezado preservado + pie (Subtotal/Contingencia/Total).")
    print(f"  Filas de datos: {FILA_PRIMER_DATO}..{fila_ultimo_dato}")
    print(f"  Subtotal en G{fila_ultimo_dato + 3}, "
          f"Total en G{fila_ultimo_dato + 5}")

    celdas_l1l2 = [f for f in CAPEX_FILAS if f[0].startswith("Celdas") and f[1] == "L1-L2"]
    celdas_l3 = [f for f in CAPEX_FILAS if f[0].startswith("Celdas") and f[1] == "L3"]
    suma_l1l2 = sum(f[3] * f[5] for f in celdas_l1l2)
    suma_l3 = sum(f[3] * f[5] for f in celdas_l3)
    print(f"  Celda GANTRY L1-L2: {len(celdas_l1l2)} items -> suma nominal {suma_l1l2:,.0f}")
    print(f"  Celda ROBOT ARTICULADO L3: {len(celdas_l3)} items -> suma nominal multimoneda {suma_l3:,.0f}")
    zeroed = [f[2] for f in CAPEX_FILAS if f[3] == 0]
    print(f"  Filas en cantidad=0 ({len(zeroed)}): {zeroed}")


if __name__ == "__main__":
    main()
