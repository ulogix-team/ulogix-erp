"""
Genera los datasets base del repositorio de forma determinista.

IMPORTANTE (trazabilidad): el repositorio original (scripts 00-14) usa
`kof_volumenes_trimestrales.csv` extraido de 17 reportes trimestrales oficiales
de KOF. Este script reproduce el ESQUEMA y los ordenes de magnitud de esa serie
(21 trimestres, 2021Q1-2026Q1) para que la suite sea funcional de inmediato.
Si tienes el CSV original, simplemente reemplaza el archivo en data/ y todo el
pipeline (pronostico, escenarios, inventario, MRP) se recalcula sobre los
datos reales sin tocar codigo.

Eventos reales incorporados a la serie sintetica:
- Racionamiento de agua en Bogota (CAR/EAAB, abr-2024 a abr-2025): repunte de
  garrafon durante el periodo.
- Impuesto saludable a bebidas azucaradas (Ley 2277/2022, vigente nov-2023):
  caida transitoria de carbonatadas 2024, base deprimida 2025.
"""
import csv, json, math, random
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
DATA.mkdir(exist_ok=True)
rng = random.Random(42)

# ---------------------------------------------------------------- KOF trimestral
Q_SEASON = {1: 0.965, 2: 1.005, 3: 0.985, 4: 1.095}  # estacionalidad trimestral CO
rows = []
carb0, agua0, garr0 = 54.0, 7.2, 3.1  # MCU por trimestre, nivel 2021
for year in range(2021, 2027):
    for q in range(1, 5):
        if (year, q) > (2026, 1):
            break
        t = (year - 2021) + (q - 1) / 4
        # tendencias anuales: carbonatadas +3.2% (con choque impuesto 2024),
        # agua +5.0%, garrafon +3.8%
        carb = carb0 * (1.032 ** t) * Q_SEASON[q]
        if year == 2024:                       # impuesto saludable pleno
            carb *= 0.955
        elif year == 2025:                     # base deprimida, recuperacion parcial
            carb *= 0.975
        agua = agua0 * (1.050 ** t) * Q_SEASON[q]
        garr = garr0 * (1.038 ** t) * Q_SEASON[q]
        if (year == 2024 and q >= 2) or (year == 2025 and q == 1):
            garr *= 1.10                       # racionamiento Bogota
        noise = lambda: 1 + rng.uniform(-0.012, 0.012)
        rows.append({
            "trimestre": f"{year}Q{q}",
            "carbonatadas_mcu": round(carb * noise(), 2),
            "agua_mcu": round(agua * noise(), 2),
            "garrafon_mcu": round(garr * noise(), 2),
        })
for r in rows:
    r["total_mcu"] = round(r["carbonatadas_mcu"] + r["agua_mcu"] + r["garrafon_mcu"], 2)

