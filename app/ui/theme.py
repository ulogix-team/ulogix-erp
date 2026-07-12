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

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {{ font-family: 'Sora', sans-serif; }}
.stApp {{ background: {COL['base']}; }}
h1, h2, h3 {{ color: {COL['texto']} !important; letter-spacing: -0.01em; }}
[data-testid="stSidebar"] {{ background: {COL['panel']}; border-right: 1px solid #241A4E; }}
[data-testid="stMetric"] {{
  background: {COL['panel']}; border: 1px solid #241A4E; border-radius: 12px;
  padding: 14px 16px;
}}
[data-testid="stMetricLabel"] {{ color: {COL['texto2']}; }}
[data-testid="stMetricValue"] {{ color: {COL['texto']}; font-family: 'IBM Plex Mono', monospace; }}
.ulogix-eyebrow {{
  font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem;
  letter-spacing: 0.22em; text-transform: uppercase; color: {COL['acento']};
  margin-bottom: 0.15rem;
}}
.ulogix-sub {{ color: {COL['texto2']}; margin-top: -0.4rem; }}
.stButton > button[kind="primary"] {{ background: {COL['acento']}; color: {COL['base']};
  border: none; font-weight: 600; }}
div[data-testid="stDataFrame"] {{ border: 1px solid #241A4E; border-radius: 10px; }}
hr {{ border-color: #241A4E; }}
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


def encabezado(eyebrow: str, titulo: str, sub: str = "") -> None:
    st.markdown(f'<div class="ulogix-eyebrow">{eyebrow}</div>', unsafe_allow_html=True)
    st.title(titulo)
    if sub:
        st.markdown(f'<p class="ulogix-sub">{sub}</p>', unsafe_allow_html=True)


def plotly_layout(fig, titulo: str = ""):
    fig.update_layout(
        title=titulo or None,
        template="plotly_dark",
        paper_bgcolor=COL["base"], plot_bgcolor=COL["panel"],
        font=dict(family="Sora, sans-serif", color=COL["texto"]),
        legend=dict(orientation="h", y=-0.2),
        margin=dict(l=40, r=20, t=48 if titulo else 24, b=40),
        xaxis=dict(gridcolor="#241A4E"), yaxis=dict(gridcolor="#241A4E"),
    )
    return fig


# ------------------------------------------------------------------ datos compartidos
@st.cache_data(show_spinner="Ajustando modelos sobre los datos reales KOF y corriendo Monte Carlo...")
def datos_pronostico(mc_n: int = 10000):
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
