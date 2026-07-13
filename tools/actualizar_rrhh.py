"""
Publica la hoja consolidada 'RRHH' (RESUMEN por rol + ROSTER individual +
TASAS de carga prestacional + RECONCILIACION, ver
integrations/rrhh_client.py) a partir de data/empleados.csv, y borra las
hojas 'Personal'/'Empleados' del libro (redundantes tras la consolidacion,
decision de diseno #10 actualizada de CLAUDE.md).

Uso: python tools/actualizar_rrhh.py
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd

from config import settings
from integrations.rrhh_client import COLUMNAS, publicar_hoja_rrhh
from integrations.sheets_client import Contabilidad


def main() -> None:
    cont = Contabilidad()
    if cont.modo != "sheets":
        raise SystemExit("Sheets no esta configurado (.env).")
    df = pd.read_csv(settings.DATA_DIR / "empleados.csv")[COLUMNAS]
    destino = publicar_hoja_rrhh(df)
    print(f"Publicado 'RRHH': {len(df)} personas (destino: {destino}).")

    ss = cont._spreadsheet()
    for nombre in ["Personal", "Empleados"]:
        try:
            ws = ss.worksheet(nombre)
            ss.del_worksheet(ws)
            print(f"Borrada hoja '{nombre}' (redundante, contenido migrado a 'RRHH').")
        except Exception as e:  # noqa: BLE001
            print(f"No se pudo borrar '{nombre}' (puede que ya no exista): {e}")


if __name__ == "__main__":
    main()
