<img src="https://raw.githubusercontent.com/ulogix-team/assets/main/banners/header-dark.svg" width="100%"/>

<img src="https://raw.githubusercontent.com/ulogix-team/assets/main/dividers/divider-dark.svg" width="100%"/>

<p align="center">
  <img src="https://raw.githubusercontent.com/ulogix-team/assets/main/logos/ulogix-icon-transparent-dark.svg" height="58" alt="ULogix"/>
</p>

# Reporte técnico-ejecutivo para presentación

## Automatización, planeación y viabilidad de la planta FEMSA Fontibón

**Fecha de corte:** 14 de julio de 2026  
**Proyecto:** ULogix Fontibón Suite  
**Planta de referencia:** Coca-Cola FEMSA / INDEGA Fontibón, Bogotá  
**Líneas:** L1 Coca-Cola 350 ml vidrio retornable · L2 QuAtro 1.5 L PET · L3 garrafón 25 L retornable  
**Repositorios:** `ulogix-fontibon-suite` y `ulogix-data-finance`

> Este documento explica qué se construyó, por qué se construyó, cómo funciona y cómo defenderlo en una presentación. Las cifras financieras corresponden al snapshot vivo de Google Sheets publicado el 14 de julio de 2026.

<img src="https://raw.githubusercontent.com/ulogix-team/assets/main/dividers/divider-section-dark.svg" width="100%"/>

## 1. Resumen ejecutivo

ULogix propone una modernización **brownfield**: no se reemplaza toda la planta, sino que se conservan los activos que todavía cumplen su función y se invierte en los cuellos de botella que limitan capacidad, trazabilidad y estabilidad.

La propuesta combina cuatro frentes:

1. **Ingeniería de producción:** comparación antes/después de tiempos, OEE, capacidad, equipos y turnos.
2. **Automatización física:** llenadoras usadas en L1/L2, encajonado, termoencogido y paletizado robotizado.
3. **Integración digital:** SCADA Ignition, MES, MQTT/Coreflux, UNS, simulación, gemelos digitales y ERP/Odoo.
4. **Viabilidad económica:** CAPEX, licencias, APU, nómina, flujo de caja, VPN, TIR, ROI y payback conectados a la demanda.

### Resultado central

| Indicador | Resultado vigente |
|---|---:|
| CAPEX total con contingencia | **COP 9.165.554.245** |
| CAPEX de software | COP 112.086.015 |
| OPEX mensual de licencias y hosting | COP 8.262.150 |
| EBITDA incremental de 12 meses operativos | **COP 9.406.419.488** |
| VPN a 60 meses | **COP 11.032.069.063** |
| TIR anual efectiva | **78,2 %** |
| ROI a 60 meses | **226,7 %** |
| Payback simple | **22 meses** |
| Payback descontado | **25 meses** |
| TMAR | 18,0 % E.A. |

### Tesis que debe quedar en la presentación

> La propuesta no automatiza por automatizar. Parte de demanda real, demuestra que L1 y L2 son infactibles en el estado anterior, identifica el paletizado como restricción crítica, selecciona equipos usados y celdas compartidas para reducir CAPEX, y conecta la producción real con Odoo y el modelo financiero mediante el UNS.

## 2. Problema que se resolvió

El estado inicial tenía cinco dificultades principales:

- L1 y L2 no cubrían la demanda anual con la configuración anterior de equipos, OEE y dos turnos.
- El paletizado manual limitaba cadencia, ergonomía y estabilidad; en L3 era el cuello de botella aunque la llenadora aún tenía capacidad.
- Demanda, inventario, fabricación, OEE y finanzas estaban fragmentados en archivos o sistemas sin un flujo común.
- Las órdenes de fabricación no avanzaban automáticamente con la producción real.
- El CAPEX inicial mezclaba referencias nuevas, supuestos, licencias y equipos sobredimensionados, generando un caso financiero costoso y poco trazable.

La solución se diseñó con una regla: **cada inversión debe responder a una restricción demostrada de capacidad, operación, seguridad o información**.

## 3. Estado antes y después por línea

### 3.1 L1 — Coca-Cola 350 ml vidrio retornable

**Antes**

