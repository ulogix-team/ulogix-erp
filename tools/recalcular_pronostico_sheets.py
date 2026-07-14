"""Recalcula el modelo con inputs de Sheets y publica todos sus derivados.

Se ejecuta dentro del servicio Docker, donde SciPy/statsmodels y las variables
de hilos BLAS tienen un entorno reproducible.
"""
from __future__ import annotations

import sys
from pathlib import Path

import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.forecast import pronostico_base  # noqa: E402
from integrations.sheets_client import Contabilidad  # noqa: E402


def main() -> None:
    cli = Contabilidad()
    res = pronostico_base()
    cli.publicar_tabla_externa("Forecast_Pronostico_Mensual", res.mensual)
    cli.publicar_tabla_externa("Forecast_Pronostico_Trimestral", res.trimestral)
    cli.publicar_tabla_externa("Forecast_Metricas", res.metricas)
    cfg = cli.leer_hoja("Forecast_Configuracion")
    cfg = cfg[~cfg["clave"].isin(["resultado_supuestos", "resultado_validacion"])]
    extra = pd.DataFrame([
        {"clave": "resultado_supuestos",
         "json": json.dumps(res.supuestos, ensure_ascii=False, default=str,
                            separators=(",", ":"))},
        {"clave": "resultado_validacion",
         "json": json.dumps(res.validacion, ensure_ascii=False, default=str,
                            separators=(",", ":"))},
    ])
    cli.publicar_tabla_externa("Forecast_Configuracion",
                               pd.concat([cfg, extra], ignore_index=True))
    cli.publicar_demanda(res.mensual, "Base")
    print(f"Pronostico publicado: {len(res.mensual)} meses; "
          f"MAPE {res.metricas['mape'].round(4).tolist()}")


if __name__ == "__main__":
    main()
