"""
Integracion RRHH: roster individual + agregado por rol, consolidados en UNA
hoja de Google Sheets ("RRHH"), con fallback a data/empleados.csv para el
roster cuando Sheets no esta configurado -- misma filosofia de resiliencia
que integrations/sheets_client.py.

2026-07: antes eran DOS hojas separadas ("Personal" agregado + "Empleados"
detalle, ver decision de diseno #10 de CLAUDE.md). Por pedido explicito del
dueno del proyecto ("todo lo de RRHH en una hoja bien centralizado") ahora
conviven en la MISMA hoja "RRHH", en secciones marcadas (RESUMEN / ROSTER
INDIVIDUAL / TASAS DE CARGA PRESTACIONAL / RECONCILIACION) -- la separacion
conceptual detalle-vs-agregado se mantiene (siguen siendo dos vistas
distintas para poder reconciliar una contra la otra,
`core.rrhh.reconciliar_con_personal`), solo cambio DONDE viven.

Lectura por NOMBRE de columna dentro de cada seccion (no por rango fijo),
mismo patron que `integrations/sheets_client.py: leer_capex()` /
`leer_apu_ingenieria()` -- localiza la fila marcadora de cada bloque y lee
hasta la siguiente fila en blanco. Escritura: SIEMPRE reconstruye la hoja
completa (clear + rewrite, `construir_filas_rrhh()` + `publicar_hoja_rrhh()`)
porque la seccion RESUMEN se deriva del roster -- no tiene sentido editar
solo un pedazo. Este modulo NUNCA escribe fuera de la hoja RRHH.
"""
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings
from core.rrhh import (ARL_CLASE_POR_ROL, ARL_POR_CLASE,
                       COMPONENTES_PRESTACIONALES_COMUNES,
                       desglosar_costo_empleador, resumen_por_rol)

HOJA = "RRHH"
MARCA_RESUMEN = "RESUMEN POR ROL"
MARCA_ROSTER = "ROSTER INDIVIDUAL"
MARCA_TASAS = "TASAS DE CARGA PRESTACIONAL (referencia -- validar contra normativa vigente)"
MARCA_RECON = "RECONCILIACION ROSTER vs. RESUMEN"
COLUMNAS = ["cedula", "nombre", "cargo", "rol_personal", "linea", "turno",
           "fase", "fecha_ingreso", "estado", "salario_mensual_cop",
           "telefono", "email"]
CSV_LOCAL = settings.DATA_DIR / "empleados.csv"


def _sheets_disponible() -> bool:
    return bool(settings.SHEETS_ENABLED and not settings.DRY_RUN_FORZADO)


def _spreadsheet():
    import gspread
    gc = gspread.service_account(filename=settings.GOOGLE_SA_JSON)
    return gc.open_by_key(settings.SHEETS_SPREADSHEET_ID)


def _bloque(vals: list[list[str]], marca: str) -> tuple[int, list[str]] | None:
    """Ubica la fila con `marca` en la columna A y devuelve
    (indice_fila_encabezado_0based, encabezados) -- el encabezado es la fila
    inmediatamente debajo de la marca. None si no se encuentra."""
    for i, fila in enumerate(vals):
        if fila and fila[0].strip() == marca:
            if i + 1 < len(vals):
                return i + 1, [c.strip() for c in vals[i + 1]]
    return None


def _filas_de_bloque(vals: list[list[str]], idx_encabezado: int) -> list[list[str]]:
    """Filas de datos desde justo debajo del encabezado hasta la primera
    fila en blanco (columna A vacia)."""
    out = []
    for fila in vals[idx_encabezado + 1:]:
        if not fila or not str(fila[0]).strip():
            break
        out.append(fila)
    return out


