"""
Contabilidad de produccion: Google Sheets (gspread + cuenta de servicio) con
respaldo local en Excel (openpyxl) cuando no hay credenciales — la fase
financiera funciona end-to-end desde el primer dia.

Configuracion Google Sheets (una sola vez):
1. En Google Cloud Console crea un proyecto, habilita la API "Google Sheets".
2. Crea una CUENTA DE SERVICIO y descarga su JSON de credenciales; guardalo en
   config/google_service_account.json (o apunta GOOGLE_SA_JSON a otra ruta).
3. Crea un spreadsheet y compartelo (Editor) con el client_email del JSON.
4. Copia el ID del spreadsheet (la parte larga de la URL) a
   SHEETS_SPREADSHEET_ID en .env.

Hojas gestionadas:
- LibroProduccion : una fila por evento de produccion (ingreso/costo/margen).
- ResumenMensual  : agregado por mes y SKU.
- PlanCompras     : plan MRP activo (lo que se envio/enviara a Odoo).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings
from integrations import state_store

ENCABEZADOS_LIBRO = ["ts", "linea", "sku", "unidades", "precio_unit_cop",
                     "costo_unit_cop", "ingreso_cop", "costo_cop", "margen_cop"]


class Contabilidad:
    def __init__(self) -> None:
        self.modo = "sheets" if (settings.SHEETS_ENABLED and not settings.DRY_RUN_FORZADO) else "excel"
        self._ss = None

    # ------------------------------------------------------------- backends
    def _spreadsheet(self):
        if self._ss is None:
            import gspread
            gc = gspread.service_account(filename=settings.GOOGLE_SA_JSON)
            self._ss = gc.open_by_key(settings.SHEETS_SPREADSHEET_ID)
        return self._ss

    def _hoja(self, nombre: str, encabezados: list[str]):
        ss = self._spreadsheet()
        try:
            ws = ss.worksheet(nombre)
        except Exception:  # noqa: BLE001 — WorksheetNotFound
            ws = ss.add_worksheet(nombre, rows=2000, cols=max(12, len(encabezados)))
            ws.append_row(encabezados)
        if not ws.row_values(1):
            ws.append_row(encabezados)
        return ws

    def _excel_append(self, hoja: str, encabezados: list[str], filas: list[list]) -> None:
        from openpyxl import Workbook, load_workbook
        path = settings.LEDGER_XLSX
        wb = load_workbook(path) if path.exists() else Workbook()
        if "Sheet" in wb.sheetnames and len(wb.sheetnames) == 1 and hoja != "Sheet":
            wb.remove(wb["Sheet"])
        if hoja not in wb.sheetnames:
            ws = wb.create_sheet(hoja)
            ws.append(encabezados)
        ws = wb[hoja]
        for f in filas:
            ws.append(f)
        wb.save(path)

    def _escribir(self, hoja: str, encabezados: list[str], filas: list[list],
                  reemplazar: bool = False) -> str:
        if not filas:
            return self.modo
        if self.modo == "sheets":
            try:
                ws = self._hoja(hoja, encabezados)
                if reemplazar:
                    ws.clear()
                    ws.append_row(encabezados)
                ws.append_rows(filas, value_input_option="USER_ENTERED")
                state_store.log("sheets", f"append:{hoja}", f"{len(filas)} filas")
                return "sheets"
            except Exception as e:  # noqa: BLE001 — degradar a Excel local
                state_store.log("sheets", "ERROR -> fallback excel", str(e))
                self.modo = "excel"
        if reemplazar and settings.LEDGER_XLSX.exists():
            # borrar y recrear la hoja EN LA MISMA sesion: el libro nunca queda
            # con cero hojas visibles (openpyxl no permite guardarlo asi)
            from openpyxl import load_workbook
            wb = load_workbook(settings.LEDGER_XLSX)
            if hoja in wb.sheetnames:
                idx = wb.sheetnames.index(hoja)
                wb.remove(wb[hoja])
                ws = wb.create_sheet(hoja, idx)
                ws.append(encabezados)
                for f in filas:
                    ws.append(f)
                wb.save(settings.LEDGER_XLSX)
                state_store.log("contabilidad", f"excel:{hoja}",
                                f"{len(filas)} filas (reemplazo)")
                return "excel"
        self._excel_append(hoja, encabezados, filas)
        state_store.log("contabilidad", f"excel:{hoja}", f"{len(filas)} filas")
        return "excel"

    # ------------------------------------------------------------- operaciones
    def registrar_produccion(self, eventos: list[dict],
                             maestro: pd.DataFrame) -> tuple[str, pd.DataFrame]:
        """eventos: [{'ts','linea','sku','qty'}...] -> libro con margen."""
        m = maestro.set_index("sku")
        filas = []
        for ev in eventos:
            if ev["sku"] not in m.index:
                continue
            p = m.loc[ev["sku"]]
            ing = ev["qty"] * p["precio_venta_cop"]
            cos = ev["qty"] * p["costo_material_cop"]
            filas.append([ev.get("ts", datetime.now(timezone.utc).isoformat(timespec="seconds")),
                          ev.get("linea", ""), ev["sku"], ev["qty"],
                          float(p["precio_venta_cop"]), float(p["costo_material_cop"]),
                          round(ing), round(cos), round(ing - cos)])
        destino = self._escribir("LibroProduccion", ENCABEZADOS_LIBRO, filas)
        return destino, pd.DataFrame(filas, columns=ENCABEZADOS_LIBRO)

    def publicar_resumen_mensual(self, resumen: pd.DataFrame) -> str:
        return self._escribir("ResumenMensual", list(resumen.columns),
                              resumen.astype(object).values.tolist(), reemplazar=True)

    def publicar_plan_compras(self, plan: pd.DataFrame) -> str:
        return self._escribir("PlanCompras", list(plan.columns),
                              plan.astype(object).values.tolist(), reemplazar=True)


    def sincronizar_libro_completo(self, eventos: list[dict],
                                   maestro: pd.DataFrame) -> tuple[str, int]:
        """Reconstruye y REEMPLAZA LibroProduccion con todos los eventos
        (idempotente: sin duplicados al sincronizar varias veces)."""
        m = maestro.set_index("sku")
        filas = []
        for ev in eventos:
            if ev["sku"] not in m.index:
                continue
            p = m.loc[ev["sku"]]
            ing = ev["qty"] * p["precio_venta_cop"]
            cos = ev["qty"] * p["costo_material_cop"]
            filas.append([ev.get("ts", ""), ev.get("linea", ""), ev["sku"], ev["qty"],
                          float(p["precio_venta_cop"]), float(p["costo_material_cop"]),
                          round(ing), round(cos), round(ing - cos)])
        destino = self._escribir("LibroProduccion", ENCABEZADOS_LIBRO, filas,
                                 reemplazar=True)
        return destino, len(filas)


    # ------------------------------------------------------ integracion ERP v4
    def publicar_tiempos(self, demanda_mensual: pd.DataFrame | None = None) -> str:
        """Publica/actualiza la hoja Tiempos (estudio de tiempos por linea)."""
        from core.tiempos_oee import tabla_tiempos
        df = tabla_tiempos(demanda_mensual).fillna("")
        return self._escribir("Tiempos", list(df.columns),
                              df.astype(object).values.tolist(), reemplazar=True)

    def publicar_oee(self) -> str:
        """Publica/actualiza la hoja OEE (base medido vs +5% justificado)."""
        from core.tiempos_oee import tabla_oee
        df = tabla_oee().fillna("")
        return self._escribir("OEE", list(df.columns),
                              df.astype(object).values.tolist(), reemplazar=True)

    def registrar_kpis_uns(self, kpis: list[dict]) -> str:
        """Anexa KPIs recibidos del UNS (ts, linea, rama, kpi, valor)."""
        enc = ["ts", "linea", "rama", "kpi", "valor_num", "valor_txt", "topic"]
        filas = [[k.get(c, "") if k.get(c) is not None else "" for c in enc]
                 for k in kpis]
        return self._escribir("KPIs_UNS", enc, filas)

    # ---- contrato de demanda: rangos FIJOS (las hojas Financiero del libro
    # ---- referencian Demanda!D5:F16 y DemandaEscenario!D5:F16; por eso NO se
    # ---- usa clear+append sino escritura posicional que preserva las formulas)
    ENC_DEMANDA = ["escenario", "mes_num", "etiqueta",
                   "P1-CC350-RGB_unidades", "P2-QT1500-PET_unidades",
                   "P3-GARR25L_unidades"]

    def _escribir_rango(self, hoja: str, filas: list[list],
                        fila_inicio: int = 4) -> str:
        """Escribe un bloque en posicion fija (A{fila_inicio}) sin tocar el
        resto de la hoja. Crea la hoja si no existe."""
        if self.modo == "sheets":
            try:
                ss = self._spreadsheet()
                try:
                    ws = ss.worksheet(hoja)
                except Exception:  # noqa: BLE001
                    ws = ss.add_worksheet(hoja, rows=60, cols=20)
                ws.update(filas, f"A{fila_inicio}",
                          value_input_option="USER_ENTERED")
                state_store.log("sheets", f"rango:{hoja}",
                                f"{len(filas)} filas @A{fila_inicio}")
                return "sheets"
            except Exception as e:  # noqa: BLE001
                state_store.log("sheets", "ERROR -> fallback excel", str(e))
                self.modo = "excel"
        from openpyxl import Workbook, load_workbook
        path = settings.LEDGER_XLSX
        wb = load_workbook(path) if path.exists() else Workbook()
        if "Sheet" in wb.sheetnames and len(wb.sheetnames) == 1 and hoja != "Sheet":
            wb.remove(wb["Sheet"])
        ws = wb[hoja] if hoja in wb.sheetnames else wb.create_sheet(hoja)
        for i, fila in enumerate(filas):
            for j, v in enumerate(fila, 1):
                ws.cell(row=fila_inicio + i, column=j, value=v)
        wb.save(path)
        state_store.log("contabilidad", f"excel-rango:{hoja}", f"{len(filas)} filas")
        return "excel"

    def _filas_demanda(self, mensual: pd.DataFrame, escenario: str) -> list[list]:
        filas = [self.ENC_DEMANDA]
        for i, (_, r) in enumerate(mensual.reset_index(drop=True).iterrows(), 1):
            filas.append([escenario, i, r["etiqueta"],
                          int(r["P1-CC350-RGB_unidades"]),
                          int(r["P2-QT1500-PET_unidades"]),
                          int(r["P3-GARR25L_unidades"])])
        return filas

    def publicar_demanda(self, mensual: pd.DataFrame, escenario: str = "Base") -> str:
        """Demanda BASE -> hoja 'Demanda' (alimenta la hoja Financiero)."""
        return self._escribir_rango("Demanda", self._filas_demanda(mensual, escenario))

    ENC_INVENTARIOS = ["ts", "escenario", "sku", "punto_reorden_s",
                       "stock_seguridad", "lote_Q", "pallets_por_lote",
                       "fill_rate", "capital_inmovilizado_cop"]

    def publicar_inventarios(self, politicas: list[dict]) -> str:
        """Politica (s,Q) del ERP -> hoja 'Inventarios' (rango fijo A4:I8).
        `politicas`: filas de la tabla inventario_politicas (una por SKU)."""
        filas = [self.ENC_INVENTARIOS]
        for p in politicas[:4]:
            filas.append([p.get("ts", ""), p.get("escenario", ""), p.get("sku", ""),
                          p.get("punto_reorden_s", ""), p.get("stock_seguridad", ""),
                          p.get("lote_Q", ""), p.get("pallets_por_lote", ""),
                          p.get("fill_rate", ""), p.get("capital_inmovilizado_cop", "")])
        return self._escribir_rango("Inventarios", filas)

    def publicar_demanda_escenario(self, mensual: pd.DataFrame,
                                   escenario: str) -> str:
        """Demanda del ESCENARIO ACTIVO del ERP -> hoja 'DemandaEscenario'
        (alimenta la hoja FinancieroEscenario para evaluar el escenario)."""
        return self._escribir_rango("DemandaEscenario",
                                    self._filas_demanda(mensual, escenario))

    def leer_parametros(self) -> dict:
        """Lee la hoja Parametros (pares clave-valor) del libro en Drive; asi el
        libro de Sheets puede gobernar parametros del ERP. Fallback: Excel local.

        Contrato de claves que hoy consume `core.finanzas_negocio` (todas
        opcionales; si faltan, el motor usa su default local): TRM,
        FACTOR_RFQ, TMAR_ANUAL, UPLIFT_THROUGHPUT, FACTOR_MONETIZACION,
        RAMPA_MES5, SCRAP_PP, MANT_EVITADO_MES, TASA_RENTA, WC_PCT_INGRESO,
        CRECIMIENTO_DEMANDA_ANUAL, FASES_CAPEX ("0.20,0.35,0.27,0.18"),
        NOMINA_OPERACION_MES, NOMINA_IMPLEMENTACION_MES, OTROS_FIJOS_BASE_MES,
        OTROS_FIJOS_PROYECTO_MES, OPEX_LICENCIAS_MES, CAPEX_SOFTWARE,
        CONTINGENCIA, VIDA_equipos/VIDA_automatizacion/VIDA_servicios/
        VIDA_intangibles/VIDA_software (anios), y unit economics por SKU:
        precio_venta_cop_<SKU> / costo_material_cop_<SKU> (p.ej.
        `precio_venta_cop_P1-CC350-RGB`)."""
        try:
            if self.modo == "sheets":
                ws = self._spreadsheet().worksheet("Parametros")
                filas = ws.get_all_values()
            else:
                raise RuntimeError("modo excel")
        except Exception:  # noqa: BLE001
            from openpyxl import load_workbook
            if not settings.LEDGER_XLSX.exists():
                return {}
            wb = load_workbook(settings.LEDGER_XLSX, read_only=True)
            if "Parametros" not in wb.sheetnames:
                return {}
            filas = [[c if c is not None else "" for c in row]
                     for row in wb["Parametros"].iter_rows(values_only=True)]
        out = {}
        for fila in filas:
            if len(fila) >= 2 and str(fila[0]).strip():
                out[str(fila[0]).strip()] = fila[1]
        return out

    ENC_CAPEX = ["seccion", "linea", "activo", "cantidad", "moneda",
                "costo_unitario", "vida_anios", "categoria_dep"]

    def leer_capex(self) -> list[tuple]:
        """Lee la hoja 'CAPEX' (tabla, mismo esquema que CAPEX_FILAS de
        core.finanzas_negocio: seccion, linea, activo, cantidad, moneda,
        costo_unitario, vida_anios, categoria_dep) para que el CAPEX se
        gobierne desde Sheets en vez de la constante local. Fallback: lista
        vacia si la hoja no existe, esta vacia o no calza el encabezado
        esperado — el motor financiero cae entonces a su CAPEX_FILAS local."""
        try:
            if self.modo == "sheets":
                ws = self._spreadsheet().worksheet("CAPEX")
                filas = ws.get_all_values()
            else:
                raise RuntimeError("modo excel")
        except Exception:  # noqa: BLE001
            from openpyxl import load_workbook
            if not settings.LEDGER_XLSX.exists():
                return []
            wb = load_workbook(settings.LEDGER_XLSX, read_only=True)
            if "CAPEX" not in wb.sheetnames:
                return []
            filas = [[c if c is not None else "" for c in row]
                     for row in wb["CAPEX"].iter_rows(values_only=True)]
        if not filas or [str(c).strip() for c in filas[0][:8]] != self.ENC_CAPEX:
            return []
        salida = []
        for fila in filas[1:]:
            if len(fila) < 8 or not str(fila[0]).strip():
                continue
            try:
                salida.append((str(fila[0]).strip(), str(fila[1]).strip(),
                               str(fila[2]).strip(), float(fila[3]),
                               str(fila[4]).strip(), float(fila[5]),
                               float(fila[6]), str(fila[7]).strip()))
            except (TypeError, ValueError):
                continue  # fila mal diligenciada: se ignora, no revienta el motor
        return salida

    def probar(self) -> dict:
        """Prueba de conectividad: escribe y relee una celda de verificacion."""
        from datetime import datetime, timezone
        marca = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            destino = self._escribir("_PruebaAPI", ["ts", "origen"],
                                     [[marca, "ulogix-pruebas"]])
            if destino == "sheets":
                ws = self._spreadsheet().worksheet("_PruebaAPI")
                ultimo = ws.get_all_values()[-1][0]
                tabs = [w.title for w in self._spreadsheet().worksheets()]
                return {"ok": ultimo == marca, "modo": "sheets",
                        "detalle": f"celda escrita y releida OK; hojas: {tabs}"}
            return {"ok": True, "modo": "excel",
                    "detalle": f"sin credenciales Sheets: escrito en {settings.LEDGER_XLSX.name}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "modo": self.modo, "detalle": str(e)}


def libro_local() -> pd.DataFrame:
    """Lee el libro de produccion local (respaldo Excel) si existe."""
    if settings.LEDGER_XLSX.exists():
        try:
            return pd.read_excel(settings.LEDGER_XLSX, sheet_name="LibroProduccion")
        except ValueError:
            pass
    return pd.DataFrame(columns=ENCABEZADOS_LIBRO)
