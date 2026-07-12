"""
Integracion RRHH: roster individual de empleados en Google Sheets (hoja
"Empleados"), con fallback a data/empleados.csv cuando Sheets no esta
configurado -- misma filosofia de resiliencia que integrations/sheets_client.py.

Complementa (no reemplaza) la hoja "Personal" del libro financiero: Personal
es el AGREGADO por rol que consume core.finanzas_negocio (via Parametros
NOMINA_OPERACION_MES / NOMINA_IMPLEMENTACION_MES); Empleados es el detalle
individual -- cada persona tiene un `rol_personal` que debe coincidir con
las categorias de Personal para poder reconciliar ambos
(core.rrhh.reconciliar_con_personal). Este modulo NUNCA escribe en la hoja
Personal.

A diferencia de Demanda/DemandaEscenario/Inventarios (rangos fijos porque las
hojas financieras las referencian con formulas), Empleados es una lista sin
formulas dependientes: se puede reemplazar completa (clear + append) sin
romper nada.
"""
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings

HOJA = "Empleados"
HOJA_PERSONAL = "Personal"
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


def leer_empleados() -> tuple[pd.DataFrame, str]:
    """Lee el roster desde la hoja Empleados; si Sheets no esta disponible
    (o falla la lectura), cae al CSV local. Devuelve (df, origen) con
    origen en {'sheets', 'csv'} para que la UI sea explicita sobre que tan
    'vivo' es el dato."""
    if _sheets_disponible():
        try:
            ws = _spreadsheet().worksheet(HOJA)
            filas = ws.get_all_records()
            if filas:
                df = pd.DataFrame(filas)
                faltan = [c for c in COLUMNAS if c not in df.columns]
                if not faltan:
                    df["salario_mensual_cop"] = pd.to_numeric(
                        df["salario_mensual_cop"], errors="coerce").fillna(0.0)
                    return df[COLUMNAS], "sheets"
        except Exception:  # noqa: BLE001 -- degradar a CSV local
            pass
    df = pd.read_csv(CSV_LOCAL)
    return df[COLUMNAS], "csv"


def publicar_empleados(df: pd.DataFrame) -> str:
    """Reemplaza el contenido de la hoja Empleados con `df` (clear+append:
    esta hoja no tiene formulas dependientes, a diferencia de Demanda/
    Inventarios). Si Sheets no esta disponible, escribe data/empleados.csv."""
    df = df[COLUMNAS].copy()
    if _sheets_disponible():
        try:
            ss = _spreadsheet()
            try:
                ws = ss.worksheet(HOJA)
            except Exception:  # noqa: BLE001
                ws = ss.add_worksheet(HOJA, rows=max(200, len(df) + 10),
                                      cols=len(COLUMNAS))
            ws.clear()
            ws.append_row(COLUMNAS)
            ws.append_rows(df.astype(object).values.tolist(),
                          value_input_option="USER_ENTERED")
            return "sheets"
        except Exception:  # noqa: BLE001
            pass
    df.to_csv(CSV_LOCAL, index=False)
    return "csv"


def agregar_empleado(**campos) -> str:
    """Agrega una persona al roster (append puro, sin releer/reescribir el
    resto). `campos` debe traer las COLUMNAS completas."""
    faltan = [c for c in COLUMNAS if c not in campos]
    if faltan:
        raise ValueError(f"faltan campos: {faltan}")
    fila = [campos[c] for c in COLUMNAS]
    if _sheets_disponible():
        try:
            ss = _spreadsheet()
            try:
                ws = ss.worksheet(HOJA)
            except Exception:  # noqa: BLE001
                ws = ss.add_worksheet(HOJA, rows=200, cols=len(COLUMNAS))
                ws.append_row(COLUMNAS)
            ws.append_row(fila, value_input_option="USER_ENTERED")
            return "sheets"
        except Exception:  # noqa: BLE001
            pass
    df = pd.read_csv(CSV_LOCAL) if CSV_LOCAL.exists() else pd.DataFrame(columns=COLUMNAS)
    df = pd.concat([df, pd.DataFrame([campos])[COLUMNAS]], ignore_index=True)
    df.to_csv(CSV_LOCAL, index=False)
    return "csv"


def _parse_moneda_cop(texto: str) -> float | None:
    """'$85.915.382' (formato COP: punto de miles) -> 85915382.0."""
    limpio = str(texto).strip().replace("$", "").replace(".", "").replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return None


def leer_nomina_personal() -> dict | None:
    """Lee de la hoja 'Personal' los totales 'Costo mensual OPERACION' /
    'Costo mensual IMPLEMENTACION' (columna 'costo total mes COP'), para que
    la pagina RRHH pueda reconciliar el roster individual contra el agregado
    que ya gobierna el motor financiero -- sin depender de
    core.finanzas_negocio (evita acoplarse a ese modulo) ni escribir nada en
    Personal. Devuelve None si Sheets no esta disponible o la hoja no tiene
    el formato esperado."""
    if not _sheets_disponible():
        return None
    try:
        ws = _spreadsheet().worksheet(HOJA_PERSONAL)
        filas = ws.get_all_values()
    except Exception:  # noqa: BLE001
        return None
    out: dict[str, float] = {}
    for fila in filas:
        if not fila or not fila[0]:
            continue
        etiqueta = fila[0].strip()
        valor = _parse_moneda_cop(fila[3]) if len(fila) > 3 else None
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
    personal = leer_nomina_personal()
    print("\nNomina segun hoja Personal:", personal or "no disponible (Sheets no conectado)")
