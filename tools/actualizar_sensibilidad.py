"""
Agrega a la hoja 'Sensibilidad' (SIN tocar las filas 1-21, que tienen
formulas vivas de VPN/TIR por escenario ya reparadas -- ver decision #18 de
CLAUDE.md): (1) el tornado parametrico detallado de core/sensibilidad.py
(hoy solo vivia en la pagina Finanzas del dashboard), y (2) documentacion de
los 6 escenarios de demanda y como se propagan por el ERP (pedido explicito
del dueno del proyecto).

Uso: python tools/actualizar_sensibilidad.py
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.escenarios import ESCENARIOS
from core.forecast import pronostico_base
from core.sensibilidad import tornado
from integrations.sheets_client import Contabilidad

BLOQUE_FMT = {"backgroundColor": {"red": 1.0, "green": 0.85, "blue": 0.4},
             "textFormat": {"bold": True, "fontFamily": "Arial"}}


def _f(*vals, n=6):
    v = list(vals)
    return v + [""] * (n - len(v))


def construir_filas_extra() -> tuple[list[list], list[int]]:
    r = pronostico_base(mc_n=500)
    t = tornado(r.mensual)

    filas: list[list] = [_f("")]
    titulos = []

    titulos.append(len(filas) + 1)
    filas.append(_f("TORNADO PARAMÉTRICO — margen bruto anual (escenario Base)"))
    filas.append(_f(f"Margen base: ${t.attrs['margen_base_cop']:,.0f} COP. Cada parámetro se "
                    "perturba individualmente entre su cota baja y alta manteniendo el resto "
                    "en el valor base — el ranking indica dónde vale la pena invertir en mejor "
                    "información (recalculado con `core/sensibilidad.py: tornado()`, snapshot "
                    "al publicar; el interactivo vive en la página Finanzas del dashboard)."))
    filas.append(_f("parámetro", "cota baja→alta", "margen bajo (COP)", "margen alto (COP)",
                    "Δ% bajo", "Δ% alto"))
    t_ordenado = t.sort_values("amplitud_pct", ascending=False)
    for _, row in t_ordenado.iterrows():
        filas.append(_f(row["parametro"], "", f"${row['margen_low_cop']:,.0f}",
                        f"${row['margen_high_cop']:,.0f}", f"{row['delta_low_pct']:+.2f}%",
                        f"{row['delta_high_pct']:+.2f}%"))
    filas.append(_f(""))

    titulos.append(len(filas) + 1)
    filas.append(_f("ESCENARIOS DE PRONÓSTICO — cómo se propagan por el ERP"))
    filas.append(_f("Los 6 escenarios (`core/escenarios.py`) aplican factores multiplicativos "
                    "mes a mes POR PRODUCTO sobre el pronóstico estadístico base (Holt-Winters "
                    "+ Bates-Granger óptimo) — el modelo nunca se recalibra, solo se escala. Se "
                    "activan en la página *Escenarios* del dashboard (botón 'Activar'), y desde "
                    "ahí la demanda del escenario elegido reemplaza a la Base en TODO el resto "
                    "de la suite hasta que se vuelva a cambiar:"))
    filas.append(_f("① Inventario / MRP (página *Inventario*): política (s,Q) y plan de "
                    "compras se recalculan con la nueva demanda; la sección 'Capacidad y "
                    "factibilidad de producción' muestra si cada línea sigue siendo factible "
                    "con los turnos actuales."))
    filas.append(_f("② Compras (página *Órdenes Odoo*): el plan MRP que se convierte en "
                    "purchase.order/mrp.production usa la demanda del escenario activo."))
    filas.append(_f("③ Finanzas (página *Finanzas*): el caso de negocio (VPN/TIR/ROI/payback) "
                    "se recalcula para el escenario activo y se compara contra Base en la misma "
                    "pantalla."))
    filas.append(_f("④ Sheets: al activar, la demanda del escenario se publica a la hoja "
                    "`DemandaEscenario` (rango fijo A4:F16) — las hojas `FinancieroEscenario` "
                    "y esta misma `Sensibilidad` (filas 1-21, arriba) leen de ahí."))
    filas.append(_f(""))
    filas.append(_f("escenario", "justificación", "fuente"))
    for nombre, esc in ESCENARIOS.items():
        filas.append(_f(nombre, esc.justificacion, esc.fuente))

    return filas, titulos


def main() -> None:
    cont = Contabilidad()
    if cont.modo != "sheets":
        raise SystemExit("Sheets no esta configurado (.env).")
    ss = cont._spreadsheet()
    ws = ss.worksheet("Sensibilidad")
    vals = ws.get_all_values()
    # Las filas 1-21 tienen formulas vivas (ya reparadas, decision #18) --
    # NO tocarlas. Todo lo que haya de la fila 22 en adelante es contenido
    # de una corrida anterior de este mismo script: se borra antes de
    # reescribir para no ir acumulando copias en cada corrida.
    FILA_LIMITE_FORMULAS = 21
    if len(vals) > FILA_LIMITE_FORMULAS:
        ws.batch_clear([f"A{FILA_LIMITE_FORMULAS+1}:{chr(64+min(len(vals[0]),26))}{len(vals)}"])
    fila_inicio = FILA_LIMITE_FORMULAS + 2

    filas_extra, titulos_rel = construir_filas_extra()
    ancho = max(len(f) for f in filas_extra)
    filas_extra = [f + [""] * (ancho - len(f)) for f in filas_extra]

    ws.resize(rows=max(fila_inicio + len(filas_extra) + 10, ws.row_count),
             cols=max(ancho, ws.col_count))
    # RAW, no USER_ENTERED: este bloque es texto estatico (snapshot del
    # tornado + documentacion), no formulas -- USER_ENTERED deja que Sheets
    # reinterprete texto como "+9.25%" como el INICIO de una formula
    # (convencion heredada de Lotus 1-2-3: "+" dispara modo formula) y
    # revienta en #ERROR!, ademas del problema de coma-decimal ya conocido
    # (ver decision #17, bug del Dashboard)
    ws.update(filas_extra, f"A{fila_inicio}", value_input_option="RAW")
    for idx_rel in titulos_rel:
        fila_abs = fila_inicio + idx_rel - 1
        ws.format(f"A{fila_abs}:{chr(64+min(ancho,26))}{fila_abs}", BLOQUE_FMT)

    print(f"Agregado tornado + documentación de escenarios a 'Sensibilidad' desde la fila "
         f"{fila_inicio} ({len(filas_extra)} filas nuevas). Filas 1-21 (fórmulas vivas) "
         "sin tocar.")


if __name__ == "__main__":
    main()
