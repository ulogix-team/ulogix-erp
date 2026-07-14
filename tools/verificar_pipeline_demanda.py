"""QA reproducible del pipeline de demanda integrado con Google Sheets.

Recoge las verificaciones esenciales de los scripts 00-14 del repositorio
base y las aplica a la evolucion v4 operativa. No lee Downloads ni CSV locales:
los insumos y el snapshot vigente salen de Forecast_* en Sheets. Recalcula el
modelo dentro de Docker y exige que conserve el estado publicado, admitiendo
solo diferencias minimas de redondeo/optimizacion numerica.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.forecast import pronostico_base  # noqa: E402
from integrations.sheets_client import Contabilidad  # noqa: E402


def _ean13_valido(valor: object) -> bool:
    codigo = str(valor).split(".")[0].zfill(13)
    if len(codigo) != 13 or not codigo.isdigit():
        return False
    d = [int(x) for x in codigo]
    return d[-1] == (10 - (sum(d[:12:2]) + 3 * sum(d[1:12:2])) % 10) % 10


def _registrar(filas: list[dict], prueba: str, pasa: bool, detalle: str) -> None:
    filas.append({"prueba": prueba, "estado": "OK" if pasa else "FALLA",
                  "detalle": detalle})
    print(f"[{'OK' if pasa else 'FALLA'}] {prueba}: {detalle}")


def ejecutar() -> pd.DataFrame:
    s = Contabilidad()
    filas: list[dict] = []

    kof = s.leer_dataset_pronostico("Forecast_KOF_Trimestral")
    categorias = ["refrescos", "agua", "garrafon", "otros"]
    for c in categorias + ["total"]:
        kof[c] = pd.to_numeric(kof[c], errors="raise")
    cierre = (kof[categorias].sum(axis=1) - kof["total"]).abs().max()
    _registrar(filas, "KOF 21 trimestres y categorias=total",
               len(kof) == 21 and cierre < 0.15,
               f"filas={len(kof)}, diferencia_max={cierre:.3f} MCU")
    kof["anio"] = kof["k"].astype(str).str[:4]
    anual = kof.groupby("anio")["total"].sum().to_dict()
    referencia = {"2022": 330.1, "2023": 347.6, "2024": 352.3, "2025": 349.4}
    dif_anual = max(abs(float(anual[a]) - v) for a, v in referencia.items())
    _registrar(filas, "Agregados anuales KOF",
               dif_anual <= 0.3, f"diferencia_max={dif_anual:.3f} MCU")

    params = s.leer_config_pronostico("parametros_repo")
    dif_pesos = max(abs(sum(map(float, w)) - 1) for w in params["W"].values())
    _registrar(filas, "Pesos intra-trimestre",
               dif_pesos < 1e-9, f"desviacion_max={dif_pesos:.3g}")

    hm = s.leer_dataset_pronostico("Forecast_Historico_Mensual")
    hq = s.leer_dataset_pronostico("Forecast_Historico_Trimestral")
    serial = pd.to_numeric(hm["fecha"], errors="coerce")
    hm["fecha"] = (pd.to_datetime(serial, unit="D", origin="1899-12-30")
                   if serial.notna().all() else pd.to_datetime(hm["fecha"]))
    hm["anio"] = hm["fecha"].dt.year
    hm["trim"] = hm["fecha"].dt.quarter
    normalizar_producto = {"P1-CC350-RGB": "P1", "P2-QT1500-PET": "P2",
                           "P3-GARR25L": "P3"}
    hm["producto"] = hm["producto"].replace(normalizar_producto)
    hq["producto"] = hq["producto"].replace(normalizar_producto)
    agg = hm.groupby(["anio", "trim", "producto"], as_index=False)["litros"].sum()
    hq["anio"] = pd.to_numeric(hq["anio"], errors="raise").astype(int)
    hq["trim"] = pd.to_numeric(hq["trim"], errors="raise").astype(int)
    unidos = agg.merge(hq[["anio", "trim", "producto", "litros"]],
                       on=["anio", "trim", "producto"], suffixes=("_m", "_q"))
    dif_hist = (pd.to_numeric(unidos["litros_m"])
                - pd.to_numeric(unidos["litros_q"])).abs().max()
    _registrar(filas, "Historico mensual re-agrega al trimestral",
               len(unidos) == 63 and dif_hist <= 1,
               f"filas={len(unidos)}, diferencia_max={dif_hist:.3f} L")

    maestro = s.leer_maestro_productos()
    esperados = {"P1-CC350-RGB": 1620, "P2-QT1500-PET": 840, "P3-GARR25L": 30}
    pallets = dict(zip(maestro["sku"],
                       maestro["unidades_por_caja"] * maestro["cajas_por_pallet"]))
    _registrar(filas, "Jerarquia de empaque",
               all(int(pallets.get(k, -1)) == v for k, v in esperados.items()),
               str({k: int(v) for k, v in pallets.items()}))
    ean_ok = maestro["ean13"].map(_ean13_valido).all()
    _registrar(filas, "EAN-13 de productos", bool(ean_ok), f"validos={int(ean_ok)}")

    vigente = s.leer_dataset_pronostico("Forecast_Pronostico_Mensual")
    fresco = pronostico_base()
    columnas = list(fresco.mensual.columns)
    esquema_ok = columnas == list(vigente.columns) and len(vigente) == 12
    _registrar(filas, "Contrato del pronostico mensual", esquema_ok,
               f"filas={len(vigente)}, columnas={len(vigente.columns)}")
    max_litros = max(
        float((pd.to_numeric(vigente[c]) - pd.to_numeric(fresco.mensual[c])).abs().max())
        for c in columnas if c.endswith("_litros"))
    max_unidades = max(
        float((pd.to_numeric(vigente[c]) - pd.to_numeric(fresco.mensual[c])).abs().max())
        for c in columnas if c.endswith(("_unidades", "_p05", "_p95")))
    _registrar(filas, "Demanda vigente == recalculo v4",
               max_litros <= 500 and max_unidades <= 20,
               f"max_litros={max_litros:.0f}, max_unidades={max_unidades:.0f}")

    metricas = s.leer_dataset_pronostico("Forecast_Metricas")
    m_pub = dict(zip(metricas["producto"], pd.to_numeric(metricas["mape"])))
    m_new = dict(zip(fresco.metricas["producto"], fresco.metricas["mape"]))
    dif_mape = max(abs(float(m_pub[k]) - float(m_new[k])) for k in m_new)
    _registrar(filas, "MAPE vigente == recalculo v4",
               dif_mape <= 0.001,
               f"diferencia_max={dif_mape:.8f} ({dif_mape*100:.3f} pp)")
    return pd.DataFrame(filas)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publicar-qa", action="store_true",
                        help="publica el resultado en la hoja Forecast_QA")
    args = parser.parse_args()
    resultado = ejecutar()
    if args.publicar_qa:
        Contabilidad().publicar_tabla_externa("Forecast_QA", resultado)
        print("Forecast_QA publicada en Sheets")
    if (resultado["estado"] != "OK").any():
        raise SystemExit(1)
    print(f"PIPELINE DEMANDA OK: {len(resultado)} verificaciones")


if __name__ == "__main__":
    main()
