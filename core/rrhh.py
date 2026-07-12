"""
RRHH -- dotacion y costo de personal, a partir del roster individual.

Modulo puro (sin Streamlit): recibe el roster de empleados (DataFrame, una
fila por persona -- ver integrations/rrhh_client.py para la lectura desde la
hoja "Empleados" de Sheets) y calcula agregados de dotacion y costo por rol,
linea y turno.

La hoja "Personal" del libro financiero (rol/conteo/costo_unitario/
costo_total/fase) es el AGREGADO que hoy consume core.finanzas_negocio via
Parametros (NOMINA_OPERACION_MES / NOMINA_IMPLEMENTACION_MES); "Empleados"
es el detalle individual. Cada persona tiene un `rol_personal` que debe
coincidir con las categorias de "Personal" para poder reconciliar ambos
(`reconciliar_con_personal`) -- si no reconcilia, alguien desincronizo el
detalle (Empleados) del agregado (Personal) y hay que corregir uno de los
dos a mano en Sheets.
"""
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

COLUMNAS_REQUERIDAS = ["cedula", "nombre", "cargo", "rol_personal", "linea",
                       "turno", "fase", "fecha_ingreso", "estado",
                       "salario_mensual_cop", "telefono", "email"]
ESTADOS_VALIDOS = {"activo", "inactivo", "vacaciones", "incapacidad"}


def validar_roster(df: pd.DataFrame) -> list[str]:
    """Problemas encontrados en el roster (lista vacia si esta OK): columnas
    faltantes, cedulas duplicadas o estados fuera del vocabulario esperado."""
    problemas = []
    faltan = [c for c in COLUMNAS_REQUERIDAS if c not in df.columns]
    if faltan:
        problemas.append(f"faltan columnas: {faltan}")
        return problemas
    dup = df["cedula"][df["cedula"].astype(str).duplicated()].astype(str).tolist()
    if dup:
        problemas.append(f"cedulas duplicadas: {dup}")
    invalidos = df[~df["estado"].isin(ESTADOS_VALIDOS)]
    if len(invalidos):
        problemas.append(f"{len(invalidos)} fila(s) con estado invalido "
                         f"(valido: {sorted(ESTADOS_VALIDOS)})")
    return problemas


def resumen_por_rol(df: pd.DataFrame) -> pd.DataFrame:
    """Dotacion y costo por rol+fase -- debe reconciliar con la hoja
    Personal del libro financiero (misma agrupacion que esa hoja usa)."""
    activos = df[df["estado"] == "activo"]
    r = (activos.groupby(["rol_personal", "fase"])
         .agg(conteo=("cedula", "count"),
              costo_total_mes_cop=("salario_mensual_cop", "sum"))
         .reset_index())
    r["costo_unitario_cop"] = r["costo_total_mes_cop"] / r["conteo"]
    return r.sort_values(["fase", "rol_personal"]).reset_index(drop=True)


def resumen_por_linea(df: pd.DataFrame) -> pd.DataFrame:
    """Dotacion por linea+turno -- solo roles operativos (linea in L1/L2/L3),
    para cruzar contra los turnos configurados en parametros_planta.json."""
    activos = df[(df["estado"] == "activo") & (df["linea"].isin(["L1", "L2", "L3"]))]
    return (activos.groupby(["linea", "turno"])
            .agg(dotacion=("cedula", "count"))
            .reset_index()
            .sort_values(["linea", "turno"]).reset_index(drop=True))


def costo_mensual_por_fase(df: pd.DataFrame) -> dict[str, float]:
    activos = df[df["estado"] == "activo"]
    return activos.groupby("fase")["salario_mensual_cop"].sum().to_dict()


def reconciliar_con_personal(df: pd.DataFrame, nomina_operacion_mes: float,
                             nomina_implementacion_mes: float,
                             tolerancia_cop: float = 1.0) -> dict:
    """Compara el costo agregado del roster individual (Empleados) contra
    los totales que hoy gobiernan el motor financiero (hoja Personal /
    Parametros NOMINA_OPERACION_MES / NOMINA_IMPLEMENTACION_MES). Sirve para
    detectar si el detalle (Empleados) y el agregado (Personal) se
    desincronizaron -- p.ej. alguien agrego una persona en Empleados pero no
    actualizo el conteo/costo en Personal, o viceversa."""
    costo = costo_mensual_por_fase(df)
    op = costo.get("Operacion", 0.0)
    impl = costo.get("Implementacion", 0.0)
    return {
        "operacion_roster_cop": op,
        "operacion_personal_cop": nomina_operacion_mes,
        "operacion_diferencia_cop": op - nomina_operacion_mes,
        "operacion_reconciliado": abs(op - nomina_operacion_mes) <= tolerancia_cop,
        "implementacion_roster_cop": impl,
        "implementacion_personal_cop": nomina_implementacion_mes,
        "implementacion_diferencia_cop": impl - nomina_implementacion_mes,
        "implementacion_reconciliado": abs(impl - nomina_implementacion_mes) <= tolerancia_cop,
    }


if __name__ == "__main__":
    from config import settings
    df = pd.read_csv(settings.DATA_DIR / "empleados.csv")
    problemas = validar_roster(df)
    print(f"{len(df)} empleados · roster {'OK' if not problemas else 'con problemas: ' + str(problemas)}")
    print("\nPor rol:")
    print(resumen_por_rol(df).to_string(index=False))
    print("\nPor linea/turno:")
    print(resumen_por_linea(df).to_string(index=False))
    costo = costo_mensual_por_fase(df)
    print("\nCosto mensual por fase:", {k: f"${v:,.0f}" for k, v in costo.items()})
    rec = reconciliar_con_personal(df, 85_915_382.0, 87_161_760.0)
    print("\nReconciliacion vs. hoja Personal (valores de referencia):")
    print(f"  Operacion: roster ${rec['operacion_roster_cop']:,.0f} vs Personal "
         f"${rec['operacion_personal_cop']:,.0f} -> {'OK' if rec['operacion_reconciliado'] else 'DESCUADRADO'}")
    print(f"  Implementacion: roster ${rec['implementacion_roster_cop']:,.0f} vs Personal "
         f"${rec['implementacion_personal_cop']:,.0f} -> {'OK' if rec['implementacion_reconciliado'] else 'DESCUADRADO'}")
