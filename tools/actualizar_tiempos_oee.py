"""
Reconstruye la hoja 'Tiempos' del libro con TODO el contenido de la
auditoria de ingenieria original ('Tiempos_Fontibon_Corregido.xlsx', 10
hojas: Memoria, Correcciones, Parametros, Tiempos_Lineas, MLT_VSM, OEE_TEEP,
Capacidad_vs_Demanda, Maquinas_Referencias, Referencias, Glosario),
consolidada en UNA sola hoja bien organizada en bloques -- y borra la hoja
'OEE_TEEP' del libro (redundante: su contenido queda cubierto en los
bloques 4/8 de la nueva 'Tiempos').

Pedido explicito del dueño del proyecto: la mejora de OEE debe ser
ESTRICTAMENTE +5% relativo a nivel global (no una cifra aproximada) -- ver
core/tiempos_oee.py: _mejora_pp_linea()/CRONOGRAMA_MEJORA_OEE. Este script
publica esa reconciliacion exacta y el cronograma de implementacion.

Sigue el mismo patron de escritura que tools/publicar_apu_ingenieria.py /
tools/actualizar_capex_celdas.py: clear + rewrite completo de la hoja via
gspread, NO regenera el libro completo (eso pisaria ediciones manuales del
usuario en otras hojas).

Uso: python tools/actualizar_tiempos_oee.py
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.sheets_client import Contabilidad
from core.tiempos_oee import (DATOS, LINEAS, CRONOGRAMA_MEJORA_OEE,
                              componentes_oee, tabla_capacidad,
                              tabla_oee, tabla_tiempos, _mejora_pp_linea)

FUENTE_XLSX = r"c:\Users\samue\Downloads\Repo\Tiempos_Fontibon_Corregido.xlsx"

AZUL, NEGRO, VERDE, AMARILLO = "#1155CC", "#000000", "#38761D", "#BF9000"
FMT_TITULO = {"backgroundColor": {"red": 0.145, "green": 0.09, "blue": 0.28},
             "textFormat": {"bold": True, "fontSize": 13,
                            "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                            "fontFamily": "Arial"}}
FMT_BLOQUE = {"backgroundColor": {"red": 0.75, "green": 0.65, "blue": 0.15},
             "textFormat": {"bold": True, "fontSize": 11, "fontFamily": "Arial"}}
FMT_ENCAB = {"backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.85},
            "textFormat": {"bold": True, "fontFamily": "Arial"}}


def _leer_fuente() -> dict:
    import pandas as pd
    xl = pd.ExcelFile(FUENTE_XLSX)
    return {h: xl.parse(h, header=None) for h in xl.sheet_names}


def _fila_ancha(*vals, n=10) -> list:
    v = list(vals)
    return v + [""] * (n - len(v))


def _filas_memoria(src) -> list[list]:
    df = src["Memoria"]
    out = [_fila_ancha("BLOQUE 1 · MEMORIA — METODOLOGÍA Y HALLAZGOS CLAVE")]
    for _, row in df.iterrows():
        txt = str(row[1]) if len(row) > 1 and str(row[1]) != "nan" else ""
        if txt:
            out.append(_fila_ancha(txt))
    return out


def _filas_correcciones(src) -> list[list]:
    df = src["Correcciones"]
    out = [_fila_ancha("BLOQUE 2 · CORRECCIONES — AUDITORÍA DEL ARCHIVO ORIGINAL (8 hallazgos)"),
          _fila_ancha("Hallazgo", "En el archivo original", "Corrección aplicada aquí")]
    for _, row in df.iterrows():
        c1, c2, c3 = str(row[1]), str(row[2]), str(row[3])
        if c1 in ("nan", "Hallazgo") or c1 == "" or (c2 == "nan" and c3 == "nan"):
            continue  # salta el titulo de la fuente y filas sin datos reales
        out.append(_fila_ancha(c1, c2, c3))
    return out


def _filas_parametros_tiempos() -> list[list]:
    out = [_fila_ancha("BLOQUE 3 · PARÁMETROS Y TIEMPOS POR LÍNEA (fórmulas APM, "
                       "Tc/T_D/Takt/Q/Tb/Tp/Rp_lote/PC/PC_efectiva)")]
    t = tabla_tiempos()
    cols = ["linea", "producto", "rp_nominal_uph", "rp_diseno_uph", "ciclo_Tc_s",
           "turnos", "horas_turno", "dias_operativos_ano", "tsu_alistamiento_min",
           "q_lote_turno_und", "pallets_por_lote", "unidades_por_pallet",
           "tb_lote_h", "tp_s_por_und", "rp_lote_uph", "mlt_lote_h",
           "capacidad_efectiva_anual_und"]
    out.append(_fila_ancha(*cols, n=len(cols)))
    for _, row in t.iterrows():
        out.append(_fila_ancha(*[row[c] for c in cols], n=len(cols)))
    out.append(_fila_ancha("Nota L3: cuello real es el paletizado MANUAL (2 operarios x "
                           "240 gfn/h), no la llenadora (600 gfn/h) — la celda robótica "
                           "elimina ese cuello."))
    return out


def _filas_mlt_vsm(src) -> list[list]:
    out = [_fila_ancha("BLOQUE 4 · MLT / VSM POR LÍNEA (Value Stream Map estación-por-"
                       "estación) — MLT = Tsu(max) + Σ(Tc_i+Tno_i) + (Q−1)·Tc_cuello")]
    df = src["MLT_VSM"]
    for _, row in df.iterrows():
        vals = [str(row[i]) if len(row) > i and str(row[i]) != "nan" else "" for i in range(7)]
        if any(vals):
            out.append(_fila_ancha(*vals[1:], n=6))
    return out


def _filas_oee(demanda=None) -> list[list]:
    out = [_fila_ancha("BLOQUE 5 · OEE BOTTOM-UP (base medido, valida 75-78% de la "
                       "visita técnica) — A=Ter/Tep · SE=Rp_real/Rp_diseño · RE=microparos "
                       "medidos · PE=RE×SE · Q=1−rechazo · OEE=A×PE×Q")]
    cols = ["linea", "producto", "A_disponibilidad", "SE_tasa", "RE_microparos",
           "PE_desempeno", "Q_calidad", "oee_base", "carga_calendario", "teep"]
    out.append(_fila_ancha(*cols, n=len(cols)))
    t = tabla_oee()
    for _, row in t.iterrows():
        out.append(_fila_ancha(*[row[c] for c in cols], n=len(cols)))
    return out


def _filas_mejora_5pct() -> list[list]:
    out = [_fila_ancha("BLOQUE 6 · MEJORA DE OEE A IMPLEMENTAR — OBJETIVO ESTRICTO "
                       "+5% RELATIVO (exacto por línea, no una cifra plana aproximada)"),
          _fila_ancha("oee_a_implementar = oee_base × 1.05 EXACTO para cada línea. El "
                     "Δpp necesario varía por línea porque cada una parte de un OEE "
                     "base distinto. Reparto 50% disponibilidad / 30% rendimiento / "
                     "20% calidad del Δpp exacto de cada línea (no 50/30/20 de una "
                     "cifra fija repetida en las 3).")]
    cols = ["linea", "oee_base", "oee_a_implementar", "mejora_total_pp",
           "mejora_disponibilidad_pp", "mejora_rendimiento_pp", "mejora_calidad_pp",
           "meta_programa_oee", "justificacion"]
    out.append(_fila_ancha(*cols, n=len(cols)))
    t = tabla_oee()
    for _, row in t.iterrows():
        out.append(_fila_ancha(*[row[c] for c in cols], n=len(cols)))
    out.append(_fila_ancha("Meta de programa (86%) es ASPIRACIONAL de largo plazo — "
                           "distinta del +5% estricto del caso de negocio actual, no "
                           "confundir ambas."))
    out.append(_fila_ancha(""))
    out.append(_fila_ancha("CRONOGRAMA DE IMPLEMENTACIÓN (atado a las 4 fases de "
                           "preoperación del CAPEX, core/finanzas_negocio.py: FASES_CAPEX)"))
    out.append(_fila_ancha("Fase", "Mes preop.", "% CAPEX fase", "Palanca",
                           "Componente OEE", "Detalle", n=6))
    for fase, mes, pct, palanca, comp, detalle in CRONOGRAMA_MEJORA_OEE:
        out.append(_fila_ancha(fase, mes, f"{pct*100:.0f}%", palanca,
                               comp or "—", detalle, n=6))
    return out


def _filas_capacidad() -> list[list]:
    out = [_fila_ancha("BLOQUE 7 · CAPACIDAD EFECTIVA vs DEMANDA (hallazgo del "
                       "archivo corregido)")]
    cols = ["linea", "demanda_2026_und", "capacidad_efectiva_und",
           "U_turnos_actuales", "capacidad_3_turnos_und", "U_con_3_turnos", "dictamen"]
    out.append(_fila_ancha(*cols, n=len(cols)))
    t = tabla_capacidad()
    for _, row in t.iterrows():
        out.append(_fila_ancha(*[row[c] for c in cols], n=len(cols)))
    out.append(_fila_ancha("L3 con 1 solo operario (sensibilidad): U=1.612 → infactible; "
                           "la celda robótica evita el 2º operario del paletizado manual."))
    out.append(_fila_ancha("Lectura: L1 y L2 son INFACTIBLES con 2 turnos → el 3er turno "
                           "es palanca del caso de negocio; L3 es factible con 1 turno "
                           "gracias a la celda robótica."))
    return out


def _filas_maquinas(src) -> list[list]:
    out = [_fila_ancha("BLOQUE 8 · MÁQUINAS Y REFERENCIAS COMERCIALES POR ETAPA "
                       "(tasas de catálogo/mercado de usados, referencia real)")]
    df = src["Maquinas_Referencias"]
    for _, row in df.iterrows():
        vals = [str(row[i]) if len(row) > i and str(row[i]) != "nan" else "" for i in range(7)]
        if any(vals):
            out.append(_fila_ancha(*vals[1:], n=6))
    out.append(_fila_ancha(""))
    out.append(_fila_ancha("Nota (decisión #15 de CLAUDE.md): el CAPEX real YA NO "
                           "incluye comprar equipos de inspección nuevos. Esto reconcilia "
                           "perfecto con el 'intercambio capex-cero de inspectoras' de "
                           "arriba — HEUFT PRIME y Linatronic 713 son equipos EXISTENTES "
                           "que se REASIGNAN entre L1/L2, no se compran nuevos."))
    return out


def _filas_glosario_referencias(src) -> list[list]:
    out = [_fila_ancha("BLOQUE 9 · GLOSARIO")]
    for _, row in src["Glosario"].iterrows():
        vals = [str(row[i]) if len(row) > i and str(row[i]) != "nan" else "" for i in range(3)]
        if vals[1]:
            out.append(_fila_ancha(vals[1], vals[2] if len(vals) > 2 else "", n=2))
    out.append(_fila_ancha(""))
    out.append(_fila_ancha("BLOQUE 10 · REFERENCIAS Y CITAS"))
    for _, row in src["Referencias"].iterrows():
        vals = [str(row[i]) if len(row) > i and str(row[i]) != "nan" else "" for i in range(3)]
        if vals[1]:
            out.append(_fila_ancha(vals[1], vals[2] if len(vals) > 2 else "", n=2))
    return out


def construir_filas() -> tuple[list[list], list[int]]:
    """Devuelve (filas, indices_1based_de_titulos_de_bloque) para formatear."""
    src = _leer_fuente()
    filas: list[list] = [
        _fila_ancha("ESTUDIO DE TIEMPOS Y OEE — PLANTA KOF FONTIBÓN (CORREGIDO Y "
                   "CONSOLIDADO) — DOCUMENTAL"),
        _fila_ancha("Fuente: Tiempos_Fontibon_Corregido.xlsx (auditoría APM, 8 hallazgos "
                   "corregidos, ver Bloque 2). DOCUMENTAL: no está conectado al ERP en "
                   "vivo — es referencia de ingeniería para el diseño del equipo. Los "
                   "KPIs VIVOS de OEE/TEEP NO se gestionan en el ERP: llegan por MQTT "
                   "según el UNS (FEMSA/+/MES/KPI/#) y se consultan en las páginas "
                   "Producción MQTT y Base de datos (tabla kpi_uns). Consolidada "
                   "2026-07: esta hoja reemplaza a Tiempos + OEE_TEEP (redundante, "
                   "borrada) — todo el contenido queda en un solo lugar."),
        _fila_ancha(""),
    ]
    bloques = [_filas_memoria(src), [_fila_ancha("")],
              _filas_correcciones(src), [_fila_ancha("")],
              _filas_parametros_tiempos(), [_fila_ancha("")],
              _filas_mlt_vsm(src), [_fila_ancha("")],
              _filas_oee(), [_fila_ancha("")],
              _filas_mejora_5pct(), [_fila_ancha("")],
              _filas_capacidad(), [_fila_ancha("")],
              _filas_maquinas(src), [_fila_ancha("")],
              _filas_glosario_referencias(src)]
    titulos_idx = []
    for b in bloques:
        if b and b[0][0].startswith("BLOQUE"):
            titulos_idx.append(len(filas) + 1)  # 1-based, antes de extender
        filas.extend(b)
    return filas, titulos_idx


def main() -> None:
    cont = Contabilidad()
    if cont.modo != "sheets":
        raise SystemExit("Sheets no esta configurado (.env) -- esta hoja no tiene "
                         "fallback local, es documental/exhibicion.")
    ss = cont._spreadsheet()
    filas, titulos_idx = construir_filas()
    ancho = max(len(f) for f in filas)
    filas = [f + [""] * (ancho - len(f)) for f in filas]

    try:
        ws = ss.worksheet("Tiempos")
        ws.resize(rows=max(len(filas) + 20, ws.row_count), cols=max(ancho, ws.col_count))
    except Exception:  # noqa: BLE001
        ws = ss.add_worksheet("Tiempos", rows=len(filas) + 20, cols=ancho)
    ws.clear()
    # RAW, no USER_ENTERED: toda la hoja es texto/numeros documentales
    # estaticos (decision #1/#17 de CLAUDE.md, NO son formulas vivas) --
    # USER_ENTERED deja que Sheets reinterprete texto que empieza con "+"
    # (p.ej. "+1.93pp A: ...") como el INICIO de una formula estilo
    # Lotus 1-2-3 y revienta en #ERROR!
    ws.update(filas, "A1", value_input_option="RAW")

    # formato: titulo general, bloques, encabezados de sub-tabla
    ws.format(f"A1:{chr(64+min(ancho,26))}1", FMT_TITULO)
    for idx in titulos_idx:
        rng = f"A{idx}:{chr(64+min(ancho,26))}{idx}"
        ws.format(rng, FMT_BLOQUE)
    ws.freeze(rows=2)

    print(f"Publicado 'Tiempos': {len(filas)} filas x {ancho} columnas, "
         f"{len(titulos_idx)} bloques.")

    try:
        ws_oee = ss.worksheet("OEE_TEEP")
        ss.del_worksheet(ws_oee)
        print("Borrada hoja 'OEE_TEEP' (redundante, contenido migrado a 'Tiempos').")
    except Exception as e:  # noqa: BLE001
        print(f"No se pudo borrar OEE_TEEP (puede que ya no exista): {e}")

    print("\nReconciliación +5% relativo por línea:")
    for lin in LINEAS:
        base = componentes_oee(lin)["OEE"]
        m = _mejora_pp_linea(lin)
        print(f"  {lin}: {base*100:.2f}% -> {base*105/100*100:.2f}% "
             f"(Δ{m['delta_total_pp']:.3f}pp = disp {m['disponibilidad_pp']:.3f} + "
             f"rend {m['rendimiento_pp']:.3f} + cal {m['calidad_pp']:.3f})")


if __name__ == "__main__":
    main()