- Llenado de referencia: KRONES Mecafill usada, 42.500 unidades/hora.
- OEE base: 77,12 %.
- Dos turnos.
- Paletizado manual.
- Capacidad efectiva aproximada: 149,97 millones de unidades/año.
- Demanda vigente: 188,34 millones de unidades/año.
- Utilización: aproximadamente 126 %.
- Dictamen: **infactible**; la demanda supera la capacidad disponible.

**Después**

- Llenadora KRONES usada de aproximadamente 44.000 unidades/hora.
- Encajonadora custom para las cajas 30×30 existentes.
- Transportadores, variadores y conexión a la celda compartida.
- GANTRY ABB compartido con L2.
- OEE fase 1: 80,97 %.
- Tres turnos.
- Capacidad efectiva aproximada: 244,55 millones de unidades/año.
- Utilización: aproximadamente 77 %.
- Dictamen: **factible**, con holgura operativa.

### 3.2 L2 — QuAtro 1.5 L PET

**Antes**

- Línea KRONES de aproximadamente 12.000 unidades/hora.
- OEE base: 76,50 %.
- Dos turnos.
- Conformación y paletizado manuales.
- Capacidad efectiva aproximada: 42,01 millones de unidades/año.
- Demanda vigente: 54,23 millones de unidades/año.
- Utilización: aproximadamente 129 %.
- Dictamen: **infactible**.

**Después**

- Llenadora KRONES usada de aproximadamente 18.000 unidades/hora.
- KRONES Variopac usada para termoencogido y preparación del paquete.
- GANTRY ABB compartido con L1; la celda alterna el paletizado entre líneas.
- OEE fase 1: 80,32 %.
- Tres turnos.
- Capacidad efectiva aproximada: 99,24 millones de unidades/año.
- Utilización: aproximadamente 55 %.
- Dictamen: **factible**, con margen para variaciones de demanda y paros.

### 3.3 L3 — Garrafón 25 L retornable

**Antes**

- Monoblock con capacidad suficiente, limitado por paletizado manual a cerca de 480 garrafones/hora.
- OEE base: 75,37 %.
- Un turno.
- Capacidad efectiva aproximada: 347.309 garrafones/año.
- Demanda vigente: 279.149 garrafones/año.
- Utilización: aproximadamente 80 %.
- Dictamen: factible, pero con restricción ergonómica y poca holgura.

**Después**

- Se conserva la llenadora/tapadora existente de aproximadamente 600 garrafones/hora.
- Robot ABB para paletizado, cotizado por EUROBOTS.
- OEE fase 1: 79,14 %.
- Se conserva un turno.
- Capacidad efectiva aproximada: 455.843 garrafones/año.
- Utilización: aproximadamente 61 %.
- Dictamen: **factible con mayor holgura**.

### 3.4 Comparación consolidada

| Línea | Demanda anual | Capacidad antes | Capacidad después | OEE antes | OEE después | Dictamen antes | Dictamen después |
|---|---:|---:|---:|---:|---:|---|---|
| L1 | 188,34 M u | 149,97 M u | 244,55 M u | 77,12 % | 80,97 % | Infactible | Factible |
| L2 | 54,23 M u | 42,01 M u | 99,24 M u | 76,50 % | 80,32 % | Infactible | Factible |
| L3 | 279.149 u | 347.309 u | 455.843 u | 75,37 % | 79,14 % | Factible | Factible con holgura |

### 3.5 Cómo se aplicó la mejora de OEE

La fase financiada no usa un OEE plano ni afirma que todas las líneas llegan inmediatamente a 86 %. Se aplica una mejora de **+5 % relativo exacto** sobre el OEE base de cada línea:

```text
OEE después = OEE antes × 1,05
```

El aumento se distribuye conceptualmente entre:

- 50 % disponibilidad: reducción de microparos y MTTR mediante automatización, alarmas y seguimiento.
- 30 % rendimiento: mejora de cadencia, eliminación de manipulación manual y cambio de llenadoras en L1/L2.
- 20 % calidad: mejor control y aprovechamiento de los sistemas de inspección existentes.

La meta ≥86 % permanece como objetivo aspiracional de mejora continua, no como supuesto inmediato del caso financiero.

## 4. Alcance físico de la automatización

### Equipos principales

