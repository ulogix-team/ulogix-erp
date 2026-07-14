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
from core.tiempos_oee import (DATOS, DATOS_DESPUES, MAQUINAS_ESTADO, LINEAS,
                              CRONOGRAMA_MEJORA_OEE,
                              componentes_oee, tabla_capacidad,
                              tabla_capacidad_comparada, tabla_oee,
                              tabla_tiempos, _mejora_pp_linea)

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


def _valor_fuente(valor):
    """Conserva numericos de Excel como numeros (no strings tipo fecha)."""
    import pandas as pd
    if pd.isna(valor):
        return ""
    if hasattr(valor, "item") and not isinstance(valor, str):
        try:
            return valor.item()
        except ValueError:
            pass
    return valor


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
    out = [_fila_ancha("BLOQUE 3 · ANTES DEL PROYECTO — PARÁMETROS Y TIEMPOS BASE "
                       "MEDIDOS (fórmulas APM: Tc/T_D/Takt/Q/Tb/Tp/Rp_lote/MLT/capacidad)")]
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
        vals = [_valor_fuente(row[i]) if len(row) > i else "" for i in range(7)]
        if any(vals):
            out.append(_fila_ancha(*vals[1:], n=6))
    return out


def _filas_oee(demanda=None) -> list[list]:
    out = [_fila_ancha("BLOQUE 5 · OEE BOTTOM-UP (base medido, valida 75-78% de la "
                       "visita técnica) — A=Ter/Tep · SE=Rp_real/Rp_diseño · RE=microparos "
                       "medidos · PE=RE×SE · Q=1−rechazo · OEE=A×PE×Q")]
    cols = ["linea", "producto", "A_disponibilidad", "SE_tasa", "RE_microparos",
           "PE_desempeno", "Q_calidad", "oee_base", "carga_calendario", "teep",
           "tt_turno_h", "tip_parada_inherente_h", "tnp_parada_no_programada_h"]
    out.append(_fila_ancha(*cols, n=len(cols)))
    t = tabla_oee()
    for _, row in t.iterrows():
        valores = [row[c] for c in cols[:10]] + [8.0, 1.1667, 0.75]
        out.append(_fila_ancha(*valores, n=len(cols)))
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
    out = [_fila_ancha("BLOQUE 7 · CAPACIDAD Y FACTIBILIDAD — ANTES vs DESPUÉS DEL "
                       "PROYECTO (misma demanda; cambian equipos, OEE, tiempos y turnos)")]
    cols = ["linea", "demanda_anual_und", "equipo_antes", "equipo_despues",
            "rp_antes_uph", "rp_despues_uph", "ciclo_antes_s", "ciclo_despues_s",
            "oee_antes", "oee_despues", "turnos_antes", "turnos_despues",
            "dias_operativos_ano", "q_antes_und", "q_despues_und",
            "mlt_antes_h", "mlt_despues_h", "capacidad_antes_und",
            "capacidad_despues_mismos_turnos_und", "capacidad_despues_und",
            "U_antes", "U_despues", "incremento_capacidad_pct",
            "dictamen_antes", "dictamen_despues", "condicion_proyecto"]
    out.append(_fila_ancha(*cols, n=len(cols)))
    t = tabla_capacidad_comparada()
    for _, row in t.iterrows():
        valores = row.to_dict()
        valores["dias_operativos_ano"] = DATOS[row["linea"]]["dias_ano"]
        out.append(_fila_ancha(*[valores[c] for c in cols], n=len(cols)))
    out.append(_fila_ancha("La capacidad DESPUÉS con los mismos turnos separa el efecto "
                           "tecnológico/OEE del efecto calendario. El proyecto completo "
                           "usa 3 turnos en L1/L2 y 1 en L3."))
    out.append(_fila_ancha("MLT DESPUÉS es una proyección: conserva las esperas del VSM "
                           "base y recalcula la corrida con el nuevo cuello/lote. Debe "
                           "reemplazarse por la medición SAT/comisionamiento."))
    return out


def _filas_maquinas(src) -> list[list]:
    out = [_fila_ancha("BLOQUE 8 · MÁQUINAS Y REFERENCIAS COMERCIALES POR ETAPA "
                       "(tasas de catálogo/mercado de usados, referencia real)")]
    df = src["Maquinas_Referencias"]
    for _, row in df.iterrows():
        vals = [_valor_fuente(row[i]) if len(row) > i else "" for i in range(7)]
        if any(vals):
            out.append(_fila_ancha(*vals[1:], n=6))
    out.append(_fila_ancha(""))
    out.append(_fila_ancha("ESTADO DESPUÉS DEL PROYECTO — EQUIPO CRÍTICO Y ALCANCE REAL"))
    out.append(_fila_ancha("línea", "equipo antes", "equipo después", "intervención"))
    for lin in LINEAS:
        out.append(_fila_ancha(lin, MAQUINAS_ESTADO[lin]["antes"],
                               MAQUINAS_ESTADO[lin]["despues"],
                               MAQUINAS_ESTADO[lin]["intervencion"], n=4))
    out.append(_fila_ancha("Nota L2: el proyecto ahora incorpora una llenadora KRONES "
                           "usada de 18.000 u/h y una Variopac usada; la tasa de diseño "
                           "se dimensiona con holgura sobre la demanda y el OEE objetivo."))
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
    # USER_ENTERED es necesario para que Sheets conserve formulas vivas. Los
    # textos documentales que empiezan con '=' o '+' se escapan primero para
    # que no se interpreten como formulas estilo Lotus 1-2-3.
    for fila in filas:
        for i, valor in enumerate(fila):
            if isinstance(valor, str) and valor.startswith(("=", "+")):
                fila[i] = "'" + valor
    _convertir_calculos_a_formulas(filas)
    return filas, titulos_idx


