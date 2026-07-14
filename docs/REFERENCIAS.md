<img src="https://raw.githubusercontent.com/ulogix-team/assets/main/banners/header-dark.svg" width="100%"/>

<img src="https://raw.githubusercontent.com/ulogix-team/assets/main/dividers/divider-dark.svg" width="100%"/>

# Referencias de justificación de la demanda

Fuentes usadas en el proyecto para justificar la serie, la mensualización y
los escenarios (citadas en el informe IEEE del proyecto):

## Serie de volúmenes
1. **Coca-Cola FEMSA (KOF)** — Reportes de resultados trimestrales 2021Q1–2026Q1
   (17 reportes): volúmenes por país/categoría en millones de cajas unidad
   (1 CU = 5.678 L). investor.coca-colafemsa.com
2. **Conversión CU→L**: 24 botellas de 8 oz por caja unidad (estándar KOF).

## Eventos incorporados al modelo y a los escenarios
3. **Ley 2277 de 2022** (impuesto saludable a bebidas azucaradas, vigencia
   nov-2023 con escalas 2024–2025): presión sobre volumen de carbonatadas.
4. **Racionamiento de agua en Bogotá** (EAAB/CAR, abr-2024 a abr-2025, embalse
   Chuza/Chingaza): repunte de demanda de garrafón durante el período; base
   del escenario "Restricción hídrica CAR adicional".
5. **Paro nacional 2021**: caída de volumen del orden de −18% en el mes más
   afectado por bloqueos logísticos (reportes KOF/ANDI); base del escenario
   de choque logístico.
6. **Copa Mundial FIFA 2026** (jun–jul, sede Norteamérica): históricamente
   +6–10% en carbonatadas durante torneos con plan comercial dedicado.
7. **Calendario laboral colombiano** (Ley 51/1983 "Ley Emiliani"): 52 domingos
   + 18 festivos + mantenimiento anual → 286 días operativos (base de TEEP).

## Metodología
8. Holt, C. & Winters, P. — suavizamiento exponencial estacional; variante
   multiplicativa con tendencia amortiguada (Gardner & McKenzie, 1985).
9. Bates, J.M. & Granger, C.W.J. (1969) — *The Combination of Forecasts*:
   combinación 50/50 usada para garrafón (MAPE 4.6% en backtest original).
10. Validación de residuos: Kolmogórov-Smirnov, Anderson-Darling y
    chi-cuadrado (normalidad aceptada) + tracking signal.
11. Silver, Pyke & Peterson — *Inventory and Production Management*: política
    (s, Q), stock de seguridad z·σ·√LT y EOQ redondeado a pallets.

## Datos operativos de planta
12. Visita a planta Fontibón (INDEGA): velocidades nominales, turnos,
    OEE reconstruido bottom-up por línea (77.1 / 76.5 / 75.4%).
13. Benchmarks de OEE en formatos retornables: 75–82% típico por lavado e
    inspección multietapa (no 87.5%+ como asumen benchmarks genéricos).

> Nota: la serie incluida en `data/` reproduce el esquema y órdenes de
> magnitud de la extracción de los reportes (1); reemplázala por la
> extracción original para resultados exactos del informe.

<img src="https://raw.githubusercontent.com/ulogix-team/assets/main/banners/footer-dark.svg" width="100%"/>
