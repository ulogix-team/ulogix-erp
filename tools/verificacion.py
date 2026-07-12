"""
Verificacion end-to-end de la suite (equivalente en espiritu al script 12 de QA
del repositorio original). Corre sin servicios externos: usa una base SQLite
temporal y el respaldo Excel de contabilidad.

Uso:  python tools/verificacion.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# aislar el estado: DB temporal para no tocar middleware/state.db
os.environ["STATE_DB"] = str(Path(tempfile.mkdtemp()) / "state_qa.db")

RESULTADOS: list[tuple[str, bool, str]] = []


def paso(nombre):
    def deco(fn):
        def run():
            try:
                detalle = fn() or ""
                RESULTADOS.append((nombre, True, str(detalle)))
            except Exception as e:  # noqa: BLE001
                RESULTADOS.append((nombre, False, f"{type(e).__name__}: {e}"))
        return run
    return deco


@paso("1. Datos base presentes")
def _datos():
    from config import settings
    req = ["kof_volumenes_trimestrales.csv", "maestro_productos.csv", "bom.csv",
           "estacionalidad_mensual.csv", "parametros_planta.json", "clientes.csv"]
    faltan = [f for f in req if not (settings.DATA_DIR / f).exists()]
    assert not faltan, f"faltan: {faltan}"
    return f"{len(req)} archivos"


@paso("2. Pronostico (HW + Bates-Granger + MC)")
def _forecast():
    from core.forecast import pronostico_base
    r = pronostico_base(mc_n=500)
    assert len(r.mensual) == 12 and (r.metricas["mape"] < 0.25).all()
    globals()["_res"] = r
    return "12 meses · MAPE " + ", ".join(f"{m*100:.1f}%" for m in r.metricas["mape"])


@paso("3. Escenarios (6 presets + comparativo)")
def _esc():
    from core.escenarios import ESCENARIOS, resumen_comparativo
    df = resumen_comparativo(globals()["_res"])
    assert len(df) == len(ESCENARIOS) == 6
    return f"{len(df)} escenarios"


@paso("4. Inventario (s,Q) Monte Carlo")
def _inv():
    from core.inventario import ParametrosInventario, simular_inventario
    r = simular_inventario(globals()["_res"].mensual,
                           ParametrosInventario("P1-CC350-RGB"), 0.023, n_rep=30)
    assert r["fill_rate_prom"] > 0.90
    return f"fill rate {r['fill_rate_prom']*100:.1f}%"


@paso("5. MRP -> plan de compras")
def _mrp():
    from core.inventario import plan_compras
    p = plan_compras(globals()["_res"].mensual, cobertura_meses=2)
    assert {"producto", "componente", "proveedor", "fecha_pedido"} <= set(p.columns)
    globals()["_plan"] = p
    return f"{len(p)} lineas · ${p['subtotal_cop'].sum():,.0f} COP"


@paso("6. Sensibilidad (tornado)")
def _sens():
    from core.sensibilidad import tornado
    t = tornado(globals()["_res"].mensual)
    assert len(t) == 6 and t.attrs["margen_base_cop"] > 0
    return f"margen base ${t.attrs['margen_base_cop']:,.0f}"


@paso("7. Odoo dry-run (PO de insumos + factura proveedor + MO desde el plan)")
def _odoo():
    # QA de LOGICA, no de conectividad (eso vive en la pagina Pruebas):
    # se fuerza dry-run aunque haya credenciales reales en .env.
    from config import settings
    from integrations.odoo_client import LineaPedido, OdooClient
    from integrations import state_store
    previo, settings.DRY_RUN_FORZADO = settings.DRY_RUN_FORZADO, True
    g = globals()["_plan"].iloc[0]
    cli = OdooClient()
    res = cli.crear_orden_compra(
        g["proveedor"], [LineaPedido(g["descripcion"], g["componente"],
                                     g["cantidad"], g["precio_unitario_cop"])],
        "QA/VERIFICACION", confirmar=True, recibir=True, facturar=True)
    assert res.get("facturada")
    mo = cli.crear_orden_fabricacion(g["producto"], 100, "QA/VERIFICACION-MO")
    state_store.registrar_po(res["name"], g["producto"], qty_objetivo=100,
                             proveedor=g["proveedor"], mo_id=mo.get("id"),
                             mo_name=mo.get("name"), insumos_recibidos=True)
    globals()["_ultima_po"] = res
    settings.DRY_RUN_FORZADO = previo
    return f"{res['name']} (facturada) -> {mo['name']}"


@paso("8. Ventas dry-run (SO al cliente + entrega + factura de cliente)")
def _ventas():
    from config import settings
    from integrations.odoo_client import LineaPedido, OdooClient
    from integrations import state_store
    previo, settings.DRY_RUN_FORZADO = settings.DRY_RUN_FORZADO, True
    g = globals()["_plan"].iloc[0]
    cli = OdooClient()
    res = cli.crear_orden_venta(
        "QA Distribuidor de prueba",
        [LineaPedido(g["descripcion"], g["producto"], 50, 2200.0)],
        "QA/VERIFICACION-VENTA", confirmar=True, entregar=True, facturar=True)
    assert res.get("entregada") and res.get("facturada")
    state_store.registrar_venta(res["name"], g["producto"], "QA Distribuidor de prueba",
                                50, 2200.0, mo_name="QA/VERIFICACION-MO",
                                estado="facturada")
    settings.DRY_RUN_FORZADO = previo
    return f"{res['name']} -> entregada y facturada"


@paso("9. Middleware MQTT (payload normal + estilo MES)")
def _mw():
    import json
    from integrations.mqtt_middleware import Middleware
    from integrations import state_store
    from config import settings
    previo, settings.DRY_RUN_FORZADO = settings.DRY_RUN_FORZADO, True
    mw = Middleware()
    sku = globals()["_plan"].iloc[0]["producto"]
    linea = {"P1-CC350-RGB": "L1", "P2-QT1500-PET": "L2", "P3-GARR25L": "L3"}[sku]
    mw.manejar_mensaje(f"plant/{linea}/production", json.dumps({"sku": sku, "qty": 60}))
    done = mw.manejar_mensaje(f"plant/{linea}/production", json.dumps({"value": 40}))
    pos = state_store.listar_pos()
    assert done and pos[0]["estado"] == "recibida_odoo" and pos[0]["mo_name"], pos
    settings.DRY_RUN_FORZADO = previo
    return f"{pos[0]['po_name']} -> recibida_odoo (MO {pos[0]['mo_name']})"


@paso("10. Contabilidad (Sheets con fallback Excel)")
def _cont():
    from integrations.sheets_client import Contabilidad
    from integrations import state_store
    from core.forecast import cargar_maestro
    destino, n = Contabilidad().sincronizar_libro_completo(
        state_store.ultimos_eventos(10), cargar_maestro())
    assert n >= 2
    return f"{n} asientos -> {destino}"


@paso("11. UNS FEMSA (YAML -> 63 topicos + interprete)")
def _uns():
    from integrations import uns
    hs = uns.hojas()
    assert len(hs) == 63 and "FEMSA/Linea1/MES/KPI/OEE" in hs
    info = uns.interpretar_topico("FEMSA/Linea2/ERP/OrderStatus")
    assert info["linea"] == "L2" and info["hoja"] == "OrderStatus"
    return f"{len(hs)} topicos-hoja; suscripciones: {uns.suscripciones()}"


@paso("12. Base de datos ERP (tablas + persistencia)")
def _erp():
    from integrations import state_store as ss
    res = ss.resumen_tablas()
    assert set(ss.TABLAS_ERP) <= set(res)
    ss.registrar_kpi("L1", "MES/KPI", "OEE", 0.7712, "FEMSA/Linea1/MES/KPI/OEE")
    assert ss.kpis_actuales()
    return f"tablas: {res}"


@paso("13. Tiempos y OEE (+5% justificado)")
def _toee():
    from core.tiempos_oee import tabla_oee, tabla_tiempos
    t, o = tabla_tiempos(), tabla_oee()
    assert len(t) == 3 and t["pallets_por_lote"].tolist() == [162, 87, 96]
    assert int(t.loc[t.linea == "L1", "q_lote_turno_und"].iloc[0]) == 262440
    assert abs(o.loc[o.linea == "L1", "oee_base"].iloc[0] - 0.7712) < 1e-3
    assert abs(o.loc[o.linea == "L1", "oee_a_implementar"].iloc[0] - 0.7712 * 1.05) < 1e-3
    return (f"lotes {t['pallets_por_lote'].tolist()} pallets · OEE base "
            f"{o['oee_base'].tolist()} · TEEP {o['teep'].tolist()}")


@paso("14. Caso de negocio (ROI/VPN/TIR)")
def _fin():
    from core.finanzas_negocio import indicadores
    ind = indicadores()
    assert ind["vpn_cop"] > 0 and 0.20 < ind["tir_anual"] < 0.50
    assert ind["payback_simple_meses"] == 33
    return (f"VPN ${ind['vpn_cop']/1e6:,.0f}M · TIR {ind['tir_anual']*100:.1f}% · "
            f"ROI {ind['roi_horizonte_60m']*100:.1f}% · payback {ind['payback_simple_meses']}m")


@paso("15. RRHH (roster de empleados + reconciliacion)")
def _rrhh():
    from core import rrhh
    from integrations import rrhh_client
    df, origen = rrhh_client.leer_empleados()
    problemas = rrhh.validar_roster(df)
    assert not problemas, problemas
    costo = rrhh.costo_mensual_por_fase(df)
    assert costo.get("Operacion", 0) > 0 and costo.get("Implementacion", 0) > 0
    return f"{len(df)} empleados ({origen}) · {len(rrhh.resumen_por_rol(df))} roles"


if __name__ == "__main__":
    for fn in [_datos, _forecast, _esc, _inv, _mrp, _sens, _odoo, _ventas, _mw,
               _cont, _uns, _erp, _toee, _fin, _rrhh]:
        fn()
    print("\n=== VERIFICACION ULOGIX ===")
    ok = True
    for nombre, exito, detalle in RESULTADOS:
        print(f"{'✅' if exito else '❌'} {nombre}  {detalle}")
        ok &= exito
    print("===", "TODO OK" if ok else "HAY FALLAS", "===")
    sys.exit(0 if ok else 1)