def _fila_encabezado(filas: list[list], columnas: list[str]) -> int:
    for i, fila in enumerate(filas):
        if fila[:len(columnas)] == columnas:
            return i
    raise ValueError(f"No se encontro encabezado {columnas}")


def _convertir_calculos_a_formulas(filas: list[list]) -> None:
    """Convierte los cuatro bloques cuantitativos en un modelo vivo.

    Las tasas, turnos, calendario, microparos, calidad, tiempos de parada,
    pallets y unidades/pallet siguen siendo entradas editables. Todo valor
    derivado se expresa como formula y la capacidad toma la demanda viva de
    la hoja Demanda.
    """
    h_t = _fila_encabezado(filas, ["linea", "producto", "rp_nominal_uph"])
    h_o = _fila_encabezado(filas, ["linea", "producto", "A_disponibilidad"])
    h_m = _fila_encabezado(filas, ["linea", "oee_base", "oee_a_implementar"])
    h_c = _fila_encabezado(filas, ["linea", "demanda_anual_und",
                                   "equipo_antes", "equipo_despues"])
    demanda_col = {"L1": "D", "L2": "E", "L3": "F"}

    for offset in range(1, 4):
        rt, ro, rm, rc = (h_t + offset + 1, h_o + offset + 1,
                          h_m + offset + 1, h_c + offset + 1)
        ft, fo, fm, fc = (filas[h_t + offset], filas[h_o + offset],
                          filas[h_m + offset], filas[h_c + offset])
        linea = str(ft[0])

        # Bloque 3: estudio de tiempos.
        ft[4] = f"=3600/C{rt}"
        ft[9] = f"=K{rt}*L{rt}"
        ft[12] = f"=I{rt}/60+J{rt}*E{rt}/3600"
        ft[13] = f"=M{rt}*3600/J{rt}"
        ft[14] = f"=3600/N{rt}"
        ft[15] = f"=B{(56, 69, 79)[offset - 1]}"
        ft[16] = f"=C{rt}*F{rt}*G{rt}*H{rt}*H{ro}"

        # Bloque 5: OEE bottom-up. K:M son entradas de tiempos de parada.
        fo[2] = f"=(K{ro}-L{ro}-M{ro})/(K{ro}-L{ro})"
        fo[3] = f"=C{rt}/D{rt}"
        fo[5] = f"=D{ro}*E{ro}"
        fo[7] = f"=C{ro}*F{ro}*G{ro}"
        fo[8] = f"=F{rt}*G{rt}*H{rt}/(24*365)"
        fo[9] = f"=H{ro}*I{ro}"

        # Bloque 6: mejora estricta relativa y reparto del delta.
        fm[1] = f"=H{ro}"
        fm[2] = f"=B{rm}*(105/100)"
        fm[3] = f"=(C{rm}-B{rm})*100"
        fm[4] = f"=D{rm}*(50/100)"
        fm[5] = f"=D{rm}*(30/100)"
        fm[6] = f"=D{rm}*(20/100)"

        # Bloque 7: comparacion viva ANTES vs DESPUES. E/F/K/L/M son
        # entradas de ingenieria (tasas, turnos y calendario); lo demas es
        # formula o referencia a los bloques base/OEE.
        dc = demanda_col[linea]
        fc[1] = f"=SUM(Demanda!{dc}$5:{dc}$16)"
        fc[6] = f"=3600/E{rc}"
        fc[7] = f"=3600/F{rc}"
        fc[8] = f"=H{ro}"
        fc[9] = f"=C{rm}"
        fc[13] = f"=J{rt}"
        fc[14] = f"=ROUND(F{rc}*G{rt}*J{rc}/L{rt};0)*L{rt}"
        fc[15] = f"=P{rt}"
        fc[16] = f"=P{rc}-(N{rc}-1)*G{rc}/3600+(O{rc}-1)*H{rc}/3600"
        fc[17] = f"=E{rc}*K{rc}*G{rt}*M{rc}*I{rc}"
        fc[18] = f"=F{rc}*K{rc}*G{rt}*M{rc}*J{rc}"
        fc[19] = f"=F{rc}*L{rc}*G{rt}*M{rc}*J{rc}"
        fc[20] = f"=B{rc}/R{rc}"
        fc[21] = f"=B{rc}/T{rc}"
        fc[22] = f"=T{rc}/R{rc}-1"
        fc[23] = f'=IF(U{rc}>1;"INFACTIBLE";"Factible")'
        fc[24] = f'=IF(V{rc}>1;"INFACTIBLE";"Factible")'

    # Bloque 4: conversion h→s y MLT a partir del VSM editable.
    for inicio, fin, resumen, rt in ((47, 55, 56, 37), (59, 68, 69, 38),
                                     (72, 78, 79, 39)):
        for r in range(inicio, fin + 1):
            filas[r - 1][4] = f"=D{r}*3600"
        filas[resumen - 1][1] = (f"=(I{rt}*60+SUM(B{inicio}:B{fin})+"
                                  f"SUM(E{inicio}:E{fin})+(J{rt}-1)*E{rt})/3600")

    # Bloque 8: ciclo comercial derivado de la tasa cuando esta es numerica.
    for i, fila in enumerate(filas, start=1):
        if len(fila) > 3 and isinstance(fila[2], (int, float)):
            if 115 <= i <= 136:
                fila[3] = f"=3600/C{i}"


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
    ws.update(filas, "A1", value_input_option="USER_ENTERED")

    # formato: titulo general, bloques, encabezados de sub-tabla
    ws.format(f"A1:{chr(64+min(ancho,26))}1", FMT_TITULO)
    for idx in titulos_idx:
        rng = f"A{idx}:{chr(64+min(ancho,26))}{idx}"
        ws.format(rng, FMT_BLOQUE)
    # El bloque comparativo debe conservar precision visible: sin formato,
    # Sheets redondea MLT 16,98 a "17" y oculta parte del antes/despues.
    h_cap = _fila_encabezado(filas, ["linea", "demanda_anual_und",
                                     "equipo_antes", "equipo_despues"]) + 1
    r_ini, r_fin = h_cap + 1, h_cap + 3
    ws.format(f"G{r_ini}:H{r_fin}",
              {"numberFormat": {"type": "NUMBER", "pattern": "0.000"}})
    ws.format(f"I{r_ini}:J{r_fin}",
              {"numberFormat": {"type": "PERCENT", "pattern": "0.0%"}})
    ws.format(f"P{r_ini}:Q{r_fin}",
              {"numberFormat": {"type": "NUMBER", "pattern": "0.00"}})
    ws.format(f"R{r_ini}:T{r_fin}",
              {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
    ws.format(f"U{r_ini}:W{r_fin}",
              {"numberFormat": {"type": "PERCENT", "pattern": "0.0%"}})
    ws.freeze(rows=2)

    # Vista corta y legible: Tiempos conserva la auditoria completa; esta
    # portada evita recorrer 26 columnas para tomar decisiones de capacidad.
    resumen = [["TIEMPOS — RESUMEN EJECUTIVO ANTES vs DESPUES", "", "", "", "", "", "", "", "", "", "", "", ""],
               ["Los tiempos base/OEE medidos gobiernan ANTES; los equipos y OEE de diseño gobiernan DESPUES. L3 conserva la llenadora.", "", "", "", "", "", "", "", "", "", "", "", ""],
               [],
               ["linea", "producto", "equipo antes", "equipo despues", "tasa antes", "tasa despues",
                "OEE antes", "OEE despues", "demanda anual", "capacidad antes", "capacidad despues",
                "utilizacion antes", "utilizacion despues", "dictamen despues"]]
    comp = tabla_capacidad_comparada()
    for _, r in comp.iterrows():
        resumen.append([r["linea"], DATOS[r["linea"]]["producto"], r["equipo_antes"],
                        r["equipo_despues"], r["rp_antes_uph"], r["rp_despues_uph"],
                        r["oee_antes"], r["oee_despues"], r["demanda_anual_und"],
                        r["capacidad_antes_und"], r["capacidad_despues_und"],
                        r["U_antes"], r["U_despues"], r["dictamen_despues"]])
    resumen += [[], ["Lectura de ingenieria"],
                ["L1", "Encajonadora 30x30 + llenadora KRONES usada 44k + GANTRY compartido"],
                ["L2", "Llenadora KRONES usada 18k + Variopac + el mismo GANTRY alternado con L1"],
                ["L3", "Solo celda robotica; llenadora existente 600 gfn/h es suficiente"]]
    try:
        wr = ss.worksheet("Tiempos_Resumen")
    except Exception:  # noqa: BLE001
        wr = ss.add_worksheet("Tiempos_Resumen", rows=50, cols=16)
    wr.clear(); wr.update(resumen, "A1", value_input_option="USER_ENTERED")
    wr.format("A1:N1", FMT_TITULO); wr.format("A4:N4", FMT_ENCAB)
    wr.format("G5:H7", {"numberFormat": {"type": "PERCENT", "pattern": "0.0%"}})
    wr.format("L5:M7", {"numberFormat": {"type": "PERCENT", "pattern": "0.0%"}})
    wr.freeze(rows=4, cols=1)

    print(f"Publicado 'Tiempos': {len(filas)} filas x {ancho} columnas, "
         f"{len(titulos_idx)} bloques + portada 'Tiempos_Resumen'.")

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
