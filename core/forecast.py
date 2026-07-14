"""
Pronostico de demanda v4 — sobre los DATOS REALES del repositorio Fontibon v3.

Fuentes (data/): kof_trimestral_colombia.json (21 trimestres reales KOF),
historico_planta.csv (mensual por producto, ene-2021 -> mar-2026),
historico_trimestral_planta.csv, parametros.json (SHARE/ENVASE/L_CU/RET-NR/W),
distribuciones.json (sigma de residuos, Normal aceptada KS/AD/chi2).

Metodologia (script 03 del repositorio + tres mejoras):

1. P1/P2: Holt-Winters con tendencia aditiva AMORTIGUADA y estacionalidad
   multiplicativa (m=4) sobre la serie trimestral REAL en litros por producto.

2. P3 (garrafon) — CORRECCION: el repositorio combinaba 50/50 los modelos
   (a) directo y (b) ligado-al-agua; el backtest muestra que eso EMPEORA el
   pronostico (MAPE 4.6% combinado vs 1.9% directo). Se implementa la
   combinacion OPTIMA de Bates & Granger (1969): pesos inversamente
   proporcionales al MSE de backtest de cada modelo,
       w_a = MSE_b / (MSE_a + MSE_b),
   que carga el peso hacia el modelo directo (~0.9) y recupera el MAPE ~2%.
   Se reportan los cuatro MAPEs (directo, ligado-agua, 50/50, optimo).

3. Diferenciacion P1 vs P2 — el historico reconstruido reparte refrescos con
   mezcla FIJA retornable/no-retornable (34/66), por lo que ambas series son
   colineales (r = 1.0) y los pronosticos salian "iguales a distinta escala".
   Dos mecanismos, documentados y editables, los separan en el horizonte:
   a) DERIVA DE MEZCLA: ret(t) = RET0 + deriva x (anios). La estrategia de
      asequibilidad de KOF empuja los retornables; default +0.5 pp/anio
      (data/parametros_planta.json: deriva_mix_retornable_anual). Conserva el
      total de refrescos: P1 escala con ret(t)/RET0 y P2 con (1-ret(t))/NR0.
   b) PERFIL DE FORMATO mensual (data/perfil_formato.csv): consumo individual
      (350 ml, on-premise) sube en jun-jul (vacaciones/eventos) y el formato
      familiar (1.5 L, hogar) sube en nov-dic; los pesos intra-trimestre W se
      multiplican por el perfil y se renormalizan DENTRO de cada trimestre,
      preservando los totales trimestrales del modelo estadistico.
   Resultado: corr mensual P1-P2 < 1 (se reporta en metricas/supuestos).

4. Historicos: el resultado expone las series mensual y trimestral reales
   (y el ajuste in-sample) para graficarlas junto al pronostico.

Bandas Monte Carlo: N=10.000 (semilla 42), residuos ~ Normal (sigma de
distribuciones.json o recalculada), centradas en la demanda del escenario.
Validacion adicional: un-paso 2025T4 -> 2026T1 contra el dato real.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings

warnings.filterwarnings("ignore")

MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
         "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
PROD = ["P1", "P2", "P3"]
SKU_DE = {"P1": "P1-CC350-RGB", "P2": "P2-QT1500-PET", "P3": "P3-GARR25L"}
PROD_DE_SKU = {v: k for k, v in SKU_DE.items()}
HORIZONTE_Q = [(2026, 2), (2026, 3), (2026, 4), (2027, 1)]  # Abr-26 -> Mar-27


def normalizar_demanda_mensual(df: pd.DataFrame) -> pd.DataFrame:
    """Restablece el contrato temporal de una demanda mensual externa.

    Google Sheets interpreta etiquetas como ``Abr-26`` como fechas y, al
    leerlas con ``UNFORMATTED_VALUE``, devuelve seriales (por ejemplo 46138).
    Las hojas fijas ``Demanda``/``DemandaEscenario`` tampoco almacenan
    ``ano`` ni ``mes``. Esta funcion reconstruye ambas columnas y deja una
    etiqueta canonica ``Mes-AA`` sin alterar ``mes_num`` (que en esas hojas
    es el indice 1..12 usado por las formulas financieras).
    """
    out = df.copy()
    if out.empty:
        return out

    fechas = pd.Series(pd.NaT, index=out.index, dtype="datetime64[ns]")
    mapa_mes = {m.lower(): i for i, m in enumerate(MESES, 1)}
    mapa_mes.update({
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
        "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
        "septiembre": 9, "setiembre": 9, "octubre": 10,
        "noviembre": 11, "diciembre": 12,
    })

    # 1) El pronostico completo trae ano/mes explicitos: son la autoridad.
    # Sheets puede convertir "Ene-27" en 27-ene-2026, por lo que el serial de
    # etiqueta NO debe sobreescribir estos campos correctos.
    if {"ano", "mes"}.issubset(out.columns):
        for idx in out.index:
            try:
                mes_num = mapa_mes[str(out.at[idx, "mes"]).strip().lower()]
                fechas.loc[idx] = pd.Timestamp(int(out.at[idx, "ano"]), mes_num, 1)
            except (KeyError, TypeError, ValueError):
                continue

    # 2) Demanda/DemandaEscenario no guardan ano/mes, pero mes_num es el
    # ordinal 1..12 del horizonte fijo Abr-26 -> Mar-27.
    if "mes_num" in out:
        ordinales = pd.to_numeric(out["mes_num"], errors="coerce")
        inicio = pd.Period(settings.HORIZONTE_INICIO, freq="M")
        for idx in fechas[fechas.isna()].index:
            ordinal = ordinales.loc[idx]
            if pd.notna(ordinal) and ordinal >= 1:
                fechas.loc[idx] = (inicio + int(ordinal) - 1).to_timestamp()

    # 3) La etiqueta queda como ultimo recurso para tablas historicas o
    # contratos antiguos que no tengan ninguno de los campos anteriores.
    if "etiqueta" in out:
        etiquetas = out["etiqueta"]
        pendientes = fechas.isna()
        seriales = pd.to_numeric(etiquetas, errors="coerce")
        validos = pendientes & seriales.notna()
        if validos.any():
            fechas.loc[validos] = pd.to_datetime(
                seriales.loc[validos], unit="D", origin="1899-12-30",
                errors="coerce")
        for idx in fechas[fechas.isna()].index:
            texto = str(etiquetas.loc[idx]).strip()
            partes = texto.replace("/", "-").split("-")
            if len(partes) == 2 and partes[0].lower() in mapa_mes:
                try:
                    ano = int(partes[1])
                    ano += 2000 if ano < 100 else 0
                    fechas.loc[idx] = pd.Timestamp(ano, mapa_mes[partes[0].lower()], 1)
                    continue
                except (TypeError, ValueError):
                    pass
            fechas.loc[idx] = pd.to_datetime(texto, errors="coerce", dayfirst=True)

    if fechas.notna().any():
        validos = fechas.notna()
        if "etiqueta" in out:
            out["etiqueta"] = out["etiqueta"].astype(object)
        out.loc[validos, "ano"] = fechas.loc[validos].dt.year.astype(int)
        out.loc[validos, "mes"] = fechas.loc[validos].dt.month.map(
            lambda numero: MESES[int(numero) - 1])
        out.loc[validos, "etiqueta"] = fechas.loc[validos].map(
            lambda fecha: f"{MESES[fecha.month - 1]}-{str(fecha.year)[2:]}")
        out["ano"] = pd.to_numeric(out["ano"], errors="coerce").astype("Int64")

    for columna in out.columns:
        if (str(columna).endswith(("_unidades", "_litros", "_p05", "_p95"))
                or columna == "mes_num"):
            out[columna] = pd.to_numeric(out[columna], errors="raise")
    return out


# ----------------------------------------------------------------- carga
def _dd() -> Path:
    return settings.DATA_DIR


@lru_cache(maxsize=1)
def _contabilidad():
    from integrations.sheets_client import Contabilidad
    return Contabilidad()


@lru_cache(maxsize=1)
def cargar_parametros_repo() -> dict:
    par = (_contabilidad().leer_config_pronostico("parametros_repo")
           if settings.EXTERNAL_ONLY else
           json.load(open(_dd() / "parametros.json", encoding="utf-8")))
    par["W"] = {int(k): v for k, v in par["W"].items()}
    return par


@lru_cache(maxsize=1)
def cargar_parametros() -> dict:  # parametros de planta (OEE, lineas, negocio)
    if settings.EXTERNAL_ONLY:
        return _contabilidad().leer_config_pronostico("parametros_planta")
    return json.load(open(_dd() / "parametros_planta.json", encoding="utf-8"))


@lru_cache(maxsize=1)
def cargar_maestro() -> pd.DataFrame:
    if settings.EXTERNAL_ONLY:
        return _contabilidad().leer_maestro_productos()
    return pd.read_csv(_dd() / "maestro_productos.csv")


@lru_cache(maxsize=1)
def cargar_historico_mensual() -> pd.DataFrame:
    df = (_contabilidad().leer_dataset_pronostico("Forecast_Historico_Mensual")
          if settings.EXTERNAL_ONLY else
          pd.read_csv(_dd() / "historico_planta.csv"))
    serial = pd.to_numeric(df["fecha"], errors="coerce")
    if serial.notna().all():
        df["fecha"] = pd.to_datetime(serial, unit="D", origin="1899-12-30")
    else:
        df["fecha"] = pd.to_datetime(df["fecha"])
    return df.sort_values(["producto", "fecha"]).reset_index(drop=True)


@lru_cache(maxsize=1)
def serie_trimestral_litros() -> pd.DataFrame:
    dq = (_contabilidad().leer_dataset_pronostico("Forecast_Historico_Trimestral")
          if settings.EXTERNAL_ONLY else
          pd.read_csv(_dd() / "historico_trimestral_planta.csv"))
    for c in ["anio", "trim", "litros"]:
        dq[c] = pd.to_numeric(dq[c], errors="raise")
    dq["t"] = pd.PeriodIndex([f"{y}Q{q}" for y, q in zip(dq.anio, dq.trim)],
                             freq="Q").to_timestamp()
    return dq.pivot_table(index="t", columns="producto", values="litros").asfreq("QS")


@lru_cache(maxsize=1)
def cargar_perfil_formato() -> dict[str, list[float]]:
    df = (_contabilidad().leer_dataset_pronostico("Forecast_Perfil_Formato")
          if settings.EXTERNAL_ONLY else
          pd.read_csv(_dd() / "perfil_formato.csv"))
    for c in PROD:
        df[c] = pd.to_numeric(df[c], errors="raise")
    return {p: df[p].tolist() for p in PROD}  # indice 0 = enero


@lru_cache(maxsize=1)
def cargar_kof() -> dict:
    if settings.EXTERNAL_ONLY:
        df = _contabilidad().leer_dataset_pronostico("Forecast_KOF_Trimestral")
        return {str(r["k"]): {c: r[c] for c in df.columns if c != "k"}
                for _, r in df.iterrows()}
    return json.load(open(_dd() / "kof_trimestral_colombia.json"))


@lru_cache(maxsize=1)
def cargar_distribuciones() -> dict:
    if settings.EXTERNAL_ONLY:
        return _contabilidad().leer_config_pronostico("distribuciones")
    return json.load(open(_dd() / "distribuciones.json"))


def limpiar_cache_fuentes() -> None:
    """Una lectura por fuente y corrida; evita agotar la cuota de Sheets."""
    for funcion in (_contabilidad, cargar_parametros_repo, cargar_parametros,
                    cargar_maestro, cargar_historico_mensual,
                    serie_trimestral_litros, cargar_perfil_formato,
                    cargar_kof, cargar_distribuciones):
        funcion.cache_clear()


# ----------------------------------------------------------------- modelos
def _hw(serie: pd.Series):
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    return ExponentialSmoothing(serie.astype(float), trend="add",
                                damped_trend=True, seasonal="mul",
                                seasonal_periods=4,
                                initialization_method="estimated").fit()


def _modelo_ligado_agua(hasta=None, horizonte: int = 4):
    """Modelo (b) del script 03: W=agua+garrafon (HW) x share garrafon (SES),
    escalado a litros de planta. Devuelve (forecast, fitted, params)."""
    from statsmodels.tsa.holtwinters import (ExponentialSmoothing,
                                             SimpleExpSmoothing)
    kof = cargar_kof()
    par = cargar_parametros_repo()
    esc = par["SHARE"]["P3"] * par["L_CU"] * 1e6
    df = pd.DataFrame([dict(k=k, **v) for k, v in sorted(kof.items())])
    df["t"] = pd.PeriodIndex(df.k, freq="Q").to_timestamp()
    df = df.set_index("t")
    if hasta is not None:
        df = df[:hasta]
    W = (df["agua"] + df["garrafon"]).asfreq("QS")
    s = (df["garrafon"] / (df["agua"] + df["garrafon"])).asfreq("QS")
    mW = ExponentialSmoothing(W, trend="add", damped_trend=True, seasonal="mul",
                              seasonal_periods=4,
                              initialization_method="estimated").fit()
    mS = SimpleExpSmoothing(s, initialization_method="estimated").fit()
    fc = (mW.forecast(horizonte).values * float(mS.forecast(1).iloc[0])) * esc
    fitted = (mW.fittedvalues * mS.fittedvalues).values * esc
    return fc, fitted, dict(alpha_W=round(mW.params["smoothing_level"], 4),
                            share_fcst=round(float(mS.forecast(1).iloc[0]), 4))


def _backtest_un_paso(serie: pd.Series, n: int = 5,
                      modelo="hw") -> tuple[np.ndarray, np.ndarray]:
    """Backtest expanding-window de un paso sobre los ultimos n trimestres.
    Devuelve (reales, predichos)."""
    reales, preds = [], []
    for i in range(n, 0, -1):
        train = serie.iloc[:-i]
        if modelo == "hw":
            pred = float(_hw(train).forecast(1).iloc[0])
        else:  # 'agua' — corta el modelo compuesto en la fecha de train
            fc, _, _ = _modelo_ligado_agua(hasta=train.index[-1], horizonte=1)
            pred = float(fc[0])
        preds.append(pred)
        reales.append(float(serie.iloc[-i]))
    return np.array(reales), np.array(preds)


def _metricas(reales: np.ndarray, preds: np.ndarray) -> dict:
    err = reales - preds
    mad = float(np.mean(np.abs(err)))
    return {"mape": float(np.mean(np.abs(err / reales))),
            "mad": round(mad), "rmse": round(float(np.sqrt(np.mean(err ** 2)))),
            "mse": float(np.mean(err ** 2)),
            "tracking_signal": round(float(err.sum() / (mad + 1e-9)), 2),
            "sigma_rel": float(np.std(err / reales, ddof=1))}


# ----------------------------------------------------------------- resultado
@dataclass
class ResultadoPronostico:
    mensual: pd.DataFrame            # horizonte Abr26-Mar27 por SKU + bandas
    trimestral: pd.DataFrame         # pronostico trimestral (litros) por producto
    metricas: pd.DataFrame           # backtest por producto (+ comparacion P3)
    historico_mensual: pd.DataFrame  # serie real mensual por producto
    historico_trimestral: pd.DataFrame  # litros trimestrales reales (pivot)
    validacion: dict = field(default_factory=dict)   # un-paso 2026T1
    supuestos: dict = field(default_factory=dict)


def pronostico_base(mc_n: int | None = None, semilla: int | None = None) -> ResultadoPronostico:
    limpiar_cache_fuentes()
    mc_n = mc_n or settings.MC_N
    rng = np.random.default_rng(settings.SEMILLA if semilla is None else semilla)
    par = cargar_parametros_repo()
    planta = cargar_parametros()
    dist = cargar_distribuciones()
    piv = serie_trimestral_litros()
    W = par["W"]
    perfil = cargar_perfil_formato()
    deriva = float(planta.get("deriva_mix_retornable_anual", 0.005))
    RET0, NR0 = par["RET"], par["NR"]

    metricas_rows, fcQ, val = [], {}, {}

    # ---------------- P1 / P2: HW amortiguado sobre litros trimestrales
    for p in ["P1", "P2"]:
        serie = piv[p]
        reales, preds = _backtest_un_paso(serie, n=5, modelo="hw")
        m = _metricas(reales, preds)
        # validacion un-paso 2026T1 (ultimo punto del backtest)
        val[p] = dict(pred_2026T1=round(preds[-1]), real_2026T1=round(reales[-1]),
                      error_pct=round((preds[-1] / reales[-1] - 1) * 100, 2))
        mod = _hw(serie)
        fcQ[p] = mod.forecast(4).values
        metricas_rows.append({"producto": p, "modelo": "HW amortiguado m=4 (litros)",
                              **m, "peso_combinacion": 1.0})

    # ---------------- P3: combinacion OPTIMA Bates-Granger (correccion)
    serie3 = piv["P3"]
    rA, pA = _backtest_un_paso(serie3, n=5, modelo="hw")        # (a) directo
    rB, pB = _backtest_un_paso(serie3, n=5, modelo="agua")      # (b) ligado agua
    mA, mB = _metricas(rA, pA), _metricas(rB, pB)
    m50 = _metricas(rA, (pA + pB) / 2)
    wA = mB["mse"] / (mA["mse"] + mB["mse"])                    # peso optimo
    mOpt = _metricas(rA, wA * pA + (1 - wA) * pB)
    fcA = _hw(serie3).forecast(4).values
    fcB, _, prB = _modelo_ligado_agua(horizonte=4)
    fcQ["P3"] = wA * fcA + (1 - wA) * fcB
    predO = wA * pA[-1] + (1 - wA) * pB[-1]
    val["P3"] = dict(pred_2026T1=round(predO), real_2026T1=round(rA[-1]),
                     error_pct=round((predO / rA[-1] - 1) * 100, 2),
                     detalle=dict(directo_pct=round((pA[-1] / rA[-1] - 1) * 100, 2),
                                  agua_pct=round((pB[-1] / rA[-1] - 1) * 100, 2)))
    metricas_rows.append({"producto": "P3",
                          "modelo": f"Bates-Granger OPTIMO (w_directo={wA:.2f})",
                          **mOpt, "peso_combinacion": round(wA, 3)})
    comparacion_p3 = {"P3_directo": round(mA["mape"] * 100, 2),
                      "P3_ligado_agua": round(mB["mape"] * 100, 2),
                      "P3_combinado_50_50 (repo v3)": round(m50["mape"] * 100, 2),
                      "P3_combinacion_optima (v4)": round(mOpt["mape"] * 100, 2)}

    metricas = pd.DataFrame(metricas_rows)

    # ---------------- trimestral pronosticado (litros)
    trimestral = pd.DataFrame(
        [{"anio": y, "trim": q, "trimestre": f"{y}Q{q}",
          **{p: round(fcQ[p][i], 1) for p in PROD}}
         for i, (y, q) in enumerate(HORIZONTE_Q)])

    # ---------------- mensualizacion con W x perfil de formato + deriva de mezcla
    sigma = {p: (dist[p]["sigma"] if p in dist else metricas.loc[
        metricas["producto"] == p, "sigma_rel"].iloc[0]) for p in PROD}
    filas = []
    for i, (y, q) in enumerate(HORIZONTE_Q):
        # deriva de mezcla retornable (aplicada al trimestre i del horizonte)
        anios = (i + 0.5) / 4
        ret_t = RET0 + deriva * anios
        ajuste_mix = {"P1": ret_t / RET0, "P2": (1 - ret_t) / NR0, "P3": 1.0}
        # pesos mensuales renormalizados dentro del trimestre por producto
        meses_q = [(q - 1) * 3 + j for j in range(3)]           # indices 0-11
        for p in PROD:
            pesos = np.array([W[q][j] * perfil[p][meses_q[j]] for j in range(3)])
            pesos = pesos / pesos.sum()
            for j in range(3):
                mes_idx = meses_q[j]
                lit = fcQ[p][i] * pesos[j] * ajuste_mix[p]
                filas.append(dict(ano=y, mes_num=mes_idx + 1, producto=p,
                                  litros=lit))
    dm = pd.DataFrame(filas)

    par_env = par["ENVASE"]
    mensual_rows = []
    for (y, mnum), g in dm.groupby(["ano", "mes_num"], sort=False):
        fila = {"ano": int(y), "mes": MESES[mnum - 1],
                "etiqueta": f"{MESES[mnum - 1]}-{str(y)[2:]}"}
        for _, r in g.iterrows():
            p, sku = r["producto"], SKU_DE[r["producto"]]
            unidades = r["litros"] / par_env[p]
            sims = unidades * (1 + rng.normal(dist[p]["mu"], sigma[p], size=mc_n))
            fila[f"{sku}_litros"] = round(r["litros"])
            fila[f"{sku}_unidades"] = round(unidades)
            fila[f"{sku}_p05"] = round(float(np.percentile(sims, 5)))
            fila[f"{sku}_p95"] = round(float(np.percentile(sims, 95)))
        mensual_rows.append(fila)
    mensual = pd.DataFrame(mensual_rows)
    # orden Abr-26 -> Mar-27
    mensual = mensual.sort_values(["ano", "mes"],
                                  key=lambda s: s.map({m: i for i, m in enumerate(MESES)})
                                  if s.name == "mes" else s).reset_index(drop=True)

    # ---------------- correlacion P1-P2 mensual (antes = 1.0 por construccion)
    corr_v4 = float(np.corrcoef(mensual["P1-CC350-RGB_unidades"],
                                mensual["P2-QT1500-PET_unidades"])[0, 1])

    hist_m = cargar_historico_mensual()
    supuestos = {
        "fuente_datos": "21 trimestres reales KOF Colombia (2021T1-2026T1) -> escala planta (script 01)",
        "share_planta": par["SHARE"], "envase_L": par_env,
        "mezcla_retornable": {"RET0": RET0, "NR0": NR0,
                              "deriva_anual_pp": deriva * 100},
        "perfil_formato": "data/perfil_formato.csv (S7, editable; renormalizado por trimestre)",
        "comparacion_modelos_P3_MAPE_pct": comparacion_p3,
        "correlacion_mensual_P1P2": {"historico (mezcla fija)": 1.0,
                                     "pronostico v4": round(corr_v4, 4)},
        "mc_n": mc_n, "horizonte": "Abr-2026 a Mar-2027",
        "params_ligado_agua": prB,
    }
    return ResultadoPronostico(mensual=mensual, trimestral=trimestral,
                               metricas=metricas, historico_mensual=hist_m,
                               historico_trimestral=piv.reset_index(),
                               validacion=val, supuestos=supuestos)


def exportar_base(res: ResultadoPronostico | None = None) -> Path:
    res = res or pronostico_base()
    out = _dd() / "pronostico_base_mensual.csv"
    res.mensual.to_csv(out, index=False)
    res.trimestral.to_csv(_dd() / "pronostico_trimestral.csv", index=False)
    res.metricas.to_csv(_dd() / "metricas_backtest.csv", index=False)
    return out


if __name__ == "__main__":
    r = pronostico_base(mc_n=2000)
    pd.set_option("display.width", 200)
    print(r.metricas[["producto", "modelo", "mape", "tracking_signal",
                      "peso_combinacion"]].to_string(index=False))
    print("\nComparacion P3 (MAPE %):", r.supuestos["comparacion_modelos_P3_MAPE_pct"])
    print("Correlacion P1-P2:", r.supuestos["correlacion_mensual_P1P2"])
    print("Validacion 2026T1:", json.dumps(r.validacion, indent=1))
    print("\n", r.mensual[["etiqueta"] + [c for c in r.mensual.columns
                                          if c.endswith("_unidades")]].to_string(index=False))
