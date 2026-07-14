"""
Identidad visual Ulogix para el dashboard.

Tokens derivados del logo (ulogix-dark.svg): fondo #070213 (violeta casi
negro) y blanco. La paleta extiende ese violeta hacia paneles y un acento
principal; cada linea de produccion conserva SU color en TODAS las paginas
(firma visual de la suite):

  base        #070213   fondo Ulogix
  panel       #110A2C   tarjetas / superficies
  panel-2     #1A1140   superficies elevadas
  texto       #F4F2FC   blanco Ulogix
  texto-2     #9C93C4   texto secundario
  acento      #8F7BFF   violeta Ulogix (acciones, foco)
  L1 / P1     #FF5A66   rojo (Coca-Cola 350 RGB)
  L2 / P2     #A8E05F   citrico (QuAtro 1.5 PET)
  L3 / P3     #5AC8FA   agua (Garrafon 25 L)
  alerta      #FFB454   ambar
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import warnings

import streamlit as st

warnings.filterwarnings('ignore')  # ConvergenceWarning de statsmodels es cosmetico  # noqa: E402

COL = {
    "base": "#070213", "panel": "#110A2C", "panel2": "#1A1140",
    "texto": "#F4F2FC", "texto2": "#9C93C4", "acento": "#8F7BFF",
    "alerta": "#FFB454", "ok": "#5ADFB0",
    # tokens de apoyo (bordes, superficies, estados) — no rompen los ya
    # usados por 6_Finanzas.py (base/panel/texto/texto2/acento)
    "borde": "#241A4E", "borde2": "#332766", "muted": "#6C6396",
    "critico": "#FF6B7A", "acento2": "#5AC8FA",
}
COLOR_SKU = {
    "P1-CC350-RGB": "#FF5A66",
    "P2-QT1500-PET": "#A8E05F",
    "P3-GARR25L": "#5AC8FA",
}
NOMBRE_CORTO = {
    "P1-CC350-RGB": "Coca-Cola 350 RGB (L1)",
    "P2-QT1500-PET": "QuAtro 1.5 PET (L2)",
    "P3-GARR25L": "Garrafon 25 L (L3)",
}
# orden fijo para series genericas (RRHH, comparativos) que no representan
# un SKU — nunca se ciclan, se asignan en este orden
COLORWAY = [COL["acento"], COL["acento2"], COL["alerta"],
           "#A8E05F", "#FF5A66", COL["ok"], "#E87BA4", "#EB6834"]

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {{ font-family: 'Sora', sans-serif; }}

/* ---------------------------------------------------------- fondo y lienzo */
.stApp {{
  background:
    radial-gradient(1200px 480px at 12% -8%, {COL['panel2']}55 0%, transparent 60%),
    {COL['base']};
}}
[data-testid="stAppViewContainer"] > .main {{ padding-top: 0.4rem; }}
.block-container {{ padding-top: 1.6rem; max-width: 1440px; }}

/* ---------------------------------------------------------------- tipografia */
h1 {{ color: {COL['texto']} !important; letter-spacing: -0.015em; font-weight: 700 !important; }}
h2 {{ color: {COL['texto']} !important; letter-spacing: -0.01em; font-weight: 700 !important; }}
h3 {{
  color: {COL['texto']} !important; letter-spacing: -0.005em; font-weight: 600 !important;
  border-left: 3px solid {COL['acento']}; padding-left: 0.6rem;
  margin-top: 1.6rem !important; margin-bottom: 0.9rem !important;
}}
p, li, span, label {{ color: {COL['texto']}; }}
[data-testid="stCaptionContainer"], .stCaption {{ color: {COL['muted']} !important; }}

/* ------------------------------------------------------------------- sidebar */
[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, {COL['panel']} 0%, {COL['base']} 130%);
  border-right: 1px solid {COL['borde']};
}}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {{ color: {COL['texto2']}; }}
[data-testid="stSidebarNav"] a {{
  border-radius: 8px; color: {COL['texto2']} !important; font-weight: 500;
  transition: background 0.15s ease, color 0.15s ease;
}}
[data-testid="stSidebarNav"] a:hover {{ background: {COL['panel2']}; color: {COL['texto']} !important; }}
[data-testid="stSidebarNav"] a[aria-current="page"] {{
  background: {COL['panel2']}; color: {COL['texto']} !important;
  border-left: 3px solid {COL['acento']};
}}
.ulogix-sidebar-foot {{
  font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem; letter-spacing: 0.08em;
  color: {COL['muted']}; padding: 0.6rem 0.2rem; border-top: 1px solid {COL['borde']};
  margin-top: 0.8rem;
}}

/* --------------------------------------------------------------- encabezado */
.ulogix-eyebrow {{
  font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem;
  letter-spacing: 0.22em; text-transform: uppercase; color: {COL['acento']};
  margin-bottom: 0.2rem; font-weight: 500;
}}
.ulogix-sub {{ color: {COL['texto2']}; margin-top: -0.5rem; font-size: 0.95rem; max-width: 74ch; }}
.ulogix-hr {{
  height: 3px; border: none; margin: 0.35rem 0 1.4rem 0; border-radius: 3px;
  background: linear-gradient(90deg, {COL['acento']} 0%, {COL['acento2']} 45%, transparent 100%);
}}

/* ----------------------------------------------------------------- metricas */
[data-testid="stMetric"] {{
  background: linear-gradient(160deg, {COL['panel']} 0%, {COL['panel2']}66 130%);
  border: 1px solid {COL['borde']}; border-radius: 12px;
  padding: 14px 16px 12px 16px; position: relative; overflow: hidden;
  transition: border-color 0.15s ease, transform 0.15s ease;
}}
[data-testid="stMetric"]::before {{
  content: ""; position: absolute; top: 0; left: 0; right: 0; height: 3px;
  background: {COL['acento']}; opacity: 0.85;
}}
[data-testid="stMetric"]:hover {{ border-color: {COL['borde2']}; }}
[data-testid="stMetricLabel"] {{ color: {COL['texto2']} !important; font-size: 0.82rem; font-weight: 500; }}
[data-testid="stMetricValue"] {{
  color: {COL['texto']} !important; font-family: 'IBM Plex Mono', monospace;
  font-weight: 600 !important;
}}
[data-testid="stMetricDelta"] {{ font-family: 'IBM Plex Mono', monospace; font-size: 0.8rem; }}

/* ----------------------------------------------------- contenedores / tarjetas */
div[data-testid="stVerticalBlockBorderWrapper"] {{
  border-radius: 14px !important;
  background: {COL['panel']}55;
}}
div[data-testid="stVerticalBlockBorderWrapper"] > div {{ border-radius: 14px !important; }}

/* -------------------------------------------------------------------- tabs */
[data-testid="stTabs"] [data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 1px solid {COL['borde']}; }}
[data-testid="stTabs"] [data-baseweb="tab"] {{
  color: {COL['texto2']}; font-weight: 500; padding: 8px 16px;
}}
[data-testid="stTabs"] [aria-selected="true"] {{ color: {COL['texto']} !important; }}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {{ background-color: {COL['acento']} !important; }}

/* ---------------------------------------------------------------- expander */
[data-testid="stExpander"] {{
  border: 1px solid {COL['borde']} !important; border-radius: 12px !important;
  background: {COL['panel']}44;
}}
[data-testid="stExpander"] summary {{ font-weight: 500; }}

/* ----------------------------------------------------------------- botones */
.stButton > button[kind="primary"], .stDownloadButton > button {{
  background: {COL['acento']}; color: #0B0620; border: none; font-weight: 600;
  border-radius: 8px; transition: filter 0.15s ease;
}}
.stButton > button[kind="primary"]:hover, .stDownloadButton > button:hover {{ filter: brightness(1.12); }}
.stButton > button[kind="secondary"] {{
  background: transparent; color: {COL['texto']}; border: 1px solid {COL['borde2']};
  border-radius: 8px; font-weight: 500;
}}
.stButton > button[kind="secondary"]:hover {{ border-color: {COL['acento']}; color: {COL['acento']}; }}

/* ----------------------------------------------------------------- tablas */
div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] {{
  border: 1px solid {COL['borde']}; border-radius: 10px; overflow: hidden;
}}

/* ------------------------------------------------------------------ varios */
hr {{ border-color: {COL['borde']}; }}
[data-testid="stProgress"] > div > div > div {{ background-color: {COL['acento']} !important; }}
[data-testid="stAlert"] {{ border-radius: 10px; border: 1px solid {COL['borde']}; }}
code {{ color: {COL['acento2']}; }}
</style>
"""


