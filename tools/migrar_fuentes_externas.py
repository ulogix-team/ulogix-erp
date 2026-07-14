"""Migra maestros/datasets locales a Sheets y configura Odoo una sola vez.

Idempotente: las hojas maestras se reemplazan con el seed actual y en Odoo
se buscan campos, clientes y productos antes de crear/actualizar. Después de
esta migración, el ERP con EXTERNAL_ONLY=true solo lee Sheets/Odoo.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import settings  # noqa: E402
from integrations.odoo_client import OdooClient  # noqa: E402
from integrations.sheets_client import Contabilidad  # noqa: E402


CAMPOS = {
    "mrp.production": [
        ("x_ulogix_linea", "Línea ULOGIX", "char"),
        ("x_ulogix_mes", "Mes plan ULOGIX", "char"),
        ("x_ulogix_root_origin", "Origen raíz ULOGIX", "char"),
        ("x_ulogix_target_qty", "Objetivo lógico ULOGIX", "float"),
        ("x_ulogix_available_qty", "Cantidad MES disponible ULOGIX", "float"),
        ("x_ulogix_synced_qty", "Cantidad sincronizada ULOGIX", "float"),
        ("x_ulogix_sequence", "Secuencia ULOGIX", "integer"),
    ],
    "product.template": [
        ("x_ulogix_linea", "Línea ULOGIX", "char"),
        ("x_ulogix_litros_unidad", "Litros por unidad ULOGIX", "float"),
        ("x_ulogix_unidades_caja", "Unidades por caja ULOGIX", "integer"),
        ("x_ulogix_cajas_pallet", "Cajas por pallet ULOGIX", "integer"),
    ],
    "res.partner": [
        ("x_ulogix_canal", "Canal ULOGIX", "char"),
        ("x_ulogix_participacion", "Participación ULOGIX", "float"),
    ],
    "hr.employee": [
        ("x_ulogix_managed", "Gestionado por ULOGIX", "boolean"),
        ("x_ulogix_rol", "Rol personal ULOGIX", "char"),
        ("x_ulogix_linea", "Línea ULOGIX", "char"),
        ("x_ulogix_turno", "Turno ULOGIX", "char"),
        ("x_ulogix_fase", "Fase ULOGIX", "char"),
        ("x_ulogix_estado", "Estado roster ULOGIX", "char"),
        ("x_ulogix_costo_empleador", "Costo total empleador ULOGIX", "float"),
        ("x_ulogix_factor_prestacional", "Factor prestacional ULOGIX (%)", "float"),
        ("x_ulogix_arl_clase", "Clase ARL ULOGIX", "char"),
    ],
}


def _publicar_sheets() -> tuple[pd.DataFrame, pd.DataFrame]:
    cli = Contabilidad()
    maestro = pd.read_csv(settings.DATA_DIR / "maestro_productos.csv",
                          dtype={"ean13": str})
    clientes = pd.read_csv(settings.DATA_DIR / "clientes.csv")
    tablas = {
        "Maestro_Productos": maestro,
        "Clientes": clientes,
        "Forecast_Historico_Mensual": pd.read_csv(settings.DATA_DIR / "historico_planta.csv"),
        "Forecast_Historico_Trimestral": pd.read_csv(
            settings.DATA_DIR / "historico_trimestral_planta.csv"),
        "Forecast_Perfil_Formato": pd.read_csv(settings.DATA_DIR / "perfil_formato.csv"),
        "Forecast_Pronostico_Mensual": pd.read_csv(
            settings.DATA_DIR / "pronostico_base_mensual.csv"),
        "Forecast_Pronostico_Trimestral": pd.read_csv(
            settings.DATA_DIR / "pronostico_trimestral.csv"),
        "Forecast_Metricas": pd.read_csv(settings.DATA_DIR / "metricas_backtest.csv"),
    }
    kof = json.loads((settings.DATA_DIR / "kof_trimestral_colombia.json").read_text(
        encoding="utf-8"))
    tablas["Forecast_KOF_Trimestral"] = pd.DataFrame(
        [{"k": k, **v} for k, v in sorted(kof.items())])
    configs = []
    for clave, archivo in [("parametros_repo", "parametros.json"),
                           ("parametros_planta", "parametros_planta.json"),
                           ("distribuciones", "distribuciones.json")]:
        contenido = json.loads((settings.DATA_DIR / archivo).read_text(encoding="utf-8"))
        configs.append({"clave": clave,
                        "json": json.dumps(contenido, ensure_ascii=False, separators=(",", ":"))})
    mensual = tablas["Forecast_Pronostico_Mensual"]
    configs.extend([
        {"clave": "pipeline_origen", "json": json.dumps({
            "origen": "Repo/paquete scripts 00-14 (pipeline reproducible KOF)",
            "version_base": "v2/v3",
            "version_operativa": "v4",
            "cambios_preservados": [
                "Bates-Granger optimo P3 (no promedio 50/50)",
                "deriva de mezcla retornable P1/P2",
                "perfil mensual diferenciado por formato",
                "inputs y resultados materializados en Sheets",
            ],
        }, ensure_ascii=False, separators=(",", ":"))},
        {"clave": "resultado_supuestos", "json": json.dumps({
            "fuente_datos": "Google Sheets (datasets Forecast_*)",
            "mezcla_retornable": {"deriva_anual_pp": 0.5},
            "comparacion_modelos_P3_MAPE_pct": {
                "Bates-Granger optimo": 2.1118},
            "correlacion_mensual_P1P2": {
                "historico (mezcla fija)": 1.0,
                "pronostico v4": round(float(mensual[
                    ["P1-CC350-RGB_unidades", "P2-QT1500-PET_unidades"]
                ].corr().iloc[0, 1]), 4)},
            "perfil_formato": "Forecast_Perfil_Formato (Sheets)",
            "mc_n": 10000,
        }, ensure_ascii=False, separators=(",", ":"))},
        {"clave": "resultado_validacion", "json": json.dumps({
            "P1": {"error_pct": 0.07}, "P2": {"error_pct": 0.07},
            "P3": {"error_pct": -0.34},
        }, ensure_ascii=False, separators=(",", ":"))},
    ])
    tablas["Forecast_Configuracion"] = pd.DataFrame(configs)
    for hoja, df in tablas.items():
        cli.publicar_tabla_externa(hoja, df)
        print(f"Sheets {hoja}: {len(df)} filas")
    return maestro, clientes


def _asegurar_campo(o: OdooClient, modelo: str, nombre: str,
                    etiqueta: str, tipo: str) -> int:
    ids = o._kw("ir.model.fields", "search",
                [[['model', '=', modelo], ['name', '=', nombre]]], {"limit": 1})
    if ids:
        return ids[0]
    model_ids = o._kw("ir.model", "search", [[['model', '=', modelo]]], {"limit": 1})
    if not model_ids:
        raise RuntimeError(f"Modelo Odoo ausente: {modelo}")
    return o._kw("ir.model.fields", "create", [{
        "model_id": model_ids[0], "name": nombre,
        "field_description": etiqueta, "ttype": tipo, "state": "manual",
    }])


def _configurar_odoo(maestro: pd.DataFrame, clientes: pd.DataFrame) -> None:
    o = OdooClient()
    for modelo, campos in CAMPOS.items():
        for nombre, etiqueta, tipo in campos:
            fid = _asegurar_campo(o, modelo, nombre, etiqueta, tipo)
            print(f"Odoo campo {modelo}.{nombre}: {fid}")

    for _, r in clientes.iterrows():
        ids = o._kw("res.partner", "search", [[['name', '=', r['nombre']]]], {"limit": 1})
        vals = {"name": r["nombre"], "city": r["ciudad"], "is_company": True,
                "customer_rank": 1, "ref": f"ULOGIX-CLIENTE-{r['nombre'][:20]}",
                "x_ulogix_canal": r["canal"],
                "x_ulogix_participacion": float(r["participacion"])}
        if ids:
            o._kw("res.partner", "write", [[ids[0]], vals])
            pid = ids[0]
        else:
            pid = o._kw("res.partner", "create", [vals])
        print(f"Odoo cliente {r['nombre']}: {pid}")

    for _, r in maestro.iterrows():
        ids = o._kw("product.product", "search",
                    [[['default_code', '=', r['sku']]]], {"limit": 1})
        if not ids:
            raise RuntimeError(f"Producto {r['sku']} no existe en Odoo; ejecuta bootstrap")
        p = o._kw("product.product", "read", [ids, ["product_tmpl_id"]])[0]
        o._kw("product.product", "write", [[ids[0]], {
            "barcode": str(r["ean13"]), "list_price": float(r["precio_venta_cop"]),
            "standard_price": float(r["costo_material_cop"]),
        }])
        o._kw("product.template", "write", [[p["product_tmpl_id"][0]], {
            "name": r["nombre"], "x_ulogix_linea": r["linea"],
            "x_ulogix_litros_unidad": float(r["litros_por_unidad"]),
            "x_ulogix_unidades_caja": int(r["unidades_por_caja"]),
            "x_ulogix_cajas_pallet": int(r["cajas_por_pallet"]),
        }])
        print(f"Odoo producto {r['sku']}: {ids[0]}")


if __name__ == "__main__":
    m, c = _publicar_sheets()
    _configurar_odoo(m, c)
    print("Migración externa completa")