def leer_empleados() -> tuple[pd.DataFrame, str]:
    """Lee el roster desde la seccion ROSTER INDIVIDUAL de la hoja RRHH; si
    Sheets no esta disponible (o falla la lectura), cae al CSV local.
    Devuelve (df, origen) con origen en {'sheets', 'csv'}."""
    if _sheets_disponible():
        try:
            ws = _spreadsheet().worksheet(HOJA)
            vals = ws.get_all_values()
            b = _bloque(vals, MARCA_ROSTER)
            if b is not None:
                idx_enc, encabezados = b
                filas = _filas_de_bloque(vals, idx_enc)
                if filas:
                    df = pd.DataFrame(filas, columns=encabezados[:len(filas[0])]
                                      if len(encabezados) >= len(filas[0])
                                      else encabezados + [""] * (len(filas[0]) - len(encabezados)))
                    faltan = [c for c in COLUMNAS if c not in df.columns]
                    if not faltan:
                        df["salario_mensual_cop"] = pd.to_numeric(
                            df["salario_mensual_cop"], errors="coerce").fillna(0.0)
                        return df[COLUMNAS], "sheets"
        except Exception:  # noqa: BLE001 -- degradar a CSV local
            pass
    df = pd.read_csv(CSV_LOCAL)
    return df[COLUMNAS], "csv"


def _col_letra(n: int) -> str:
    letras = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        letras = chr(65 + r) + letras
    return letras


