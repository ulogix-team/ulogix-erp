"""
Publica la hoja 'Dashboard' del libro: resumen ejecutivo de una sola pantalla
con los indicadores clave de cada area (demanda, capacidad/OEE, CAPEX, caso
de negocio, RRHH) -- pedido explicito del dueno del proyecto ("un dashboard
de reporte"). Se recalcula desde el motor local (fallback/default, misma
filosofia que tools/verificacion.py) para no depender de que Sheets ya
tenga todo publicado en el momento de correr este script.

Uso: python tools/actualizar_dashboard.py
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings
from core.finanzas_negocio import indicadores
from core.forecast import pronostico_base
from core.rrhh import resumen_por_rol
from core.tiempos_oee import LINEAS, tabla_capacidad, tabla_oee
from integrations.sheets_client import Contabilidad

TITULO = {"backgroundColor": {"red": 0.145, "green": 0.09, "blue": 0.28},
         "textFormat": {"bold": True, "fontSize": 14,
                        "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                        "fontFamily": "Arial"}}
BLOQUE = {"backgroundColor": {"red": 0.75, "green": 0.65, "blue": 0.15},
         "textFormat": {"bold": True, "fontFamily": "Arial"}}


def _f(*vals, n=6):
    v = list(vals)
    return v + [""] * (n - len(v))


def construir_filas() -> tuple[list[list], list[int]]:
    r = pronostico_base(mc_n=500)
    ind = indicadores(r.mensual, "Base")
    tcap = tabla_capacidad(r.mensual)
    toee = tabla_oee()
    import pandas as pd
    df_emp = pd.read_csv(settings.DATA_DIR / "empleados.csv")
    resumen = resumen_por_rol(df_emp)

    filas = [
        _f("DASHBOARD — RESUMEN EJECUTIVO ULOGIX × FEMSA/INDEGA FONTIBÓN"),
        _f("Snapshot recalculado desde el motor local (escenario Base) — para el "
          "detalle vivo por escenario, ver las páginas del dashboard Streamlit "
          "(Escenarios, Inventario, Finanzas, RRHH)."),
        _f(""),
    ]
    titulos = []

    titulos.append(len(filas) + 1)
    filas.append(_f("① DEMANDA (pronóstico Base, próximos 12 meses)"))
    filas.append(_f("producto", "demanda anual (und)", "MAPE backtest"))
    for _, m in r.metricas.iterrows():
        sku_map = {"P1": "P1-CC350-RGB", "P2": "P2-QT1500-PET", "P3": "P3-GARR25L"}
        sku = sku_map.get(m["producto"], m["producto"])
        col = f"{sku}_unidades"
        anual = r.mensual[col].sum() if col in r.mensual.columns else 0
        filas.append(_f(sku, f"{anual:,.0f}", f"{m['mape']*100:.1f}%"))
    filas.append(_f(""))

    titulos.append(len(filas) + 1)
    filas.append(_f("② CAPACIDAD Y OEE (turnos actuales vs. demanda)"))
    filas.append(_f("línea", "OEE base → objetivo (+5%)", "utilización", "dictamen"))
    for lin in LINEAS:
        oee_row = toee[toee["linea"] == lin].iloc[0]
        cap_row = tcap[tcap["linea"] == lin].iloc[0]
        filas.append(_f(lin, f"{oee_row['oee_base']*100:.1f}% → "
                       f"{oee_row['oee_a_implementar']*100:.1f}%",
                       f"{cap_row['U_turnos_actuales']*100:.0f}%", cap_row["dictamen"]))
    filas.append(_f(""))

    titulos.append(len(filas) + 1)
    filas.append(_f("③ CASO DE NEGOCIO (escenario Base, TMAR 18% E.A.)"))
    filas.append(_f("CAPEX total", f"${ind['capex_total_cop']/1e6:,.0f} M COP"))
    filas.append(_f("VPN", f"${ind['vpn_cop']/1e6:,.0f} M COP"))
    filas.append(_f("TIR anual", f"{ind['tir_anual']*100:.1f}%"))
    filas.append(_f("ROI 60 meses", f"{ind['roi_horizonte_60m']*100:.1f}%"))
    filas.append(_f("Payback simple", f"{ind['payback_simple_meses']} meses"))
    filas.append(_f("Payback descontado", f"{ind['payback_descontado_meses']} meses"))
    filas.append(_f("EBITDA incremental (año 1 operativo)",
                   f"${ind['ebitda_incremental_y1_cop']/1e6:,.0f} M COP"))
    filas.append(_f(""))

    titulos.append(len(filas) + 1)
    filas.append(_f("④ RRHH (roster activo)"))
    filas.append(_f("rol", "conteo", "fase", "costo total mes COP"))
    for _, rr in resumen.iterrows():
        filas.append(_f(rr["rol_personal"], int(rr["conteo"]), rr["fase"],
                       f"${rr['costo_total_mes_cop']:,.0f}"))
    total_nomina = resumen["costo_total_mes_cop"].sum()
    filas.append(_f("TOTAL nómina/mes", "", "", f"${total_nomina:,.0f}"))
    filas.append(_f(""))

    titulos.append(len(filas) + 1)
    filas.append(_f("⑤ NAVEGACIÓN DEL LIBRO"))
    filas.append(_f("Demanda/DemandaEscenario", "pronóstico y escenario activo (ERP → Sheets)"))
    filas.append(_f("Tiempos", "estudio de tiempos, OEE base y objetivo +5%, capacidad vs. demanda"))
    filas.append(_f("CAPEX", "inversión por área (Sheets gobierna — el usuario edita aquí)"))
    filas.append(_f("RRHH", "roster + resumen por rol + carga prestacional"))
    filas.append(_f("Parametros", "supuestos financieros vivos (TRM, TMAR, nómina, precios...)"))
    filas.append(_f("Sensibilidad", "análisis tornado — dónde vale la pena invertir en mejor información"))
    filas.append(_f("APU_Ingenieria", "justificación de los costos de ingeniería que cobra ULogix"))

    return filas, titulos


def main() -> None:
    cont = Contabilidad()
    if cont.modo != "sheets":
        raise SystemExit("Sheets no esta configurado (.env).")
    ss = cont._spreadsheet()
    filas, titulos_idx = construir_filas()
    ancho = max(len(f) for f in filas)
    filas = [f + [""] * (ancho - len(f)) for f in filas]
    try:
        ws = ss.worksheet("Dashboard")
        ws.resize(rows=max(len(filas) + 10, ws.row_count), cols=max(ancho, ws.col_count))
    except Exception:  # noqa: BLE001
        ws = ss.add_worksheet("Dashboard", rows=len(filas) + 10, cols=ancho, index=0)
    ws.clear()
    # RAW (no USER_ENTERED): estas celdas son texto ya formateado, no
    # formulas -- USER_ENTERED deja que Sheets reinterprete numeros con una
    # sola coma como decimal (locale es-CO) y corrompe cifras como
    # "279,150" -> "279,15"
    ws.update(filas, "A1", value_input_option="RAW")
    ws.format(f"A1:{chr(64+min(ancho,26))}1", TITULO)
    for idx in titulos_idx:
        ws.format(f"A{idx}:{chr(64+min(ancho,26))}{idx}", BLOQUE)
    ws.freeze(rows=2)
    print(f"Publicado 'Dashboard': {len(filas)} filas.")


if __name__ == "__main__":
    main()
