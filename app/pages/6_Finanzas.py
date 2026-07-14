import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.ui import theme
from app.ui.theme import COL, COLOR_SKU, NOMBRE_CORTO
from config import settings
from core.inventario import plan_compras
from integrations.sheets_client import Contabilidad

theme.preparar_pagina("Finanzas", "💰")
theme.encabezado("FASE FINANCIERA · SHEETS / EXCEL",
                 "Finanzas de produccion",
                 "Margen plan (escenario activo) vs. real (produccion MQTT) "
                 "y sincronizacion contable.")
theme.banner_escenario()
nombre_esc, dem = theme.demanda_activa()
from core.finanzas_negocio import _maestro as _maestro_financiero  # noqa: E402
maestro = _maestro_financiero().reset_index()

cont = Contabilidad()
destino = ("Google Sheets · " + settings.SHEETS_SPREADSHEET_ID[:18] + "…"
           if cont.modo == "sheets" else "fuente externa no disponible")
st.caption(f"Backend contable: **{destino}** (configura `SHEETS_SPREADSHEET_ID` y la "
           "cuenta de servicio para pasar a Google Sheets; el codigo no cambia).")

# ------------------------------------------------------------------ unit economics
st.subheader("Unit economics (maestro de productos — datos fisicos y precio base)")
st.caption("Precios y costos unitarios gobernados por la hoja `Parametros` de "
           "Sheets (`precio_venta_cop_<SKU>` / `costo_material_cop_<SKU>`). "
           "Con `EXTERNAL_ONLY=true` no se usa el CSV local como fallback.")
ue = maestro[["sku", "nombre", "precio_venta_cop", "costo_material_cop"]].copy()
ue["margen_unit_cop"] = ue["precio_venta_cop"] - ue["costo_material_cop"]
ue["margen_pct"] = (100 * ue["margen_unit_cop"] / ue["precio_venta_cop"]).round(1)
st.dataframe(ue, width="stretch", hide_index=True,
             column_config={c: st.column_config.NumberColumn(format="$%,.0f")
                            for c in ["precio_venta_cop", "costo_material_cop",
                                      "margen_unit_cop"]})

# ------------------------------------------------------------------ plan mensual
st.subheader(f"Plan financiero mensual · escenario {nombre_esc}")
filas = []
for _, m in dem.iterrows():
    fila = {"etiqueta": m["etiqueta"]}
    ing = cos = 0.0
    for _, p in maestro.iterrows():
        u = m[f"{p['sku']}_unidades"]
        fila[f"margen_{p['sku']}"] = u * (p["precio_venta_cop"] - p["costo_material_cop"])
        ing += u * p["precio_venta_cop"]; cos += u * p["costo_material_cop"]
    fila.update(ingreso_cop=round(ing), costo_cop=round(cos), margen_cop=round(ing - cos))
    filas.append(fila)
plan_fin = pd.DataFrame(filas)

fig = go.Figure()
for sku in COLOR_SKU:
    fig.add_trace(go.Bar(x=plan_fin["etiqueta"], y=plan_fin[f"margen_{sku}"],
                         name=NOMBRE_CORTO[sku], marker_color=COLOR_SKU[sku]))
fig.update_layout(barmode="stack", yaxis_title="margen bruto (COP)")
st.plotly_chart(theme.plotly_layout(fig), width="stretch")

c1, c2, c3 = st.columns(3)
c1.metric("Ingreso anual plan", f"${plan_fin['ingreso_cop'].sum():,.0f}")
c2.metric("Costo materiales plan", f"${plan_fin['costo_cop'].sum():,.0f}")
c3.metric("Margen bruto plan", f"${plan_fin['margen_cop'].sum():,.0f}")

# ------------------------------------------------------------------ real desde MQTT
st.divider()
st.subheader("Real acumulado (produccion reportada por MQTT)")
ev_df = cont.leer_libro_produccion()
if "unidades" in ev_df.columns and "qty" not in ev_df.columns:
    ev_df = ev_df.rename(columns={"unidades": "qty"})
