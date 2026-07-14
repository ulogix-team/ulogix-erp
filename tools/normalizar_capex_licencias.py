"""Normaliza CAPEX por linea de proyecto y corrige el alcance de licencias.

La hoja CAPEX se reconstruye en cinco bloques legibles: L1, L2, equipo
compartido L1-L2, L3 y transversal L1-L2-L3. Se preservan las 85 filas de
datos y sus entradas editables, pero se corrigen las etiquetas heredadas de
la planta (L2 330 ml, L3 PET y L7 Agua) a las lineas vigentes L1/L2/L3.

La hoja Licencias separa:
  * CAPEX: licencias perpetuas (Studio 5000 e Ignition).
  * OPEX: suscripciones de ingenieria/operacion (RobotStudio, NX,
    Plant Simulation, Coreflux, Odoo y hosting del MES/ERP).
  * Fuera de alcance: Azure IoT y LabVIEW, conservados en cantidad cero.

Finalmente, la fila Software de CAPEX referencia el total vivo de Licencias;
ya no contiene un valor pegado. No toca ninguna otra hoja del libro.

Uso: python tools/normalizar_capex_licencias.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from integrations.sheets_client import Contabilidad


EUR_COP = 3_815.50  # referencia EUR/COP 08-jul-2026; editable en Parametros

LINEAS = {
    "L1": "L1 — COCA-COLA 350 ml · VIDRIO RETORNABLE",
    "L2": "L2 — QuAtro 1,5 L · PET",
    "L1-L2": "L1-L2 — GANTRY DE PALETIZADO COMPARTIDO",
    "L3": "L3 — GARRAFÓN 25 L · LLENADORA EXISTENTE",
    "COMUN": "TRANSVERSAL — L1 + L2 + L3",
}

COLOR_LINEA = {
    "L1": {"red": 0.80, "green": 0.16, "blue": 0.18},
    "L2": {"red": 0.10, "green": 0.38, "blue": 0.72},
    "L1-L2": {"red": 0.88, "green": 0.48, "blue": 0.10},
    "L3": {"red": 0.10, "green": 0.55, "blue": 0.34},
    "COMUN": {"red": 0.35, "green": 0.24, "blue": 0.65},
}

ORDEN_SECCION = {
    "Maquinaria usada": 10,
    "Diseño ULogix": 20,
    "Celdas roboticas (BOM real)": 30,
    "Benchmark retrofit": 40,
    "Fuera de alcance": 50,
    "Servicios": 60,
    "Software": 70,
}


def _sin_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", str(texto))
        if not unicodedata.combining(c)
    ).strip().lower()


def normalizar_linea(valor: str) -> str:
    """Mapea nombres historicos a la nomenclatura vigente L1/L2/L3."""
    t = _sin_tildes(valor).replace("_", " ")
    if "l1-l2" in t or "l1 / l2" in t:
        return "L1-L2"
    if t in {"comun", "común", "digital", "transversal", "l1-l2-l3"}:
        return "COMUN"
    if t.startswith("l2 330") or t.startswith("l2 350"):
        return "L1"  # etiqueta historica: producto retornable, hoy L1
    if t.startswith("l3 pet"):
        return "L2"  # etiqueta historica: QuAtro PET, hoy L2
    if t.startswith("l7"):
        return "L3"  # etiqueta historica: garrafon, hoy L3
    if t.startswith("l1"):
        return "L1"
    if t.startswith("l2"):
        return "L2"
    if t.startswith("l3"):
        return "L3"
    raise ValueError(f"Linea CAPEX no reconocida: {valor!r}")


def _asegurar_parametro(ws, clave: str, valor: float, unidad: str, nota: str) -> None:
    filas = ws.get_all_values()
    for i, fila in enumerate(filas, 1):
        if fila and str(fila[0]).strip().lower() == clave.lower():
            ws.update([[valor, unidad, nota]], f"B{i}:D{i}", value_input_option="USER_ENTERED")
            return
    ws.update([[clave, valor, unidad, nota]], f"A{len(filas) + 1}:D{len(filas) + 1}",
              value_input_option="USER_ENTERED")


def _fx_formula(fila: int) -> str:
    return f'IF($E{fila}="USD";Parametros!$B$5;1)'


def _publicar_licencias(ss) -> tuple[str, str]:
    _asegurar_parametro(
        ss.worksheet("Parametros"), "eur_cop", EUR_COP, "COP/EUR",
        "Referencia 08-jul-2026 para Coreflux; supuesto editable",
    )
    ws = ss.worksheet("Licencias")

    # precio puede ser numero o formula. Coreflux conserva su precio oficial
    # en EUR y convierte con el parametro EUR/COP, sin esconder la divisa.
    items = [
        ["ABB RobotStudio Premium", "Ingenieria offline celdas L1-L2 y L3", "Anual", 2,
         "USD", 1200, "Benchmark proveedor; cantidad editable"],
        ["Studio 5000 Logix Designer", "PLC CompactLogix transversal", "Perpetua", 2,
         "USD", 4500, "Licencia capitalizable; cantidad editable"],
        ["Siemens NX X Manufacturing", "Gemelos digitales de celdas y lineas", "Mensual", 2,
         "USD", 220, "Suscripcion de ingenieria"],
        ["Siemens Plant Simulation X Std", "Simulacion integral de planta (Tecnomatix)",
         "Anual", 1, "USD", 12587.4, "Suscripcion de ingenieria"],
        ["Ignition SCADA — plataforma + aplicacion + historian + alarmas + integracion",
         "SCADA, historico y alarmas L1-L2-L3", "Perpetua", 1, "USD", 25500,
         "Lista oficial: 1.200 + 13.500 + 3.500 + 3.200 + 4.100 USD"],
        ["Coreflux Growth — broker MQTT / UNS", "UNS productivo L1-L2-L3", "Anual", 1,
         "COP", '=2450*INDEX(Parametros!$B:$B;MATCH("eur_cop";Parametros!$A:$A;0))',
         "Precio oficial desde EUR 2.450/año; cloud gestionado es add-on"],
        ["Odoo Custom — API externa XML-RPC", "ERP/MRP/inventario/facturacion", "Mensual", 5,
         "USD", 49, "Plan con API; supuesto editable de 5 usuarios internos"],
        ["Hosting MES/ERP + base de datos, backups y observabilidad",
         "mes.ulogix.online y servicios del ERP", "Mensual", 1, "COP", 1200000,
         "Reserva operativa editable; Odoo Online ya incluye su hosting"],
        ["NI LabVIEW Full", "No requerido por el alcance ULogix", "Excluida", 0,
         "USD", 1731, "Conservado para trazabilidad; no suma"],
        ["Microsoft Azure IoT + storage", "Sustituido por Coreflux + hosting MES/ERP",
         "Excluida", 0, "COP", 6000000, "Conservado para trazabilidad; no suma"],
        ["Node-RED, Python, Streamlit y SQLite", "Middleware, MES/ERP y dashboard",
         "Open source", 1, "COP", 0, "Sin costo de licencia; soporte en APU/hosting"],
    ]

    filas: list[list[object]] = [
        ["LICENCIAS Y PLATAFORMAS DIGITALES — ALCANCE ULOGIX", "", "", "", "", "", "", "", ""],
        ["CAPEX solo incluye licencias perpetuas. Suscripciones y hosting alimentan OPEX mensual; los elementos excluidos quedan en cero para conservar trazabilidad.", "", "", "", "", "", "", "", ""],
        [],
        ["software / plataforma", "alcance", "modalidad", "cant.", "moneda",
         "precio unitario", "CAPEX inicial COP", "OPEX mensual COP", "fuente / supuesto"],
    ]
    for item in items:
        fila = len(filas) + 1
        software, alcance, modalidad, cant, moneda, precio, fuente = item
        fx = _fx_formula(fila)
        capex = f'=IF($C{fila}="Perpetua";$D{fila}*$F{fila}*{fx};0)'
        opex = (f'=IF($C{fila}="Anual";$D{fila}*$F{fila}*{fx}/12;'
                f'IF($C{fila}="Mensual";$D{fila}*$F{fila}*{fx};0))')
        filas.append([software, alcance, modalidad, cant, moneda, precio, capex, opex, fuente])

    filas.extend([
        [],
        ["CAPEX software capitalizable", "Solo licencias perpetuas", "", "", "", "",
         f"=SUM(G5:G{4 + len(items)})", "", ""],
        ["OPEX mensual licencias", "Suscripciones + hosting operativo", "", "", "", "", "",
         f"=SUM(H5:H{4 + len(items)})", ""],
    ])

    ws.clear()
    ws.resize(rows=max(60, len(filas) + 10), cols=max(9, ws.col_count))
    ws.update(filas, "A1", value_input_option="USER_ENTERED")
    ws.freeze(rows=4)
    ws.format("A1:I1", {"backgroundColor": {"red": 0.18, "green": 0.10, "blue": 0.34},
                         "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1},
                                        "bold": True, "fontFamily": "Arial"}})
    ws.format("A4:I4", {"backgroundColor": {"red": 0.12, "green": 0.12, "blue": 0.16},
                         "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1},
                                        "bold": True, "fontFamily": "Arial"}})
    ws.format(f"F5:H{4 + len(items)}", {"numberFormat": {"type": "NUMBER", "pattern": "$#,##0"}})
    ws.format(f"A{6 + len(items)}:I{7 + len(items)}", {
        "backgroundColor": {"red": 0.91, "green": 0.88, "blue": 0.98},
        "textFormat": {"bold": True, "fontFamily": "Arial"},
    })
    for fila in (13, 14):  # filas excluidas dentro del arreglo vigente
        ws.format(f"A{fila}:I{fila}", {"backgroundColor": {"red": 0.93, "green": 0.93, "blue": 0.93},
                                       "textFormat": {"foregroundColor": {"red": 0.45, "green": 0.45, "blue": 0.45}}})

    fila_capex = 6 + len(items)
    fila_opex = 7 + len(items)
    return f"Licencias!G{fila_capex}", f"Licencias!H{fila_opex}"


def _formula_capex(fila: int) -> str:
    return (f'=IF($E{fila}="COP";$D{fila}*$F{fila};'
            f'IF($E{fila}="USD*";$D{fila}*$F{fila}*Parametros!$B$5;'
            f'IF($E{fila}="GBP*";$D{fila}*$F{fila}*INDEX(Parametros!$B:$B;'
            f'MATCH("gbp_cop";Parametros!$A:$A;0));'
            f'$D{fila}*$F{fila}*Parametros!$B$5*Parametros!$B$6)))')


def _reestructurar_capex(ss) -> tuple[int, str]:
    ws = ss.worksheet("CAPEX")
    vals = ws.get("A1:I300", value_render_option="FORMULA")
    idx_header = next(i for i, r in enumerate(vals)
                      if r and str(r[0]).strip().lower() == "seccion")
    encabezado = (vals[idx_header] + [""] * 9)[:9]

    datos: list[tuple[int, list[object]]] = []
    for i, row in enumerate(vals[idx_header + 1:], idx_header + 1):
        r = (list(row) + [""] * 9)[:9]
        if str(r[0]).strip() and str(r[3]).strip() != "":
            linea = normalizar_linea(str(r[1]))
            r[1] = "COMÚN" if linea == "COMUN" else linea
            if str(r[0]).strip() == "Software":
                r[1] = "COMÚN"
                r[2] = "Software capitalizable (detalle vivo en hoja Licencias)"
                r[3], r[4] = 1, "COP"
                r[5] = '=INDEX(Licencias!$G:$G;MATCH("CAPEX software capitalizable";Licencias!$A:$A;0))'
                r[7], r[8] = 3, "software"
            datos.append((i, r))

    if len(datos) != 85:
        raise RuntimeError(f"Se esperaban 85 filas CAPEX vivas y se encontraron {len(datos)}")

    por_linea: dict[str, list[tuple[int, list[object]]]] = {k: [] for k in LINEAS}
    for i, row in datos:
        clave = normalizar_linea(str(row[1]))
        por_linea[clave].append((i, row))
    for filas in por_linea.values():
        filas.sort(key=lambda x: (ORDEN_SECCION.get(str(x[1][0]), 999), x[0]))

    nuevas: list[list[object]] = [
        ["CAPEX ULOGIX — L1 / L2 / L3 + infraestructura transversal", "", "", "", "", "", "", "", ""],
        ["Fuente viva del ERP. Cantidad y costo unitario son entradas editables; CAPEX COP, subtotales y total son fórmulas. Licencias perpetuas vienen de la hoja Licencias.", "", "", "", "", "", "", "", ""],
        [],
        encabezado,
    ]
    titulos: list[tuple[int, str]] = []
    subtotales: list[int] = []
    filas_cero: list[int] = []

    for clave in LINEAS:
        filas = por_linea[clave]
        if not filas:
            continue
        titulos.append((len(nuevas) + 1, clave))
        nuevas.append(["", "", f"▍ {LINEAS[clave]}", "", "", "", "", "", ""])
        inicio = len(nuevas) + 1
        for _, row in filas:
            fila1 = len(nuevas) + 1
            row[6] = _formula_capex(fila1)
            nuevas.append(row)
            try:
                if float(row[3]) == 0:
                    filas_cero.append(fila1)
            except (TypeError, ValueError):
                pass
        fin = len(nuevas)
        fila_sub = len(nuevas) + 1
        subtotales.append(fila_sub)
        nuevas.append(["", "", f"Subtotal — {LINEAS[clave]}", "", "", "",
                       f"=SUM(G{inicio}:G{fin})", "", ""])
        nuevas.append([])

    fila_subtotal_general = len(nuevas) + 3
    fila_contingencia = len(nuevas) + 4
    fila_total = len(nuevas) + 5
    nuevas.extend([
        ["", "", "⚠ GRP001: se conservan separados el gripper GANTRY L1-L2 (4 mordazas) y el del robot L3 (3 ventosas).", "", "", "", "", "", ""],
        [],
        ["", "", "Subtotal CAPEX", "", "", "", "=" + "+".join(f"G{r}" for r in subtotales), "", ""],
        ["", "", "Contingencia", "", "", "", f"=G{fila_subtotal_general}*Parametros!$B$27", "", ""],
        ["", "", "CAPEX TOTAL (con contingencia)", "", "", "", f"=G{fila_subtotal_general}+G{fila_contingencia}", "", ""],
    ])

    ws.clear()
    ws.resize(rows=max(140, len(nuevas) + 10), cols=max(9, ws.col_count))
    ws.update(nuevas, "A1", value_input_option="USER_ENTERED")
    ws.freeze(rows=4)
    ws.format("A1:I1", {"backgroundColor": {"red": 0.18, "green": 0.10, "blue": 0.34},
                         "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1},
                                        "bold": True, "fontFamily": "Arial"}})
    ws.format("A4:I4", {"backgroundColor": {"red": 0.12, "green": 0.12, "blue": 0.16},
                         "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1},
                                        "bold": True, "fontFamily": "Arial"}})
    for fila, clave in titulos:
        ws.format(f"A{fila}:I{fila}", {
            "backgroundColor": COLOR_LINEA[clave],
            "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1},
                           "bold": True, "fontFamily": "Arial"},
        })
    for fila in subtotales:
        ws.format(f"A{fila}:I{fila}", {"backgroundColor": {"red": 0.90, "green": 0.90, "blue": 0.94},
                                       "textFormat": {"bold": True, "fontFamily": "Arial"}})
    for fila in filas_cero:
        ws.format(f"A{fila}:I{fila}", {"backgroundColor": {"red": 0.95, "green": 0.95, "blue": 0.95},
                                       "textFormat": {"foregroundColor": {"red": 0.48, "green": 0.48, "blue": 0.48}}})
    ws.format(f"F5:G{len(nuevas)}", {"numberFormat": {"type": "NUMBER", "pattern": "$#,##0"}})

    total_cell = f"G{fila_total}"
    return len(datos), total_cell


def main() -> None:
    cont = Contabilidad()
    if cont.modo != "sheets":
        raise SystemExit("Google Sheets no esta configurado; no se modifico el libro.")
    ss = cont._spreadsheet()

    capex_ref, opex_ref = _publicar_licencias(ss)
    n_datos, total_cell = _reestructurar_capex(ss)

    # Relectura por el mismo contrato que usa el ERP: detecta encabezados,
    # formulas rotas y filas perdidas antes de terminar.
    filas = cont.leer_capex()
    lic = cont.leer_licencias()
    if len(filas) != n_datos:
        raise RuntimeError(f"leer_capex() devolvio {len(filas)} filas; se esperaban {n_datos}")
    print(f"CAPEX normalizado: {n_datos} filas, 5 bloques (L1/L2/L1-L2/L3/transversal).")
    print(f"Licencias vinculadas: CAPEX={lic.get('CAPEX_SOFTWARE')} · OPEX/mes={lic.get('OPEX_LICENCIAS_MES')}")
    print(f"Referencias vivas: {capex_ref} · {opex_ref} · CAPEX!{total_cell}")


if __name__ == "__main__":
    main()