| Área | Alcance |
|---|---|
| L1 | Llenadora KRONES usada, encajonadora custom 30×30, transportadores y conexión al GANTRY |
| L2 | Llenadora KRONES usada, Variopac usada, transportadores y conexión al GANTRY |
| L1-L2 | GANTRY ABB compartido, controlador, servos, grippers, seguridad y alternancia entre líneas |
| L3 | Robot ABB para paletizado; se conserva la llenadora existente |
| Común | Tableros, sensores, neumática, seguridad, integración, instalación, FAT/SAT y capacitación |

### Decisiones de ahorro

- Se prioriza maquinaria usada cuando existe capacidad, soporte e inspección suficientes.
- L1 y L2 comparten un GANTRY en lugar de comprar dos celdas completas.
- L3 conserva su llenadora porque ya cubre la demanda.
- Se excluyeron lavadoras nuevas y equipos adicionales de inspección; las alternativas permanecen en CAPEX con cantidad cero para trazabilidad.
- Las celdas robóticas se desglosaron en una BOM real, no en una única cifra resumen.

### Cotizaciones y benchmarks relevantes

| Equipo | Fuente | Valor / condición |
|---|---|---|
| Robot ABB para L3 | EUROBOTS | GBP 13.500, envío y logística incluidos |
| Controlador ABB IRC5 para celda L1-L2 | IGAM | USD 6.500, envío y logística incluidos |
| Variopac 459 usada | Benchmark Machinio | USD 79.900; logística por confirmar |
| KRONES VODM usada 44.000 bph | MachinePoint | Precio por consultar; alternativa técnica L1 |
| KRONES PET 18.000 bph | Exapro / mercado usado | Precio por consultar; alternativa técnica L2 |

Antes de adjudicar se exige RFQ, inspección, seriales, horas de operación, compatibilidad eléctrica, cambio de formato, FAT/SAT, garantía y costo total instalado. El detalle se encuentra en `ulogix-data-finance/docs/PROVEEDORES_CAPEX.md`.

## 5. Arquitectura digital

```text
Tecnomatix / planta física
          │
          ▼
PLC / OPC-UA ──► Ignition SCADA ──► Node-RED ──► Coreflux MQTT / UNS
                                                        │
                           ┌────────────────────────────┴────────────────────┐
                           ▼                                                 ▼
                 Middleware ULogix                                  MES / KPI / alarmas
                           │
          ┌────────────────┼──────────────────┐
          ▼                ▼                  ▼
      SQLite ERP       Odoo XML-RPC       Google Sheets
          │                │                  │
          └────────────────┴──────────────────┘
                           │
                           ▼
                   Dashboard Streamlit
```

### Función de cada componente

| Componente | Responsabilidad |
|---|---|
| Tecnomatix Plant Simulation | Simular la planta antes/después y validar capacidad, colas y utilización |
| Siemens NX | Gemelos digitales de equipos, celdas y layout |
| ABB RobotStudio | Trayectorias, alcance, colisiones y programación robótica |
| Ignition | SCADA, alarmas, estados, variables de proceso y supervisión |
| Coreflux | Broker MQTT y espacio de nombres unificado |
| UNS | Contrato común de datos para líneas, planta, ERP y MES |
| Middleware ULogix | Interpreta tópicos, actualiza órdenes, inventario, Odoo y Sheets |
| Odoo | Productos, BOM, compras, fabricación, ventas y facturación |
| SQLite ERP | Persistencia local, colas, estados, stock y trazabilidad |
| Google Sheets | Fuente viva del modelo financiero y publicación operacional |
| Streamlit | Interfaz de pronóstico, escenarios, inventario, producción, finanzas y pruebas |

Node-RED puede actuar como puente entre OPC-UA/Ignition y el UNS para telemetría de planta. Sin embargo, el cumplimiento de órdenes mediante `AvailableQuantity` se realiza directamente contra el broker Coreflux y no depende de que Node-RED esté en medio.

## 6. Flujo operativo completo

### Paso 1 — Pronóstico de demanda

La base contiene 21 trimestres de KOF Colombia, desde 2021T1 hasta 2026T1. Se transforma el volumen nacional en demanda de planta usando participación geográfica, captación por producto, litros por caja unidad, mezcla de empaque y formato.

- P1 y P2: Holt-Winters multiplicativo con tendencia amortiguada.
- P3: combinación Bates-Granger entre un modelo directo y uno ligado a la categoría agua.
- Monte Carlo: 10.000 réplicas, semilla 42, bandas P5–P95.
- MAPE vigente: 2,9 % para P1, 2,9 % para P2 y 2,1 % para P3.