def preparar_pagina(titulo: str, icono: str = "◆", layout: str = "wide") -> None:
    st.set_page_config(page_title=f"{titulo} · Ulogix", page_icon=icono, layout=layout)
    st.markdown(_CSS, unsafe_allow_html=True)
    logo = ROOT / "app" / "assets" / "ulogix-dark.svg"
    if logo.exists():
        try:
            st.logo(str(logo))
        except Exception:  # noqa: BLE001 — versiones antiguas de Streamlit
            st.sidebar.image(str(logo))
    st.sidebar.markdown(
        '<div class="ulogix-sidebar-foot">ULOGIX &times; FEMSA/INDEGA<br/>'
        'Planta Fontibon &middot; Suite ERP + MES</div>',
        unsafe_allow_html=True)


def encabezado(eyebrow: str, titulo: str, sub: str = "") -> None:
    st.markdown(f'<div class="ulogix-eyebrow">{eyebrow}</div>', unsafe_allow_html=True)
    st.title(titulo)
    if sub:
        st.markdown(f'<p class="ulogix-sub">{sub}</p>', unsafe_allow_html=True)
    st.markdown('<hr class="ulogix-hr"/>', unsafe_allow_html=True)


def plotly_layout(fig, titulo: str = ""):
    fig.update_layout(
        title=dict(text=titulo or None, font=dict(size=15, color=COL["texto"]), x=0.0),
        template="plotly_dark",
        colorway=COLORWAY,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor=COL["panel"],
        font=dict(family="Sora, sans-serif", color=COL["texto2"], size=12),
        legend=dict(orientation="h", y=-0.22, x=0, bgcolor="rgba(0,0,0,0)",
                   bordercolor="rgba(0,0,0,0)", font=dict(color=COL["texto2"])),
        margin=dict(l=40, r=20, t=48 if titulo else 24, b=40),
        hoverlabel=dict(bgcolor=COL["panel2"], bordercolor=COL["borde2"],
                        font=dict(family="Sora, sans-serif", color=COL["texto"])),
        hovermode="closest",
        bargap=0.28,
        xaxis=dict(gridcolor=COL["borde"], zeroline=False, linecolor=COL["borde2"],
                  tickfont=dict(color=COL["texto2"])),
        yaxis=dict(gridcolor=COL["borde"], zeroline=False, linecolor=COL["borde2"],
                  tickfont=dict(color=COL["texto2"])),
    )
    return fig