def construir_filas_rrhh(df: pd.DataFrame) -> list[list]:
    """Reconstruye TODAS las filas de la hoja RRHH (los 4 bloques) a partir
    del roster individual `df`. El RESUMEN por rol (conteo, costo unitario,
    costo total) y el pie (Costo mensual OPERACION/IMPLEMENTACION) se
    escriben como FORMULAS VIVAS (COUNTIFS/SUMIFS) sobre el bloque ROSTER
    INDIVIDUAL de la MISMA hoja -- si el usuario edita el roster directo en
    Sheets (agrega una persona, cambia un salario), el resumen y los totales
    que alimentan `Parametros!nomina_operacion_mes`/`nomina_implementacion_mes`
    recalculan solos, sin volver a correr este script. `salario_base_cop`/
    `factor_prestacional_pct` quedan como valores de exhibicion calculados al
    publicar (no alimentan ningun otro calculo, mismo criterio que el AIU de
    APU_Ingenieria). Ancho fijo de 9 columnas (la seccion mas ancha, RESUMEN)."""
    N = 9

    def f(*vals):
        v = list(vals)
        return v + [""] * (N - len(v))

    resumen = resumen_por_rol(df)
    n_roles = len(resumen)
    fila_resumen_header = 5           # 1-based: fila del encabezado RESUMEN
    fila_rol_inicio = fila_resumen_header + 1
    fila_rol_fin = fila_rol_inicio + n_roles - 1
    fila_operacion = fila_rol_fin + 2
    fila_implementacion = fila_operacion + 1
    fila_roster_marca = fila_implementacion + 2
    fila_roster_header = fila_roster_marca + 1
    fila_roster_inicio = fila_roster_header + 1
    fila_roster_fin = fila_roster_inicio + len(df) - 1

    col_rol = "D"       # ROSTER: rol_personal
    col_estado = "I"    # ROSTER: estado
    col_salario = "J"   # ROSTER: salario_mensual_cop
    rango_rol = f"${col_rol}${fila_roster_inicio}:${col_rol}${fila_roster_fin}"
    rango_estado = f"${col_estado}${fila_roster_inicio}:${col_estado}${fila_roster_fin}"
    rango_salario = f"${col_salario}${fila_roster_inicio}:${col_salario}${fila_roster_fin}"

    filas = [
        f("RRHH — NÓMINA Y DOTACIÓN (Bogotá, consolidado)"),
        f("Roster individual (detalle) + agregado por rol (resumen, con fórmulas vivas "
          "sobre el roster) en una sola hoja. 'salario_mensual_cop' es el COSTO TOTAL "
          "EMPLEADOR (ya incluye carga prestacional) — ver sección de tasas más abajo "
          "para el desglose de abajo hacia arriba. Operación alimenta el ER; "
          "Implementación (equipo ULogix) va al flujo pre-operativo."),
        f(""),
    ]

    filas.append(f(MARCA_RESUMEN))
    filas.append(f("rol_personal", "conteo", "fase", "arl_clase", "salario_base_cop",
                   "factor_prestacional_pct", "costo_unitario_empleador_cop",
                   "costo_total_mes_cop", "comentario"))
    comentarios = {
        "Operarios de linea (3 turnos)": "6 por turno; el 3er turno L1/L2 es palanca "
                                        "del hallazgo de capacidad (ver hoja Tiempos)",
        "Supervisores de turno": "Cubren 3 turnos",
        "Supervisor de planta": "Principal",
        "Equipo diseno y desarrollo ULogix": "Meses pre-operativos (1-4)",
    }
    for i, (_, r) in enumerate(resumen.iterrows()):
        fila_actual = fila_rol_inicio + i
        rol = r["rol_personal"]
        clase = ARL_CLASE_POR_ROL.get(rol, "IV")
        d = desglosar_costo_empleador(r["costo_unitario_cop"], clase)
        formula_conteo = (f"=COUNTIFS({rango_rol};A{fila_actual};{rango_estado};\"activo\")")
        formula_costo_total = (f"=SUMIFS({rango_salario};{rango_rol};A{fila_actual};"
                               f"{rango_estado};\"activo\")")
        formula_costo_unitario = f"=IF(B{fila_actual}=0;0;H{fila_actual}/B{fila_actual})"
        filas.append(f(rol, formula_conteo, r["fase"], clase,
                       d["salario_base_cop"], d["factor_prestacional_pct"],
                       formula_costo_unitario, formula_costo_total,
                       comentarios.get(rol, "")))
    filas.append(f(""))
    rango_fase_resumen = f"$C${fila_rol_inicio}:$C${fila_rol_fin}"
    rango_costo_resumen = f"$H${fila_rol_inicio}:$H${fila_rol_fin}"
    filas.append(f("Costo mensual OPERACION (→ ER)", "", "", "",
                   f'=SUMIF({rango_fase_resumen};"Operacion";{rango_costo_resumen})'))
    filas.append(f("Costo mensual IMPLEMENTACION (→ pre-op)", "", "", "",
                   f'=SUMIF({rango_fase_resumen};"Implementacion";{rango_costo_resumen})'))
    filas.append(f(""))

    filas.append(f(MARCA_ROSTER))
    filas.append(COLUMNAS + [""] * (N - len(COLUMNAS)))
    for _, r in df.iterrows():
        filas.append([r[c] for c in COLUMNAS] + [""] * (N - len(COLUMNAS)))
    filas.append(f(""))

    filas.append(f(MARCA_TASAS))
    filas.append(f("componente", "tasa_pct", "tipo", "base"))
    for comp, tasa in COMPONENTES_PRESTACIONALES_COMUNES.items():
        filas.append(f(comp, round(tasa * 100, 3), "común (todas las clases ARL)",
                       "salario base"))
    for clase, tasa in ARL_POR_CLASE.items():
        filas.append(f(f"arl_clase_{clase}", round(tasa * 100, 3),
                       "ARL (según clasificación de riesgo del rol)", "salario base"))
    filas.append(f("SENA/ICBF", 0.0,
                   "exonerado (Ley 1607/2012, salario < 10 SMMLV) — validar vigencia",
                   "—"))
    filas.append(f("Nota: costo_total_empleador = salario_base × (1 + Σcomunes + "
                   "ARL_clase). Tasas de referencia de mercado/histórico colombiano, "
                   "documentadas para validar contra la normativa vigente antes de "
                   "usarse en nómina real — mismo criterio que el AIU de la hoja "
                   "APU_Ingenieria."))
    filas.append(f(""))

    filas.append(f(MARCA_RECON))
    filas.append(f("fase", "roster_cop", "resumen_cop", "diferencia_cop", "estado"))
    costo_fase = df[df["estado"] == "activo"].groupby("fase")["salario_mensual_cop"].sum()
    for fase in ["Operacion", "Implementacion"]:
        roster_val = costo_fase.get(fase, 0.0)
        resumen_val = resumen[resumen["fase"] == fase]["costo_total_mes_cop"].sum()
        diff = roster_val - resumen_val
        filas.append(f(fase, round(roster_val), round(resumen_val), round(diff),
                       "✅ cuadra" if abs(diff) < 1 else "⚠️ difiere"))

    return filas