El objetivo no es “adivinar” una cifra, sino entregar una distribución de demanda utilizable para inventario, capacidad y finanzas.

### Paso 2 — Escenarios

Existen seis escenarios predefinidos y uno personalizado. Las elasticidades son distintas por producto; por ejemplo, un evento comercial no afecta igual al retornable individual, al PET familiar y al garrafón.

Al activar un escenario:

1. Se guarda en la sesión del ERP.
2. Se persiste en SQLite.
3. Se publica en `DemandaEscenario`.
4. El modelo financiero recalcula ingresos, EBITDA, VPN, TIR y ROI.

### Paso 3 — Política de inventario

Se usa revisión continua `(s,Q)`:

```text
s = demanda esperada durante el lead time + stock de seguridad
Q = lote de reposición redondeado a pallets reales
```

La simulación Monte Carlo calcula fill rate, quiebres, stock y capital inmovilizado. Los pallets son físicos: 1.620 unidades en L1, 840 en L2 y 30 garrafones en L3.

### Paso 4 — Explosión MRP

El MRP toma la demanda activa y la explota con:

- BOM por SKU.
- Scrap.
- MOQ.
- Lead time.
- Precio y proveedor.
- Inventario disponible.

El resultado se guarda en el ERP y se publica en `PlanCompras`.

### Paso 5 — Compras y fabricación en Odoo

Por cada lote se crean:

- Una o varias `purchase.order` para insumos.
- Una `mrp.production` del producto terminado, ligada a su BOM.

La PO se confirma y recibe inmediatamente porque esta suite no modela el lead time transaccional del proveedor. Esto permite reservar los componentes de la MO. Las órdenes son idempotentes: si se reintenta una referencia, se reutiliza la orden existente y no se duplica.

### Paso 6 — Publicación de la orden al UNS

El ERP publica una sola orden de fabricación activa por línea:

```text
FEMSA/LineaX/ERP/OrderNumber
FEMSA/LineaX/ERP/OrderedQuantity
FEMSA/LineaX/ERP/ReservedQuantity
FEMSA/LineaX/ERP/OrderStatus
FEMSA/LineaX/ERP/ScheduleStart
FEMSA/LineaX/ERP/ScheduleEnd
```

Los mensajes son retained, por lo que un suscriptor nuevo recibe el último estado al conectarse.

### Paso 7 — Avance mediante `AvailableQuantity`

`AvailableQuantity` es el camino principal de gestión de manufactura:

- Lo escribe el MES o la simulación.
- Representa la cantidad absoluta producida de la orden activa.
- El ERP lo lee; nunca lo publica.
- Debe avanzar de forma monótona.
- Si retrocede, se considera ruido y se ignora.
- Si supera el objetivo, se recorta al objetivo.

Cuando llega a la cantidad ordenada:

1. Se completa la MO en Odoo.
2. Odoo consume la BOM y recibe producto terminado.
3. El ERP marca el lote como cumplido.
4. Se publica la siguiente orden de la cola.

`Process/GoodCount` permanece solo como contrato legado para pruebas.

### Paso 8 — Inventario en vivo

Con cada avance de producción, no solo al final:

- El ERP suma producto terminado.
- Resta componentes según la BOM.
- Registra el movimiento en una bitácora.
- Cada 60 segundos sincroniza parciales a Odoo mediante backorders nativos.

Esto mantiene coherentes el inventario local y el transaccional.

### Paso 9 — Ventas y facturación

Cuando una MO queda recibida:

1. El lote se reparte entre clientes según participación.
2. Se crea `sale.order`.
3. Se confirma y entrega.
4. Se genera y contabiliza la factura de cliente.

Las compras también generan factura de proveedor, por lo que el flujo cubre cuentas por pagar y por cobrar.

### Paso 10 — Retroalimentación financiera

Demanda, escenario, inventarios, compras, producción, CAPEX, licencias y RRHH convergen en Google Sheets y en el dashboard financiero. El caso de negocio se recalcula sin usar flujos pegados manualmente.

## 7. UNS y datos de producción

El UNS tiene 79 tópicos documentados:

```text
3 líneas × (9 KPI + 4 mantenimiento + 9 ERP)
+ planta completa × (9 KPI + 4 mantenimiento)
= 79 tópicos
```

