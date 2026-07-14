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

Los tres precios totales se calculan desde el detalle vivo y alimentan las
filas Servicios de CAPEX. El alcance incluye mecanica, controles, RobotStudio,
Siemens NX, Tecnomatix Plant Simulation, Ignition SCADA, MES/UNS Coreflux y
ERP/Odoo. Las licencias se mantienen en la hoja Licencias para no duplicarlas.

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
    h = round(COSTO_HORA_ULOGIX)
    propia = "Mano de obra propia"
    i1 = [
        ("Ingenieria de proceso y dimensionamiento de capacidad", 320, "horas", h, propia,
         "Balance antes/despues, OEE, demanda, holgura y especificacion de llenadoras usadas"),
        ("Diseño mecanico encajonadora 30x30 y GANTRY compartido", 480, "horas", h, propia,
         "Layout, grippers, transportadores, alternancia L1/L2, planos y BOM"),
        ("Ingenieria electrica, seguridad y control ABB", 420, "horas", h, propia,
         "IRC5, servos, I/O, redes, interlocks, matrices causa-efecto y filosofia de control"),
        ("ABB RobotStudio: trayectorias y virtual commissioning", 320, "horas", h, propia,
         "RAPID, colisiones, ciclos, grippers y validacion virtual de celdas"),
        ("Siemens NX: gemelos digitales mecatronicos", 360, "horas", h, propia,
         "Celdas, embotellado, encajonado y paletizado; interfaces CAD con RobotStudio"),
        ("Tecnomatix Plant Simulation: modelo integral de planta", 400, "horas", h, propia,
         "L1-L3, turnos, buffers, fallas, OEE, escenarios y capacidad"),
        ("Ignition SCADA e historian", 360, "horas", h, propia,
         "Sinopticos, tags, alarmas, tendencias, presion y equipos de las tres lineas"),
        ("MES, Coreflux MQTT y UNS", 480, "horas", h, propia,
         "79 topicos, OEE/KPI/eventos/alarmas, trazabilidad y AvailableQuantity"),
        ("ERP/Odoo y analitica de demanda", 320, "horas", h, propia,
         "Pronostico, MRP, inventarios, compras, MO, ventas, facturacion e integracion MES"),
        ("Ciberseguridad OT, edge y arquitectura de datos", 160, "horas", h, propia,
         "Segmentacion, backups, hardening, usuarios, certificados y recuperacion"),
        ("PMO, documentacion, QA y protocolos FAT/SAT", 320, "horas", h, propia,
         "Plan maestro, riesgos, control de cambios, manuales y trazabilidad de pruebas"),
        ("Inspeccion tecnica y due diligence de maquinaria usada", 2, "equipos", 45_000_000,
         "Subcontratado / terceros", "Llenadoras KRONES L1/L2: condicion, formatos, repuestos y prueba en vacio"),
        ("FAT remoto/presencial y viaticos", 1, "global", 32_000_000,
         "Logistica / viajes", "Pruebas de fillers/Variopac y celdas; cotizar antes de adjudicar"),
    ]
    i2 = [
        ("Supervision ULogix de desmontaje, montaje y comisionamiento", 1200, "horas", h,
         propia, "Coordinacion mecanica, electrica, automatizacion, software y arranque"),
        ("Especialistas OEM maquinaria KRONES usada L1/L2", 1, "global", 180_000_000,
         "Subcontratado / terceros", "Ajuste de formatos, overhaul selectivo, puesta a punto y SAT"),
        ("Cuadrillas mecanicas/electricas y rigging", 1, "global", 220_000_000,
         "Subcontratado / terceros", "Montaje de fillers, Variopac, encajonadora, conveyors y celdas"),
        ("Comisionamiento celdas ABB y GANTRY", 1, "global", 45_000_000,
         "Subcontratado / terceros", "GANTRY compartido L1/L2 y robot garrafones L3"),
        ("Gruas, montacargas, alineacion y andamios", 1, "global", 45_000_000,
         "Equipos / alquiler", "Ventanas de parada coordinadas por linea"),
        ("Cableado, canaletas, soporteria y consumibles", 1, "global", 90_000_000,
         "Materiales", "Material menor no incluido en BOM de equipos"),
        ("Seguridad industrial HSE", 1, "global", 25_000_000,
         "Materiales", "Permisos, LOTO, EPP, pruebas de seguridad y dossier"),
        ("Transporte local, izaje y nacionalizacion complementaria", 1, "global", 55_000_000,
         "Logistica / viajes", "No duplica envios incluidos en cotizaciones EUROBOTS/IGAM"),
    ]
    i3 = [
        ("Diseño y facilitacion de capacitacion ULogix", 900, "horas", h, propia,
         "Operaciones, mantenimiento, SCADA, MES, ERP, UNS, NX, Tecnomatix y RobotStudio"),
        ("Manuales, videos, SOP y escenarios de simulacion", 1, "global", 25_000_000,
         "Materiales", "Entregables editables y ejercicios por rol"),
        ("Especialistas externos/OEM", 1, "global", 20_000_000,
         "Subcontratado / terceros", "Formacion especifica KRONES y ABB"),
        ("Logistica de entrenamiento por turnos", 1, "global", 25_000_000,
         "Logistica / viajes", "Cobertura L1/L2 tres turnos y L3 un turno"),
    ]
    items = []
    for nombre, detalle, aiu in (("Ingenieria de detalle, FAT/SAT y PMO", i1, 0.275),
                                 ("Instalacion y puesta en marcha (EPC)", i2, 0.28),
                                 ("Capacitacion y gestion del cambio", i3, 0.28)):
        directo = sum(r[1] * r[3] for r in detalle)
        items.append((nombre, detalle, round(directo * (1 + aiu))))
    return items


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
            if tipo == "Mano de obra propia":
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