def publicar_hoja_rrhh(df: pd.DataFrame) -> str:
    """Reconstruye la hoja RRHH completa (clear + rewrite) a partir del
    roster `df` -- RESUMEN/reconciliación se recalculan solos. Devuelve
    'sheets' o 'csv' (fallback: solo persiste el roster en el CSV local,
    RESUMEN/reconciliación no tienen destino sin Sheets)."""
    if _sheets_disponible():
        try:
            ss = _spreadsheet()
            filas = construir_filas_rrhh(df)
            ancho = max(len(f) for f in filas)
            try:
                ws = ss.worksheet(HOJA)
                ws.resize(rows=max(len(filas) + 20, ws.row_count),
                         cols=max(ancho, ws.col_count))
            except Exception:  # noqa: BLE001
                ws = ss.add_worksheet(HOJA, rows=len(filas) + 20, cols=ancho)
            ws.clear()
            ws.update(filas, "A1", value_input_option="USER_ENTERED")
            return "sheets"
        except Exception:  # noqa: BLE001
            pass
    df[COLUMNAS].to_csv(CSV_LOCAL, index=False)
    return "csv"


def publicar_empleados(df: pd.DataFrame) -> str:
    """Compatibilidad: reemplaza el roster completo y reconstruye la hoja
    RRHH entera (RESUMEN se deriva del roster nuevo)."""
    return publicar_hoja_rrhh(df[COLUMNAS].copy())


def agregar_empleado(**campos) -> str:
    """Agrega una persona al roster y reconstruye la hoja RRHH completa
    (RESUMEN cambia si el conteo/costo del rol cambia)."""
    faltan = [c for c in COLUMNAS if c not in campos]
    if faltan:
        raise ValueError(f"faltan campos: {faltan}")
    df, _ = leer_empleados()
    nuevo = pd.concat([df, pd.DataFrame([campos])[COLUMNAS]], ignore_index=True)
    return publicar_hoja_rrhh(nuevo)


def leer_nomina_personal() -> dict | None:
    """Lee de la seccion RESUMEN de la hoja RRHH los totales 'Costo mensual
    OPERACION' / 'Costo mensual IMPLEMENTACION', para que la pagina RRHH
    pueda reconciliar el roster individual contra el agregado que ya
    gobierna el motor financiero -- sin depender de core.finanzas_negocio
    (evita acoplarse a ese modulo) ni escribir nada en RRHH. Devuelve None
    si Sheets no esta disponible o la hoja no tiene el formato esperado."""
    if not _sheets_disponible():
        return None
    try:
        ws = _spreadsheet().worksheet(HOJA)
        filas = ws.get_all_values()
    except Exception:  # noqa: BLE001
        return None
    out: dict[str, float] = {}
    for fila in filas:
        if not fila or not fila[0]:
            continue
        etiqueta = fila[0].strip()
        valor = None
        for celda in fila[1:]:
            v = str(celda).strip().replace("$", "").replace(".", "").replace(",", "")
            if v:
                try:
                    valor = float(v)
                except ValueError:
                    pass
        if valor is None:
            continue
        if etiqueta.startswith("Costo mensual OPERACION"):
            out["nomina_operacion_mes"] = valor
        elif etiqueta.startswith("Costo mensual IMPLEMENTACION"):
            out["nomina_implementacion_mes"] = valor
    return out or None


if __name__ == "__main__":
    df, origen = leer_empleados()
    print(f"{len(df)} empleados cargados (origen: {origen})")
    print(df.head(10).to_string(index=False))
    nomina = leer_nomina_personal()
    print("\nNomina segun hoja RRHH:", nomina or "no disponible (Sheets no conectado)")