Los KPI incluyen disponibilidad, rendimiento, calidad, OEE, TEEP, downtime, MTTR, MTBF y MLT.

### Regla crítica

> El ERP no calcula ni administra el OEE real. El OEE vivo llega exclusivamente por MQTT/UNS y se almacena en `kpi_uns`. La hoja `Tiempos` es una referencia documental de ingeniería para comparar antes y después.

La rama de planta completa, por ejemplo `FEMSA/MES/KPI/OEE`, se etiqueta como `PLANTA`. También se validan los datos de entrada porque el broker puede recibir ruido o valores arbitrarios.

## 8. Gobierno de Google Sheets

### Sheets gobierna, Python es fallback

| Información | Fuente viva |
|---|---|
| CAPEX | `CAPEX` |
| Licencias | `Licencias` |
| APU de ingeniería | `APU_Ingenieria` |
| Nómina y roster | `RRHH` |
| Parámetros y unit economics | `Parametros` y `Maestro_Productos` |
| Tiempos y OEE de diseño | `Tiempos` |
| Demanda base y escenarios | `Demanda` y `DemandaEscenario` |

Las constantes Python existen como respaldo cuando Sheets no está disponible. No son la fuente operativa.

### Rangos que no se pueden mover

- `Demanda`: `A4:F16`.
- `DemandaEscenario`: `A4:F16`.
- `Inventarios`: `A4:I8`.

Las fórmulas financieras referencian esas posiciones; por eso el ERP escribe por rango fijo.

### Formato numérico

El libro usa formato colombiano:

- Punto para miles: `3.850`.
- Coma para decimales: `18,00%`.

La integración lee los valores subyacentes sin convertirlos prematuramente a texto.

## 9. Modelo financiero

### Lógica demand-driven

```text
Demanda por SKU
    × precio y costo unitario
    → estado de resultados base y proyecto
    → EBITDA incremental
    − depreciación y amortización
    − impuestos
    − inversión en capital de trabajo
    − CAPEX por fases
    → flujo de caja libre
    → VPN, TIR, ROI y payback
```

### Supuestos principales

- Horizonte: 60 meses.
- Preoperación: cuatro meses.
- TMAR: 18 % E.A.
- Impuesto de renta: 35 %.
- Capital de trabajo: porcentaje del ingreso incremental, recuperado al final.
- Demanda: patrón vigente del ERP, sin crecimiento interanual añadido.
- CAPEX: desembolsado por fases.
- Depreciación: por categoría y vida útil.
- Licencias: separación entre software capitalizable y OPEX recurrente.

### APU de ingeniería

Los tres servicios ULogix se justifican de abajo hacia arriba:

```text
precio = costo directo × (1 + AIU)
```

El costo directo incluye mano de obra propia, terceros/OEM, materiales y logística. El AIU de 25–30 % es una referencia de mercado, no una tarifa legal fija. Las tarifas de mano de obra propia se vinculan a RRHH.

### RRHH

La hoja `RRHH` consolida:

- Resumen por rol.
- Roster individual.
- Carga prestacional de referencia.
- Reconciliación.

Valores vigentes:

| Concepto | Valor mensual |
|---|---:|
| Nómina de operación | COP 85.915.382 |
| Nómina de implementación | COP 87.161.760 |

### Cómo interpretar los resultados

- VPN positivo: el proyecto crea valor sobre la TMAR.
- TIR 78,2 % > TMAR 18 %: la rentabilidad estimada supera ampliamente el mínimo exigido.
- ROI 226,7 %: el retorno acumulado es superior a dos veces la inversión medida por el modelo.
- Payback 22/25 meses: la inversión se recupera antes de la mitad del horizonte de 60 meses.

### Dos resultados que pueden aparecer en pruebas

El Dashboard vivo de Sheets reporta VPN COP 11.032 millones, TIR 78,2 %, ROI 226,7 % y payback 22/25 meses. La verificación offline del motor Python puede reportar aproximadamente VPN COP 10.803 millones, TIR 76,7 %, ROI 222,4 % y payback 22 meses porque usa el snapshot fallback de demanda y parámetros.

Para la presentación use **el resultado vivo de Sheets** e indique la fecha de corte. La diferencia no es un error de fórmula; son dos fuentes de entrada controladas.

## 10. Reconstrucción de los repositorios