with open(DATA / "kof_volumenes_trimestrales.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)
print(f"kof_volumenes_trimestrales.csv -> {len(rows)} trimestres")

# ---------------------------------------------------------------- estacionalidad mensual
# Indices mensuales dentro del trimestre / anio (mercado bebidas Colombia):
# dic alto (fiestas), ene moderado, jun-jul repunte vacaciones, abr-may medios.
MESES = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
IDX   = [0.97, 0.94, 1.00, 0.99, 1.00, 1.03, 1.04, 1.00, 0.97, 0.99, 1.02, 1.15]
s = sum(IDX) / 12
IDX = [round(i / s, 4) for i in IDX]
with open(DATA / "estacionalidad_mensual.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["mes", "indice"])
    for m, i in zip(MESES, IDX):
        w.writerow([m, i])
print("estacionalidad_mensual.csv OK (suma/12 =", round(sum(IDX)/12, 4), ")")

# ---------------------------------------------------------------- maestro de productos
def ean13(base12: str) -> str:
    d = [int(c) for c in base12]
    chk = (10 - (sum(d[0::2]) + 3 * sum(d[1::2])) % 10) % 10
    return base12 + str(chk)

productos = [
    dict(sku="P1-CC350-RGB", nombre="Coca-Cola 350 ml vidrio retornable",
         linea="L1", ean13=ean13("770123400010"), litros_por_unidad=0.350,
         unidades_por_caja=24, cajas_por_pallet=84,
         precio_venta_cop=1450, costo_material_cop=520,
         categoria="carbonatadas", participacion_categoria=0.062),
    dict(sku="P2-QT1500-PET", nombre="QuAtro 1.5 L PET no retornable",
         linea="L2", ean13=ean13("770123400027"), litros_por_unidad=1.500,
         unidades_por_caja=6, cajas_por_pallet=60,
         precio_venta_cop=3200, costo_material_cop=1410,
         categoria="carbonatadas", participacion_categoria=0.021),
    dict(sku="P3-GARR25L", nombre="Garrafon agua 25 L retornable",
         linea="L3", ean13=ean13("770123400034"), litros_por_unidad=25.0,
         unidades_por_caja=1, cajas_por_pallet=48,
         precio_venta_cop=9000, costo_material_cop=1850,
         categoria="garrafon", participacion_categoria=0.185),
]
with open(DATA / "maestro_productos.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(productos[0].keys()))
    w.writeheader(); w.writerows(productos)
print("maestro_productos.csv OK — EAN13:", [p["ean13"] for p in productos])

# ---------------------------------------------------------------- BOM + proveedores
# cantidad_por_unidad en la unidad de compra del componente.
# Retornables: factor de reposicion (merma/rotura del parque de envases).
bom = [
    # P1 — Coca-Cola 350 ml vidrio retornable
    ("P1-CC350-RGB","BOT-V350","Botella vidrio 350 ml (reposicion parque)","un",0.020,"O-I Peldar",980.0,50000,21),
    ("P1-CC350-RGB","TAP-CORONA","Tapa corona 26 mm","un",1.000,"Tapas La Libertad",28.0,500000,14),
    ("P1-CC350-RGB","ETIQ-P1","Etiqueta papel 350 ml","un",1.000,"Alico",14.0,200000,10),
    ("P1-CC350-RGB","CONC-CC","Concentrado Coca-Cola","L",0.00058,"The Coca-Cola Company",185000.0,200,30),
    ("P1-CC350-RGB","AZUCAR","Azucar refinada","kg",0.0378,"Incauca",3400.0,10000,7),
    ("P1-CC350-RGB","CO2","CO2 grado alimenticio","kg",0.0070,"Linde Colombia",2900.0,2000,5),
    # P2 — QuAtro 1.5 L PET NR
    ("P2-QT1500-PET","PREF-PET63","Preforma PET 63 g cuello 28 mm","un",1.000,"Enka de Colombia",710.0,100000,18),
    ("P2-QT1500-PET","TAP-ROSCA","Tapa rosca 28 mm","un",1.000,"Tapas La Libertad",92.0,300000,14),
    ("P2-QT1500-PET","ETIQ-TERMO","Etiqueta termoencogible 1.5 L","un",1.000,"Alico",64.0,150000,10),
    ("P2-QT1500-PET","CONC-QT","Concentrado QuAtro","L",0.00250,"The Coca-Cola Company",162000.0,200,30),
    ("P2-QT1500-PET","AZUCAR","Azucar refinada","kg",0.1620,"Incauca",3400.0,10000,7),
    ("P2-QT1500-PET","CO2","CO2 grado alimenticio","kg",0.0300,"Linde Colombia",2900.0,2000,5),
    # P3 — Garrafon 25 L retornable
    ("P3-GARR25L","GARR-25L","Garrafon PC 25 L (reposicion parque)","un",0.050,"Plastigar",21500.0,500,25),
    ("P3-GARR25L","TAP-GARR","Tapa garrafon 55 mm con sello","un",1.000,"Tapas La Libertad",210.0,50000,14),
    # Comunes de paletizado
    ("P1-CC350-RGB","FILM-STRETCH","Film stretch paletizado","kg",0.00042,"Smurfit Kappa",9800.0,500,7),
    ("P2-QT1500-PET","FILM-STRETCH","Film stretch paletizado","kg",0.00120,"Smurfit Kappa",9800.0,500,7),
    ("P3-GARR25L","FILM-STRETCH","Film stretch paletizado","kg",0.00500,"Smurfit Kappa",9800.0,500,7),
]
with open(DATA / "bom.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["producto","componente","descripcion","uom","cantidad_por_unidad",
                "proveedor","precio_unitario_cop","moq","lead_time_dias"])
    w.writerows(bom)
print(f"bom.csv OK — {len(bom)} lineas")

# ---------------------------------------------------------------- parametros de planta
params = {
    "planta": "Coca-Cola FEMSA / INDEGA — Fontibon, Bogota",
    "lineas": {
        "L1": {"producto": "P1-CC350-RGB", "vel_nominal_uph": 36000, "oee": 0.771,
               "teep": 0.401, "turnos": 2, "horas_turno": 8},
        "L2": {"producto": "P2-QT1500-PET", "vel_nominal_uph": 12000, "oee": 0.765,
               "teep": 0.398, "turnos": 2, "horas_turno": 8},
        "L3": {"producto": "P3-GARR25L", "vel_nominal_uph": 480, "oee": 0.754,
               "teep": 0.083, "turnos": 1, "horas_turno": 8,
               "nota": "Cuello de botella: paletizado manual, 2 operarios para 480 uph"},
    },
    "calendario": {"dias_operativos_ano": 286, "domingos": 52, "festivos_ley_emiliani": 18,
                   "mantenimiento_anual_dias": 10},
    "litros_por_caja_unidad": 5.678,
    "participacion_planta_bogota": 0.28,
    "nota_teep": ("TEEP ~40% en L1/L2 es el techo realista a dos turnos con el "
                  "calendario laboral de Bogota; no es un indicador de bajo desempeno."),
}
with open(DATA / "parametros_planta.json", "w") as f:
    json.dump(params, f, indent=2, ensure_ascii=False)
print("parametros_planta.json OK")