# ------------------------------------------------------------------ datos compartidos
@st.cache_data(show_spinner="Ajustando modelos sobre los datos reales KOF y corriendo Monte Carlo...")
def datos_pronostico(mc_n: int = 10000):
    from config import settings
    if settings.EXTERNAL_ONLY:
        from integrations.sheets_client import Contabilidad
        cli = Contabilidad()
        mensual = cli.leer_dataset_pronostico("Forecast_Pronostico_Mensual")
        trimestral = cli.leer_dataset_pronostico("Forecast_Pronostico_Trimestral")
        metricas = cli.leer_dataset_pronostico("Forecast_Metricas")
        from core.forecast import cargar_historico_mensual, serie_trimestral_litros
        hist_m = cargar_historico_mensual()
        hist_q = serie_trimestral_litros().reset_index()
        return {"mensual": mensual, "trimestral": trimestral,
                "metricas": metricas,
                "supuestos": cli.leer_config_pronostico("resultado_supuestos"),
                "historico_mensual": hist_m, "historico_trimestral": hist_q,
                "validacion": cli.leer_config_pronostico("resultado_validacion")}
    from core.forecast import pronostico_base
    from integrations import state_store
    r = pronostico_base(mc_n=mc_n)
    try:  # persistencia ERP: cada recalculo es una corrida auditada
        state_store.guardar_pronostico(r.mensual, "Base")
    except Exception:
        pass
    try:  # ERP -> Sheets: la demanda Base tambien llega sola al libro (hoja
          # 'Demanda', rango fijo) sin depender de que alguien apriete un
          # boton en la pagina Finanzas — st.cache_data hace que esto corra
          # solo cuando el pronostico realmente cambia, no en cada rerun.
        from integrations.sheets_client import Contabilidad
        Contabilidad().publicar_demanda(r.mensual, "Base")
    except Exception:
        pass
    return {"mensual": r.mensual, "trimestral": r.trimestral,
            "metricas": r.metricas, "supuestos": r.supuestos,
            "historico_mensual": r.historico_mensual,
            "historico_trimestral": r.historico_trimestral,
            "validacion": r.validacion}


def resultado_base():
    """Reconstruye el ResultadoPronostico desde el cache (para escenarios)."""
    from core.forecast import ResultadoPronostico
    b = datos_pronostico()
    return ResultadoPronostico(
        mensual=b["mensual"], trimestral=b["trimestral"], metricas=b["metricas"],
        historico_mensual=b["historico_mensual"],
        historico_trimestral=b["historico_trimestral"],
        validacion=b["validacion"], supuestos=b["supuestos"])


def demanda_activa():
    """(nombre_escenario, df_mensual) segun el escenario activo en sesion."""
    from config import settings
    if settings.EXTERNAL_ONLY:
        import pandas as pd
        from integrations.sheets_client import Contabilidad
        esc = st.session_state.get("escenario_activo")
        nombre = esc.nombre if esc is not None else "Base"
        df = Contabilidad().leer_demanda(escenario=nombre != "Base")
        for c in df.columns:
            if str(c).endswith("_unidades") or c == "mes_num":
                df[c] = pd.to_numeric(df[c], errors="raise")
        if df.empty:
            raise RuntimeError(f"La hoja de demanda externa para {nombre} esta vacia")
        return nombre, df
    from core.escenarios import aplicar_escenario
    base = datos_pronostico()
    esc = st.session_state.get("escenario_activo")
    if esc is None or esc.nombre == "Base":
        return "Base", base["mensual"]
    return esc.nombre, aplicar_escenario(resultado_base(), esc)


def banner_escenario() -> None:
    nombre, _ = demanda_activa()
    if nombre == "Base":
        st.caption("Escenario activo: **Base** (cambialo en la pagina Escenarios).")
    else:
        st.info(f"Escenario activo: **{nombre}** — toda la suite (inventario, "
                f"compras, finanzas) usa esta demanda.", icon="🎛️")