### `ulogix-data-finance`

Se transformó de una colección con resultados históricos a una publicación técnica reproducible:

- README ejecutivo con indicadores vigentes.
- Arquitectura del modelo.
- Gobierno y jerarquía de fuentes.
- Metodología de viabilidad.
- Registro de proveedores y cotizaciones.
- Trazabilidad y control de versión.
- Documentación de OEE, tiempos, simulación, MES y propuesta de valor.
- Snapshot XLSX del Google Sheet vivo.
- Manifiesto con fecha, tamaño y SHA-256.
- Script de exportación desde Sheets.
- Validación estructural del XLSX.
- Verificación con Excel de fórmulas y errores.
- Modelo `.xlsm` anterior conservado como legado, sin presentarlo como vigente.

### `ulogix-fontibon-suite`

La documentación del ERP se alineó con la identidad de la organización:

- Banner, logo, separadores, badges y footer de `ulogix-team/assets`.
- Indicadores financieros vigentes.
- Nomenclatura correcta L1/L2/L3.
- AvailableQuantity documentado como camino principal.
- POs y MOs ligadas a BOM.
- Índice técnico para integraciones, demanda, referencias y finanzas.
- Declaración de uso de IA sin atribuirle autoría o colaboración en commits.

## 11. Evidencia de validación

### Libro financiero

| Prueba | Resultado |
|---|---:|
| Hojas auditadas | 39 |
| Fórmulas serializadas | 4.123 |
| Celdas con error | **0** |
| Hash SHA-256 | `3b4d924de5a3e1c08dd2cd81e3c3d2609cfcfe8dd932ec56a51f60b9249646c6` |

### ERP

`tools/verificacion.py` cubre 17 bloques:

1. Datos base.
2. Pronóstico.
3. Escenarios.
4. Inventario `(s,Q)`.
5. MRP.
6. Sensibilidad.
7. Odoo compras y fabricación.
8. Ventas y facturación.
9. Middleware MQTT.
10. Contabilidad.
11. UNS de 79 tópicos.
12. Persistencia SQLite.
13. Tiempos y OEE.
14. Caso de negocio.
15. RRHH.
16. Cola de `AvailableQuantity` y protección contra ruido.
17. Inventario vivo y sincronización parcial a Odoo.

Resultado del último control: **17/17 correcto**.

## 12. Riesgos, límites y asuntos abiertos

| Riesgo o límite | Tratamiento |
|---|---|
| Precios de maquinaria usada pueden cambiar | RFQ, inspección y contingencia antes de adjudicar |
| Cotizaciones directas aún requieren PDF y alcance contractual | Solicitar seriales, garantía, FAT/SAT y exclusiones |
| GANTRY compartido puede generar conflicto de programación | Validar alternancia y buffers en Tecnomatix |
| Meta OEE ≥86 % no se logra en fase 1 | Presentarla como roadmap, no como resultado inmediato |
| Ruido o inyección en broker MQTT | Validación monótona, recorte al objetivo y republicación cada 15 s |
| La PO se recibe inmediatamente | Es una simplificación; el lead time se usa en planeación, no en el flujo transaccional |
| Dos grippers con código GRP001 | Mantener separados hasta resolver con el taller |
| Estructura legal de nómina Odoo | Validar localización y reglas antes de generar recibos |
| KPI vivo y OEE documental pueden confundirse | Explicar siempre que MQTT mide y `Tiempos` diseña |
| Diferencia Sheets vs fallback Python | Citar fuente y fecha de corte de cada indicador |

## 13. Guion recomendado de diapositivas

| Diapositiva | Contenido | Mensaje que debe quedar |
|---:|---|---|
| 1 | Título y equipo | Es una propuesta integral de automatización y planeación |
| 2 | Problema inicial | L1/L2 no cubren demanda; paletizado y fragmentación de datos son restricciones |
| 3 | Metodología | Demanda → tiempos/OEE → capacidad → solución → finanzas |
| 4 | L1 antes/después | Llenadora, encajonadora y GANTRY vuelven factible la línea |
| 5 | L2 antes/después | Llenadora, Variopac y GANTRY elevan capacidad con holgura |
| 6 | L3 antes/después | Se conserva la llenadora y se automatiza solo el cuello de botella |
| 7 | Arquitectura digital | SCADA, UNS, MES, ERP y Odoo forman un solo flujo |
| 8 | AvailableQuantity | La producción real completa MOs y mueve inventario |
| 9 | Modelo financiero | Sheets gobierna; el flujo se deriva de demanda y CAPEX |
| 10 | Resultados | CAPEX 9.166 B, VPN 11.032 B, TIR 78,2 %, payback 22/25 m |
| 11 | Validación y riesgos | 39 hojas, 4.123 fórmulas, cero errores y QA 17/17 |
| 12 | Cierre | La solución es factible, trazable, modular y económicamente atractiva |

