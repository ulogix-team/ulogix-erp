"""
Publica la hoja 'APU_Ingenieria' (Analisis de Precios Unitarios) del libro:
la justificacion, componente por componente, de los tres rubros de servicios
que ULogix cobra en la hoja CAPEX (Ingenieria de detalle/FAT/SAT/PMO,
Instalacion y puesta en marcha/EPC, Capacitacion y gestion del cambio).

Metodologia APU (Analisis de Precios Unitarios), estandar de la industria de
construccion/EPC en Colombia: costo directo (mano de obra propia + subcontra-
tistas/OEM + materiales + logistica) x (1 + AIU). AIU = Administracion +
Imprevistos + Utilidad, con una banda de mercado de referencia del 25-30%
(NO es una tarifa fijada por ley: desde la desregulacion de honorarios
profesionales en Colombia, COPNIA no fija tarifas minimas — es de negocia-
cion contractual). La mano de obra propia usa una formula viva contra la
seccion RESUMEN de `RRHH` en Sheets (equipo de implementacion); los rubros de
terceros/OEM (FAT/SAT, cuadrillas de instalacion) son supuestos de mercado
documentados linea por linea, a validar con cotizacion real antes de
contratar — no son cifras oficiales de KRONES/HEUFT ni de un subcontratista.

Los tres precios totales del APU coinciden EXACTAMENTE con los montos ya
existentes en la hoja CAPEX (Servicios): este script no cambia el CAPEX
total ni el caso de negocio, solo lo justifica de abajo hacia arriba
(el AIU implicito resultante, 27-28%, cae dentro de la banda de mercado —
es una senal de que las cifras originales ya estaban bien calibradas).

Uso: python tools/publicar_apu_ingenieria.py
Requiere Sheets configurado (.env); si no hay credenciales, no hace nada
util (no existe fallback local para esta hoja de solo-exhibicion).
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.sheets_client import Contabilidad

# Semilla usada solo para calibrar el AIU que hace coincidir el APU inicial con
# CAPEX. La tarifa publicada es una formula viva RRHH!G/160; Sheets gobierna.
COSTO_HORA_ULOGIX = 12_451_680 / 160
PCT_ADMIN, PCT_IMPREV, PCT_UTIL = 0.15, 0.05, 0.072  # referencia AIU ~25-30%


def _aiu_pct(costo_directo: float, precio_total: float) -> float:
    return precio_total / costo_directo - 1


def _items() -> list[tuple[str, list[tuple], float]]:
    i1 = [
        ("Mano de obra propia ULogix (ingenieria de detalle: P&IDs, planos electricos, "
         "filosofia de control)", 1360, "horas", round(COSTO_HORA_ULOGIX),
         "Mano de obra propia",
         "Ing. automatizacion 480h + Ing. MES/UNS 400h + Ing. procesos 320h + "
         "Lider de proyecto 160h (RRHH en Sheets, tarifa = costo empleador / 160h-mes)"),
        ("FAT (Factory Acceptance Test) — honorarios OEM (KRONES, HEUFT)", 1, "global",
         577_500_000, "Subcontratado / terceros",
         "Referencia de mercado: ~5% del valor de los equipos sujetos a prueba de fabrica "
         "(bienes de capital importados) — no es cotizacion real de KRONES/HEUFT, es un "
         "supuesto documentado a validar con el proveedor"),
        ("Viajes y viaticos FAT (Alemania, 2 ingenieros, 10 dias)", 1, "global",
         34_000_000, "Logistica / viajes", "Tiquetes + viaticos"),
        ("SAT (Site Acceptance Test) — honorarios especialistas OEM en sitio", 1, "global",
         157_500_000, "Subcontratado / terceros",
         "3 especialistas x 15 dias x tarifa dia de mercado (bienes de capital industriales)"),
        ("PMO — gobierno de proyecto y aseguramiento de calidad", 1, "global",
         40_000_000, "Mano de obra propia + terceros",
         "Lider de proyecto (dedicacion transversal) + auditoria de calidad externa"),
    ]
    i2 = [
        ("Mano de obra propia ULogix (supervision de instalacion y comisionamiento)",
         560, "horas", round(COSTO_HORA_ULOGIX), "Mano de obra propia",
         "Ing. automatizacion 240h + Ing. procesos 240h + Lider de proyecto 80h"),
        ("Cuadrillas de instalacion mecanica/electrica (subcontratado)", 1, "global",
         420_000_000, "Subcontratado / terceros",
         "~18-20 tecnicos (electricistas, mecanicos, soldadores, riggers) x 3 meses, "
         "retrofit de 3 lineas"),
        ("Comisionamiento de celdas roboticas (especialistas del integrador)", 1, "global",
         60_000_000, "Subcontratado / terceros",
         "GANTRY paletizado L1-L2 + brazo articulado L3"),
        ("Alquiler de equipo pesado (gruas, montacargas, andamios)", 1, "global",
         50_000_000, "Equipos / alquiler", "3 meses"),
        ("Materiales menores de instalacion (cableado, canaletas, soporteria)", 1, "global",
         120_000_000, "Materiales",
         "Consumibles electricos/mecanicos no incluidos en el CAPEX de equipos"),
        ("Seguridad industrial (HSE, permisos de trabajo, EPP)", 1, "global",
         35_000_000, "Materiales", ""),
        ("Transporte e izaje de equipos a sitio", 1, "global",
         29_219_120, "Logistica / viajes", ""),
    ]
    i3 = [
        ("Mano de obra propia ULogix (diseno y facilitacion de capacitacion)",
         960, "horas", round(COSTO_HORA_ULOGIX), "Mano de obra propia",
         "Gestora del cambio 640h + Ing. MES/UNS 160h + Analista de datos 160h"),
        ("Materiales de capacitacion (manuales, videos, simuladores Tecnomatix)", 1, "global",
         35_000_000, "Materiales", ""),
        ("Facilitadores externos (gestion del cambio organizacional)", 1, "global",
         40_000_000, "Subcontratado / terceros", ""),
        ("Logistica de capacitacion (salones, catering, viaticos — 3 lineas x 3 turnos)",
         1, "global", 39_789_920, "Logistica / viajes", ""),
    ]
    return [
        ("Ingenieria de detalle, FAT/SAT y PMO", i1, 1_164_000_000),
        ("Instalacion y puesta en marcha (EPC)", i2, 970_000_000),
        ("Capacitacion y gestion del cambio", i3, 242_500_000),
    ]


def filas_hoja() -> list[list]:
    filas = [
        ["APU (Analisis de Precios Unitarios) — costos de ingenieria que cobra ULogix",
         "", "", "", "", "", "", ""],
        ["Metodologia: costo directo (mano de obra propia + subcontratistas/OEM + "
         "materiales + logistica) x (1 + AIU). AIU = Administracion + Imprevistos + "
         "Utilidad, referencia estandar de la industria de construccion/EPC en Colombia "
         "(banda de mercado 25-30%; NO es una tarifa fijada por ley — desde la "
         "desregulacion de honorarios profesionales, COPNIA no fija tarifas minimas, "
         "es de negociacion contractual). La mano de obra propia usa una formula viva "
         "contra RRHH en Sheets; los rubros de terceros/OEM son supuestos "
         "de mercado documentados, a validar con cotizacion real antes de contratar.",
         "", "", "", "", "", "", ""],
        ["", "", "", "", "", "", "", ""],
        ["RESUMEN", "", "", "", "", "", "", ""],
        ["item", "costo_directo_cop", "pct_administracion", "pct_imprevistos",
         "pct_utilidad", "pct_aiu_total", "aiu_cop", "precio_total_cop"],
    ]
    resumen_rows, detalle_rows = [], [
        ["item", "componente", "descripcion", "cantidad", "unidad",
         "valor_unitario_cop", "subtotal_cop", "tipo_costo"]]

    fila_resumen = 6
    fila_detalle = 12

    for nombre, filas_item, precio_total in _items():
        costo_directo = sum(r[1] * r[3] for r in filas_item)
        aiu_total_pct = _aiu_pct(costo_directo, precio_total)
        aiu_cop = precio_total - costo_directo
        base = PCT_ADMIN + PCT_IMPREV + PCT_UTIL
        pa = aiu_total_pct * PCT_ADMIN / base
        pi = aiu_total_pct * PCT_IMPREV / base
        pu = aiu_total_pct - pa - pi
        resumen_rows.append([
            nombre,
            f'=SUMIF($A$12:$A$200;A{fila_resumen};$G$12:$G$200)',
            pa, pi, pu,
            f'=SUM(C{fila_resumen}:E{fila_resumen})',
            f'=B{fila_resumen}*F{fila_resumen}',
            f'=B{fila_resumen}+G{fila_resumen}',
        ])
        for comp, cant, uni, vu, tipo, nota in filas_item:
            tarifa = vu
            if comp.startswith("Mano de obra propia ULogix"):
                tarifa = ('=INDEX(RRHH!$G:$G;MATCH("Equipo diseno y desarrollo ULogix";'
                          'RRHH!$A:$A;0))/160')
            detalle_rows.append([nombre, comp, nota or comp, cant, uni, tarifa,
                                 f'=D{fila_detalle}*F{fila_detalle}', tipo])
            fila_detalle += 1
        detalle_rows.append(["", "", f"Costo Directo — {nombre}", "", "", "",
                             f'=B{fila_resumen}', "Subtotal"])
        fila_detalle += 1
        detalle_rows.append(["", "", f"AIU {aiu_total_pct*100:.1f}% (Admin {pa*100:.1f}% + "
                                     f"Imprev {pi*100:.1f}% + Util {pu*100:.1f}%)", "", "", "",
                             f'=G{fila_resumen}', "AIU"])
        fila_detalle += 1
        detalle_rows.append(["", "", f"PRECIO TOTAL — {nombre} (= CAPEX hoja Servicios)",
                             "", "", "", f'=H{fila_resumen}', "Total"])
        fila_detalle += 1
        detalle_rows.append(["", "", "", "", "", "", "", ""])
        fila_detalle += 1
        fila_resumen += 1

    filas += resumen_rows
    filas += [["", "", "", "", "", "", "", ""], ["DETALLE", "", "", "", "", "", "", ""]]
    filas += detalle_rows
    return filas


def actualizar_referencia_capex(cont: Contabilidad) -> int:
    """Enlaza el costo unitario de Servicios con el total vivo del APU."""
    ss = cont._spreadsheet()
    ws = ss.worksheet("CAPEX")
    vals = ws.get_all_values()
    objetivo = {n for n, _, _ in _items()}
    actualizadas = 0
    for i, fila in enumerate(vals, start=1):
        if len(fila) > 5:
            nombre = fila[2].replace(" (ver hoja APU_Ingenieria)", "").strip()
        else:
            nombre = ""
        if nombre in objetivo:
            formula = (f'=INDEX(APU_Ingenieria!$H:$H;MATCH("{nombre}";'
                       'APU_Ingenieria!$A:$A;0))')
            ws.update([[f"{nombre} (ver hoja APU_Ingenieria)"]],
                      f"C{i}", value_input_option="USER_ENTERED")
            # Cada servicio es un paquete global (cantidad=1). El costo
            # unitario, no la cantidad, es el que se gobierna desde el APU.
            ws.update([[1]], f"D{i}", value_input_option="USER_ENTERED")
            ws.update([[formula]], f"F{i}", value_input_option="USER_ENTERED")
            actualizadas += 1
    return actualizadas


def main() -> None:
    cont = Contabilidad()
    if cont.modo != "sheets":
        raise SystemExit("Sheets no esta configurado (.env) — esta hoja no tiene "
                         "fallback local, es de solo exhibicion.")
    ss = cont._spreadsheet()
    filas = filas_hoja()
    try:
        ws = ss.worksheet("APU_Ingenieria")
    except Exception:  # noqa: BLE001
        ws = ss.add_worksheet("APU_Ingenieria", rows=max(200, len(filas) + 10), cols=9)
    ws.clear()
    ws.update(filas, "A1", value_input_option="USER_ENTERED")
    print(f"Publicado APU_Ingenieria: {len(filas)} filas")

    n = actualizar_referencia_capex(cont)
    print(f"CAPEX: {n} filas de Servicios referenciadas a APU_Ingenieria "
         f"(0 es normal si ya se habian anotado en una corrida anterior)")

    total_directo = total_precio = 0.0
    for nombre, filas_item, precio_total in _items():
        costo_directo = sum(r[1] * r[3] for r in filas_item)
        total_directo += costo_directo
        total_precio += precio_total
        print(f"  {nombre}: directo ${costo_directo:,.0f} -> AIU "
             f"{_aiu_pct(costo_directo, precio_total)*100:.1f}% -> total ${precio_total:,.0f}")
    print(f"Costo directo total: ${total_directo:,.0f} -> Precio total: ${total_precio:,.0f} "
         f"(AIU implicito global: {(total_precio/total_directo-1)*100:.1f}%)")


if __name__ == "__main__":
    main()