eventos = ev_df.to_dict("records") if not ev_df.empty else []
if eventos:
    for col in ["qty", "precio_unit_cop", "costo_unit_cop", "ingreso_cop",
                "costo_cop", "margen_cop"]:
        if col in ev_df:
            ev_df[col] = pd.to_numeric(ev_df[col], errors="coerce").fillna(0)
    m = maestro.set_index("sku")
    if "ingreso_cop" not in ev_df:
        ev_df["ingreso_cop"] = ev_df.apply(lambda r: r["qty"] * m.loc[r["sku"], "precio_venta_cop"]
                                           if r["sku"] in m.index else 0, axis=1)
    if "costo_cop" not in ev_df:
        ev_df["costo_cop"] = ev_df.apply(lambda r: r["qty"] * m.loc[r["sku"], "costo_material_cop"]
                                         if r["sku"] in m.index else 0, axis=1)
    if "margen_cop" not in ev_df:
        ev_df["margen_cop"] = ev_df["ingreso_cop"] - ev_df["costo_cop"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Unidades reportadas", f"{ev_df['qty'].sum():,.0f}")
    c2.metric("Ingreso real", f"${ev_df['ingreso_cop'].sum():,.0f}")
    c3.metric("Margen real", f"${ev_df['margen_cop'].sum():,.0f}")
    with st.expander("Detalle por evento"):
        st.dataframe(ev_df[["ts", "linea", "sku", "qty", "ingreso_cop",
                            "costo_cop", "margen_cop"]],
                     width="stretch", hide_index=True)
else:
    st.info("Aun no hay produccion reportada. Publica en MQTT (pagina *Produccion "
            "MQTT*) o corre `python tools/simulador_produccion.py`.")

# ------------------------------------------------------------------ sincronizacion
st.divider()
st.subheader("Sincronizacion contable")
c1, c2, c3 = st.columns(3)
with c1:
    if st.button("📒 Sincronizar LibroProduccion", type="primary",
                 disabled=not eventos, width="stretch"):
        st.info("LibroProduccion ya es la fuente externa activa; no requiere "
                "reconstruccion desde SQLite.")
with c2:
    if st.button("📅 Publicar ResumenMensual (plan)", width="stretch"):
        destino = cont.publicar_resumen_mensual(
            plan_fin[["etiqueta", "ingreso_cop", "costo_cop", "margen_cop"]])
        st.success(f"Resumen mensual publicado en {destino}.")
with c3:
    if st.button("🧾 Publicar PlanCompras (MRP)", width="stretch"):
        destino = cont.publicar_plan_compras(plan_compras(dem, cobertura_meses=3))
        st.success(f"Plan de compras publicado en {destino}.")

# ================================================================ caso de negocio
st.divider()
st.subheader("Caso de negocio del retrofit — conectado a la demanda")
from core.finanzas_negocio import estado_fuente_financiera, indicadores  # noqa: E402

if st.session_state.pop("_forzar_refresco_fin", False):
    fuente = estado_fuente_financiera(forzar=True)
    st.toast("Parametros y CAPEX releidos desde Sheets/Excel.")
else:
    fuente = estado_fuente_financiera()

nombre_activo, dem_activa = theme.demanda_activa()
ind_base = indicadores(theme.datos_pronostico()["mensual"], "Base")
ind = (indicadores(dem_activa, nombre_activo)
       if nombre_activo != "Base" else ind_base)

st.caption(f"El FCF de 60 meses se construye **desde el pronostico de demanda por "
           f"SKU** (escenario activo: **{nombre_activo}**), con margenes del "
           "maestro de productos, uplift +11% x monetizacion 31%, ahorro de "
           "scrap, mantenimiento evitado, ahorro laboral monetizable, "
           "depreciacion/impuestos y capital de "
           "trabajo. El mismo motor vive como formulas en las hojas "
           "**Financiero** (base) y **FinancieroEscenario** (demanda elegida "
           "en el ERP) del libro conectado.")

cfa, cfb = st.columns([4, 1])
with cfa:
    if fuente["modo_contabilidad"] == "sheets":
        vivos = fuente["parametros_desde_sheets"]
        txt_capex = (f"CAPEX: **{fuente['n_filas_capex_sheets']} filas desde la hoja "
                     "'CAPEX'**" if fuente["capex_desde_sheets"]
                     else "CAPEX: hoja 'CAPEX' vacia/ausente -> usando default local")
        txt_params = (f"{len(vivos)} parametro(s) sobreescritos desde 'Parametros': "
                      f"{', '.join(vivos)}" if vivos
                      else "hoja 'Parametros' sin overrides activos -> defaults locales")
        st.success(f"📗 Gobernado por Google Sheets (TTL {fuente['ttl_seg']:.0f}s). "
                   f"{txt_capex}. {txt_params}.", icon="📗")
    else:
        st.info("📄 Google Sheets no esta configurado o cayo a fallback: el caso de "
                "negocio usa los defaults locales de `core/finanzas_negocio.py` "
                "(CAPEX_FILAS, TRM, TMAR, nomina, otros fijos...). Configura "
                "`SHEETS_SPREADSHEET_ID` y las hojas `Parametros`/`CAPEX` para que "
                "el usuario pueda ajustar CAPEX/turnos/precios sin tocar codigo.",
                icon="📄")
with cfb:
    if st.button("🔄 Refrescar desde Sheets", width="stretch"):
        st.session_state["_forzar_refresco_fin"] = True
        st.rerun()

with st.container(border=True):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("CAPEX total", f"$ {ind['capex_total_cop']/1e9:,.2f} MM COP",
              f"celdas roboticas: $ {ind['capex_celdas_cop']/1e6:,.0f} M (BOM real)",
              delta_color="off")
    c2.metric("VPN @ TMAR 18% E.A.", f"$ {ind['vpn_cop']/1e6:,.0f} M COP",
              None if nombre_activo == "Base" else
              f"{(ind['vpn_cop'] - ind_base['vpn_cop'])/1e6:+,.0f} M vs Base")
    c3.metric("TIR / ROI 60m", f"{ind['tir_anual']*100:.1f}% E.A.",
              f"ROI {ind['roi_horizonte_60m']*100:.1f}% "
              f"({ind['roi_anualizado']*100:.2f}% anual)", delta_color="off")
    c4.metric("Payback", f"{ind['payback_simple_meses']} meses",
              f"descontado: {ind['payback_descontado_meses']} m", delta_color="off")

if nombre_activo != "Base":
    comp = pd.DataFrame([
        {"indicador": "VPN (M COP)", "Base": round(ind_base["vpn_cop"]/1e6),
         nombre_activo: round(ind["vpn_cop"]/1e6)},
        {"indicador": "TIR anual", "Base": f"{ind_base['tir_anual']*100:.2f}%",
         nombre_activo: f"{ind['tir_anual']*100:.2f}%"},
        {"indicador": "ROI 60m", "Base": f"{ind_base['roi_horizonte_60m']*100:.1f}%",
         nombre_activo: f"{ind['roi_horizonte_60m']*100:.1f}%"},
        {"indicador": "Payback simple (m)", "Base": ind_base["payback_simple_meses"],
         nombre_activo: ind["payback_simple_meses"]},
        {"indicador": "EBITDA 12m operativos (M COP)",
         "Base": round(ind_base["ebitda_incremental_y1_cop"]/1e6),
         nombre_activo: round(ind["ebitda_incremental_y1_cop"]/1e6)},
    ])
    st.dataframe(comp, width="stretch", hide_index=True)

st.caption(f"EBITDA incremental (12 meses operativos): "
           f"$ {ind['ebitda_incremental_y1_cop']/1e6:,.0f} M COP · capital de "
           f"trabajo $ {ind['capital_trabajo_cop']/1e6:,.0f} M (m5 -> m60) · "
           f"Δ VPN vs modelo original (xlsm, flujo agregado): "
           f"{ind['delta_vs_modelo_original']['vpn_pct']:+.1f}% — la diferencia "
           "es esperada: este motor deriva el flujo de la demanda real por SKU "
           "con depreciacion e impuestos explicitos.")

viab = cont.leer_viabilidad_automatizacion()
if not viab.empty:
    with st.expander("Antes vs. automatización ULogix vs. alternativa comercial"):
        st.caption("El ahorro laboral es FTE equivalente y monetiza inicialmente 70%; "
                   "el porcentaje es editable en `Parametros` para representar "
                   "reasignación, rotación natural o ahorro efectivo.")
        st.dataframe(viab, width="stretch", hide_index=True)

proveedores = cont.leer_proveedores_capex()
if not proveedores.empty:
    with st.expander("Proveedores, cotizaciones y maquinaria usada evaluada"):
        st.dataframe(proveedores, width="stretch", hide_index=True)

if st.button("📗 Sincronizar demanda al libro (Base -> Demanda · activo -> DemandaEscenario)"):
    from integrations.sheets_client import Contabilidad
    cli = Contabilidad()
    d1 = cli.publicar_demanda(theme.datos_pronostico()["mensual"], "Base")
    d2 = cli.publicar_demanda_escenario(dem_activa, nombre_activo)
    pol = cli.leer_inventarios()
    d3 = "Inventarios ya gobernado por Sheets" if not pol.empty else "sin politicas aun"
    st.success(f"Demanda Base -> {d1} · escenario «{nombre_activo}» -> {d2} · "
               f"inventarios -> {d3}. Las hojas ER/Flujo_Caja/FinancieroEscenario/"
               "Reportes del libro recalculan solas.")

fig_bc = go.Figure()
fig_bc.add_trace(go.Bar(x=list(range(1, 61)), y=ind["flujos"] / 1e6,
                        name=f"FCF mensual ({nombre_activo})",
                        marker_color=COL["acento"]))
fig_bc.add_trace(go.Scatter(x=list(range(1, 61)),
                            y=ind["acumulado_descontado"] / 1e6,
                            name="Acumulado descontado", mode="lines",
                            line=dict(color="#FFB454", width=2.4)))
if nombre_activo != "Base":
    fig_bc.add_trace(go.Scatter(x=list(range(1, 61)),
                                y=ind_base["acumulado_descontado"] / 1e6,
                                name="Acumulado descontado (Base)", mode="lines",
                                line=dict(color="#888", width=1.6, dash="dot")))
fig_bc.add_hline(y=0, line_color="#666", line_width=1)
theme.plotly_layout(fig_bc, "Flujo de caja del proyecto (M COP) · 60 meses")
st.plotly_chart(fig_bc, width="stretch")

# ================================================================ costos de ingenieria (APU)
st.divider()
st.subheader("Costos de ingeniería ULogix — Análisis de Precios Unitarios (APU)")
st.caption("Justificación, componente por componente, de lo que ULogix cobra por "
           "ingeniería de detalle/FAT/SAT/PMO, instalación/puesta en marcha (EPC) y "
           "capacitación/gestión del cambio — las tres filas de **Servicios** de la "
           "hoja **CAPEX**. Metodología estándar de costeo en construcción/EPC: "
           "**costo directo × (1 + AIU)**, donde AIU = Administración + Imprevistos + "
           "Utilidad (banda de mercado 25–30% — no es una tarifa fijada por ley: desde "
           "la desregulación de honorarios profesionales, COPNIA no fija tarifas "
           "mínimas, es de negociación contractual). La mano de obra propia usa el "
           "costo real de nómina de la hoja `RRHH`; los rubros de "
           "terceros/OEM son supuestos de mercado documentados, a validar con "
           "cotización real antes de contratar. Ver `tools/publicar_apu_ingenieria.py`.")

from integrations.sheets_client import Contabilidad as _Cont  # noqa: E402
apu = _Cont().leer_apu_ingenieria()

if not apu["resumen"]:
    st.info("Aún no se ha publicado la hoja `APU_Ingenieria` — corre "
            "`python tools/publicar_apu_ingenieria.py` (requiere Sheets configurado; "
            "esta hoja es de solo exhibición, sin fallback local).")
else:
    df_resumen = pd.DataFrame(apu["resumen"])
    total_directo = df_resumen["costo_directo_cop"].sum()
    total_precio = df_resumen["precio_total_cop"].sum()
    aiu_global = total_precio / total_directo - 1

    c1, c2, c3 = st.columns(3)
    c1.metric("Costo directo total", f"$ {total_directo/1e6:,.0f} M COP", delta_color="off")
    c2.metric("AIU implícito", f"{aiu_global*100:.1f}%",
              "banda de mercado 25–30%", delta_color="off")
    c3.metric("Precio total (= CAPEX Servicios)", f"$ {total_precio/1e6:,.0f} M COP",
              delta_color="off")

    fig_apu = go.Figure()
    fig_apu.add_trace(go.Bar(y=df_resumen["item"], x=df_resumen["costo_directo_cop"] / 1e6,
                             name="Costo directo", orientation="h",
                             marker_color=COL["acento"]))
    fig_apu.add_trace(go.Bar(y=df_resumen["item"], x=df_resumen["aiu_cop"] / 1e6,
                             name="AIU (Admin+Imprev+Util)", orientation="h",
                             marker_color=COL.get("acento2", "#5AC8FA")))
    fig_apu.update_layout(barmode="stack", xaxis_title="M COP")
    st.plotly_chart(theme.plotly_layout(fig_apu, "Costo directo vs. AIU por ítem"),
                    width="stretch")

    st.dataframe(
        df_resumen[["item", "costo_directo_cop", "pct_aiu_total", "aiu_cop",
                   "precio_total_cop"]],
        width="stretch", hide_index=True,
        column_config={
            "costo_directo_cop": st.column_config.NumberColumn("Costo directo", format="$%,.0f"),
            "pct_aiu_total": st.column_config.NumberColumn("AIU %", format="%.1f%%"),
            "aiu_cop": st.column_config.NumberColumn("AIU COP", format="$%,.0f"),
            "precio_total_cop": st.column_config.NumberColumn("Precio total", format="$%,.0f"),
        })

    with st.expander("Detalle por componente (mano de obra, terceros/OEM, materiales, logística)"):
        df_detalle = pd.DataFrame(apu["detalle"])
        for columna in ("cantidad", "valor_unitario_cop", "subtotal_cop"):
            if columna in df_detalle:
                df_detalle[columna] = pd.to_numeric(df_detalle[columna], errors="coerce")
        st.dataframe(df_detalle, width="stretch", hide_index=True,
                    column_config={
                        "valor_unitario_cop": st.column_config.NumberColumn(format="$%,.0f"),
                        "subtotal_cop": st.column_config.NumberColumn(format="$%,.0f"),
                    })