## 14. Guion oral de 10–12 minutos

### Minuto 0–1 — Apertura

“El proyecto parte de una pregunta: ¿cómo atender la demanda futura de tres líneas existentes sin reemplazar innecesariamente toda la planta? Nuestra respuesta fue una modernización brownfield conectada de extremo a extremo.”

### Minuto 1–3 — Diagnóstico

“Construimos el pronóstico con 21 trimestres de datos KOF y evaluamos capacidad con máquinas, turnos y OEE del estado anterior. L1 y L2 aparecen sobrecargadas, mientras L3 tiene llenadora suficiente pero está limitada por el paletizado manual.”

### Minuto 3–5 — Solución física

“En L1 proponemos llenadora usada, encajonadora custom y GANTRY. En L2, llenadora usada, Variopac y el mismo GANTRY compartido. En L3 conservamos la llenadora y agregamos únicamente el robot ABB. Así evitamos duplicar activos y reducimos el CAPEX.”

### Minuto 5–7 — Solución digital

“Los equipos y la simulación publican datos al UNS por MQTT. El ERP publica una MO activa por línea y el MES responde con AvailableQuantity. Esa cantidad completa la fabricación, descuenta la BOM, actualiza inventario y habilita ventas y facturación en Odoo.”

### Minuto 7–9 — Finanzas

“El modelo no usa flujos calibrados. Parte de la demanda por SKU, precios, costos, CAPEX, nómina y licencias. Con el corte vigente, el CAPEX es 9.166 mil millones, el VPN 11.032 mil millones, la TIR 78,2 % y el payback 22 meses simple y 25 descontado.”

### Minuto 9–10 — Evidencia

“El libro contiene 39 hojas y 4.123 fórmulas sin errores. El ERP pasa 17 bloques de verificación, incluidos MRP, Odoo, MQTT, AvailableQuantity, inventario en vivo y finanzas.”

### Minuto 10–12 — Riesgos y cierre

“Aún deben cerrarse RFQ, inspecciones de maquinaria usada, reglas de alternancia del GANTRY y la referencia duplicada GRP001. Sin embargo, la arquitectura y el caso de negocio ya demuestran factibilidad técnica y económica.”

## 15. Preguntas probables y respuestas breves

### ¿Por qué comprar equipos usados?

Porque se busca capacidad suficiente con menor CAPEX. La selección no depende solo del precio: exige inspección, compatibilidad, FAT/SAT, repuestos, garantía y costo instalado.

### ¿Por qué el GANTRY es compartido?

Porque L1 y L2 no requieren dos sistemas completamente independientes si la alternancia, los buffers y la programación garantizan servicio. Compartirlo reduce inversión y activos ociosos.

### ¿Por qué no se cambia la llenadora de L3?

Porque la llenadora existente cubre la demanda. El cuello de botella real era el paletizado manual; cambiar la llenadora destruiría valor sin resolver la restricción principal.

### ¿El OEE lo calcula el ERP?

No. El OEE vivo proviene del MES por MQTT/UNS. El ERP lo ingiere y visualiza. La hoja `Tiempos` contiene el OEE de ingeniería usado para comparar antes y después.

### ¿Se usa `AvailableQuantity` para las órdenes de manufactura?

Sí. Es el camino principal. El MES publica la cantidad absoluta producida de la MO activa; el ERP valida el avance y completa la orden cuando alcanza el objetivo.

### ¿Qué evita que se creen órdenes duplicadas?

La idempotencia por referencia. Antes de crear una PO, MO o SO, el cliente de Odoo busca una orden no cancelada con la misma referencia y la reutiliza.

### ¿Qué pasa si el broker publica un dato erróneo?

El avance debe ser monótono. Los retrocesos se ignoran y los valores superiores al objetivo se recortan. Además, la orden activa se reafirma cada 15 segundos.

