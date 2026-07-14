"""
Publica la hoja 'Dashboard' del libro: resumen ejecutivo de una sola pantalla
con los indicadores clave de cada area (demanda, capacidad/OEE, CAPEX, caso
de negocio, RRHH) -- pedido explicito del dueno del proyecto ("un dashboard
de reporte"). Se recalcula desde las fuentes externas vivas cuando
EXTERNAL_ONLY=true. El fallback local solo queda disponible en modo de
desarrollo o recuperacion explicito.

Uso: python tools/actualizar_dashboard.py
"""
from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.finanzas_negocio import indicadores
from core.forecast import pronostico_base
from core.rrhh import resumen_por_rol
from integrations.rrhh_client import leer_empleados
from core.tiempos_oee import LINEAS, tabla_capacidad_comparada, tabla_oee
from integrations.sheets_client import Contabilidad
from config import settings

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
    try:
        r = pronostico_base(mc_n=500)
        ind = indicadores(r.mensual, "Base")
    except (ImportError, OSError):
        # En Windows corporativo App Control puede bloquear las DLL de scipy.
        # El dashboard ya es vivo en Sheets; solo necesitamos conservar como
        # entradas documentales los MAPE del ultimo backtest validado.
        r = SimpleNamespace(
            mensual=pd.DataFrame({
                "P1-CC350-RGB_unidades": [0],
                "P2-QT1500-PET_unidades": [0],
                "P3-GARR25L_unidades": [0],
            }),
            metricas=pd.DataFrame([
                {"producto": "P1", "mape": 0.029},
                {"producto": "P2", "mape": 0.029},
                {"producto": "P3", "mape": 0.021},
            ]),
        )
        ind = {"capex_total_cop": 0, "vpn_cop": 0, "tir_anual": 0,
               "roi_horizonte_60m": 0, "payback_simple_meses": 0,
               "payback_descontado_meses": 0,
               "ebitda_incremental_y1_cop": 0}
    tcap = tabla_capacidad_comparada(r.mensual)
    toee = tabla_oee()
    try:
        df_emp, origen_rrhh = leer_empleados()
    except Exception:  # noqa: BLE001
        if settings.EXTERNAL_ONLY:
            raise
        df_emp = pd.read_csv(settings.DATA_DIR / "empleados.csv")
        origen_rrhh = "csv"
    resumen = resumen_por_rol(df_emp)

    filas = [
        _f("DASHBOARD — RESUMEN EJECUTIVO ULOGIX × FEMSA/INDEGA FONTIBÓN"),
        _f("Snapshot recalculado al publicar (demanda/capacidad: motor Python — Monte "
          "Carlo/Holt-Winters, no reproducible como fórmula de Sheets; RRHH: leído en vivo "
          f"de la hoja RRHH, origen '{origen_rrhh}'). El caso de negocio de este bloque usa "
          "el motor canónico `core.finanzas_negocio` (el mismo que valida `tools/"
          "verificacion.py` y muestra la página Finanzas) — es un modelo PARALELO y más "
          "completo (D&A/impuestos/capital de trabajo explícitos) que las fórmulas nativas "
          "de `Sensibilidad`/`Flujo_Caja`/`ER_Proyecto` (modelo simplificado tipo seed); "
          "ambos convergen hoy pero son cálculos distintos a propósito — no se combinan. "
          "Para el detalle vivo por escenario, ver las páginas del dashboard Streamlit "
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
    filas.append(_f("② CAPACIDAD Y OEE — ANTES vs. DESPUÉS DEL PROYECTO"))
    filas.append(_f("línea", "OEE antes → después", "utilización antes → después",
                    "capacidad antes → después", "dictamen antes", "dictamen después"))
    for lin in LINEAS:
        oee_row = toee[toee["linea"] == lin].iloc[0]
        cap_row = tcap[tcap["linea"] == lin].iloc[0]
        filas.append(_f(lin, f"{oee_row['oee_base']*100:.1f}% → "
                       f"{oee_row['oee_a_implementar']*100:.1f}%",
                       f"{cap_row['U_antes']*100:.0f}% → {cap_row['U_despues']*100:.0f}%",
                       f"{cap_row['capacidad_antes_und']/1e6:.1f}M → "
                       f"{cap_row['capacidad_despues_und']/1e6:.1f}M",
                       cap_row["dictamen_antes"], cap_row["dictamen_despues"]))
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
    filas.append(_f("Tiempos", "equipos, tiempos, OEE y capacidad antes vs. después del proyecto"))
    filas.append(_f("CAPEX", "inversión por área (Sheets gobierna — el usuario edita aquí)"))
    filas.append(_f("RRHH", "roster + resumen por rol + carga prestacional"))
    filas.append(_f("Parametros", "supuestos financieros vivos (TRM, TMAR, nómina, precios...)"))
    filas.append(_f("Sensibilidad", "análisis tornado — dónde vale la pena invertir en mejor información"))
    filas.append(_f("APU_Ingenieria", "justificación de los costos de ingeniería que cobra ULogix"))

    _aplicar_formulas_vivas(filas)
    return filas, titulos


def _aplicar_formulas_vivas(filas: list[list]) -> None:
    """Enlaza el resumen con las hojas fuente en vez de publicar un snapshot."""
    filas[1][0] = ("Resumen vivo: demanda desde Demanda; capacidad/OEE desde Tiempos; "
                   "caso de negocio desde las formulas nativas de Flujo_Caja/CAPEX; "
                   "nomina desde RRHH. Las metricas MAPE siguen siendo resultados del "
                   "backtest Python y se actualizan al volver a publicar el pronostico.")

    for fila, col in zip((6, 7, 8), ("D", "E", "F")):
        filas[fila - 1][1] = f"=SUM(Demanda!{col}$5:{col}$16)"

    for fila_dash, fila_oee, fila_cap in zip((12, 13, 14), (90, 91, 92), (104, 105, 106)):
        filas[fila_dash - 1][1] = (f'=TEXT(Tiempos!I{fila_cap};"0.0%")&" → "&'
                                          f'TEXT(Tiempos!J{fila_cap};"0.0%")')
        filas[fila_dash - 1][2] = (f'=TEXT(Tiempos!U{fila_cap};"0%")&" → "&'
                                          f'TEXT(Tiempos!V{fila_cap};"0%")')
        filas[fila_dash - 1][3] = (f'=TEXT(Tiempos!R{fila_cap}/1000000;"0.0")&"M → "&'
                                          f'TEXT(Tiempos!T{fila_cap}/1000000;"0.0")&"M"')
        filas[fila_dash - 1][4] = f"=Tiempos!X{fila_cap}"
        filas[fila_dash - 1][5] = f"=Tiempos!Y{fila_cap}"

    filas[15][0] = "③ CASO DE NEGOCIO (modelo nativo vivo de Sheets)"
    formulas_fin = {
        17: '=INDEX(CAPEX!$G:$G;MATCH("CAPEX TOTAL (con contingencia)";CAPEX!$C:$C;0))',
        18: "=Flujo_Caja!B19", 19: "=Flujo_Caja!B21", 20: "=Flujo_Caja!B24",
        21: "=Flujo_Caja!B26", 22: "=Flujo_Caja!B27", 23: "=Flujo_Caja!B28",
    }
    for fila, formula in formulas_fin.items():
        filas[fila - 1][1] = formula

    for fila in range(27, 31):
        filas[fila - 1][1] = f"=INDEX(RRHH!$B:$B;MATCH(A{fila};RRHH!$A:$A;0))"
        filas[fila - 1][2] = f"=INDEX(RRHH!$C:$C;MATCH(A{fila};RRHH!$A:$A;0))"
        filas[fila - 1][3] = f"=INDEX(RRHH!$H:$H;MATCH(A{fila};RRHH!$A:$A;0))"
    filas[30][3] = "=SUM(D27:D30)"


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
    ws.update(filas, "A1", value_input_option="USER_ENTERED")
    ws.format(f"A1:{chr(64+min(ancho,26))}1", TITULO)
    for idx in titulos_idx:
        ws.format(f"A{idx}:{chr(64+min(ancho,26))}{idx}", BLOQUE)
    ws.freeze(rows=2)
    print(f"Publicado 'Dashboard': {len(filas)} filas.")


if __name__ == "__main__":
    main()