### ¿Por qué Sheets gobierna las finanzas?

Porque el usuario necesita editar CAPEX, licencias, precios, nómina y supuestos sin modificar código. Python queda como fallback resiliente y como motor de verificación.

### ¿Por qué hay un resultado financiero diferente en el QA offline?

Porque el QA offline usa los parámetros fallback. La presentación debe citar el Dashboard vivo, su fecha de corte y el escenario utilizado.

### ¿Cómo se demostró que la solución cubre la demanda?

Se comparó la demanda anual por SKU con la capacidad efectiva después de aplicar velocidad de equipo, calendario, turnos y OEE. L1 y L2 pasan de utilización superior al 100 % a 77 % y 55 %; L3 baja de 80 % a 61 %.

### ¿Cuál es el mayor riesgo pendiente?

La procura: confirmar condición y costo instalado de maquinaria usada. En la integración, el principal punto de ingeniería es validar la alternancia del GANTRY compartido.

## 16. Checklist para la demostración

Antes de presentar:

- Confirmar que Docker está activo y el dashboard responde.
- Abrir las páginas Pronóstico, Escenarios, Inventario, Órdenes, Producción y Finanzas.
- Tener preparado un escenario para mostrar el recálculo.
- Mostrar una MO activa y su `AvailableQuantity`.
- Mostrar el stock en vivo y el vínculo PO–MO.
- Abrir el Dashboard de Sheets con los indicadores vigentes.
- Evitar editar rangos fijos durante la demostración.
- No mostrar `.env`, API keys ni la cuenta de servicio.
- Tener capturas de respaldo si falla la conectividad externa.

## 17. Conceptos que deben dominarse

| Concepto | Definición corta |
|---|---|
| OEE | Disponibilidad × rendimiento × calidad |
| TEEP | OEE ajustado por utilización del tiempo calendario |
| Takt | Ritmo requerido por la demanda; no es tiempo de ciclo |
| Tiempo de ciclo | Tiempo real o ideal para producir una unidad |
| MLT | Tiempo total de fabricación del lote |
| `(s,Q)` | Política que repone Q cuando el inventario llega al punto s |
| MRP | Explosión de demanda de producto terminado hacia componentes |
| BOM | Lista de materiales de fabricación |
| UNS | Espacio de nombres común para datos industriales |
| Retained MQTT | Mensaje cuyo último valor queda disponible para nuevos suscriptores |
| MO | Orden de fabricación (`mrp.production`) |
| PO | Orden de compra (`purchase.order`) |
| VPN | Valor presente de los flujos después de descontar la TMAR |
| TIR | Tasa que hace el VPN igual a cero |
| ROI | Retorno acumulado respecto a la inversión |
| Payback | Tiempo requerido para recuperar la inversión |
| APU | Desglose de costo directo más AIU para justificar un precio |

## 18. Cierre sugerido

> ULogix convierte una propuesta de automatización en un sistema verificable: parte de la demanda, demuestra la restricción de capacidad, selecciona la intervención mínima necesaria, integra la planta con el ERP y traduce el desempeño operativo en resultados financieros. La inversión no se justifica solo por tecnología, sino por capacidad, trazabilidad, seguridad y creación de valor.

## 19. Documentos de respaldo

- [`README.md`](../README.md): visión general del ERP.
- [`INTEGRACION_APIS.md`](INTEGRACION_APIS.md): contratos de Odoo, Sheets y MQTT.
- [`PIPELINE_DEMANDA.md`](PIPELINE_DEMANDA.md): metodología del pronóstico.
- [`REFERENCIAS.md`](REFERENCIAS.md): fuentes técnicas y de demanda.
- [`ulogix-data-finance`](https://github.com/ulogix-team/ulogix-data-finance): modelo, proveedores, viabilidad y snapshot financiero.
- `config/uns_femsa.yaml`: contrato de los 79 tópicos.
- `core/tiempos_oee.py`: estados antes/después y capacidad.
- `core/finanzas_negocio.py`: motor financiero fallback.
- `integrations/mqtt_middleware.py`: cumplimiento por `AvailableQuantity`.
- `integrations/odoo_client.py`: compras, fabricación, ventas y facturación.

<img src="https://raw.githubusercontent.com/ulogix-team/assets/main/banners/footer-dark.svg" width="100%"/>
