---
name: uns-mqtt-ulogix
description: Trabajar con el espacio de nombres unificado (UNS) FEMSA, el middleware MQTT, el puente Node-RED/Ignition/OPC-UA y los KPIs de producción del proyecto Ulogix. Úsala SIEMPRE que se mencione MQTT, UNS, tópicos, broker, mosquitto, Node-RED, Ignition, OPC UA, Tecnomatix, KPIs de planta, OEE en vivo, GoodCount, órdenes retained, la tabla kpi_uns o los archivos config/uns_femsa.yaml, integrations/uns.py, integrations/mqtt_middleware.py — incluso si el usuario solo dice "no me llegan los datos de la línea" o "conectar la planta".
---

# UNS FEMSA — contrato y middleware

## Principio no negociable

**El ERP NO gestiona OEE/TEEP.** Esos KPIs existen únicamente porque el
middleware se **cuelga** del UNS por MQTT. Nunca los calcules ni los guardes
desde la app: se ingieren, se muestran y se sincronizan a la hoja `KPIs_UNS`.

Las hojas `Tiempos` y `OEE_TEEP` del libro Excel son **documentales** (referencia
de ingeniería del estudio corregido), no están conectadas a nada.

## El árbol

Definido en `config/uns_femsa.yaml` (79 tópicos-hoja, **no editar sin acordarlo
con la planta**). Lo interpreta `integrations/uns.py`:

```python
from integrations import uns
uns.hojas()                                   # 79 topicos
uns.suscripciones()                           # patrones del middleware
uns.interpretar_topico("FEMSA/Linea2/ERP/OrderStatus")  # {'linea': 'L2', 'hoja': 'OrderStatus', ...}
uns.interpretar_topico("FEMSA/MES/KPI/OEE")   # {'linea': 'PLANTA', 'hoja': 'OEE', ...} (sin linea)
uns.UNS_DE_LINEA                              # {'L1': 'Linea1', ...}
```

**Verificado contra el broker real** (Coreflux Hub, panel en `:8080`,
conectándose directo al broker y suscribiendo a `#`): 79 = 3 líneas ×
(9 KPI + 4 Maintance + 9 ERP) + planta completa (9 KPI + 4 Maintance, sin
ERP propio). Si vuelves a auditar el broker y algo no calza contra esta
cuenta, algo cambió en Coreflux — no asumas que el YAML sigue vigente sin
volver a comprobarlo.

Mapeo: `Linea1 ↔ L1 (350 ml)` · `Linea2 ↔ L2 (1.5 L)` · `Linea3 ↔ L3 (garrafón)`

## Qué escucha y qué publica el middleware

**Suscribe:**
- `FEMSA/+/MES/KPI/#` → `Availability, Quality, Performance, OEE, TEEP, DT, MTTR, MTBF, MLT`
  Payload: número plano (`0.7712`) o JSON `{"value": 0.7712}` → tabla `kpi_uns`
- `FEMSA/+/MES/Maintance/#` → estado de mantenimiento
- `FEMSA/MES/KPI/#` y `FEMSA/MES/Maintance/#` → **agregado de planta completa**,
  sin segmento de línea (existe en el broker real, verificado). Mismas hojas
  que arriba; `interpretar_topico()` las etiqueta `linea='PLANTA'` — quedan en
  la misma tabla `kpi_uns`, sin lógica ni vista aparte
- `FEMSA/+/Process/#` → conteo de producción. La rama está **libre** en el YAML;
  por convención se leen las hojas `GoodCount / Count / Produccion / Production /
  value` como unidades buenas
- `plant/+/production` → contrato legado v1 (compatibilidad)

**Ruido del broker que NO es UNS FEMSA** (visto suscribiendo a `#` en
Coreflux): `celda/status/nodered` (liveness del bridge Node-RED, aún sin
integrar al UNS) y `Agent/*` (telemetría interna de Coreflux Hub con IA) —
ignóralos, no forman parte de este contrato.

**Publica (retained)** la rama ERP de cada línea, para que cualquier suscriptor
nuevo (Ignition, Tecnomatix, Grafana) reciba el último estado al conectarse:

```
FEMSA/Linea1/ERP/OrderNumber        PO-2026-0007
FEMSA/Linea1/ERP/OrderStatus        IN_PROGRESS | COMPLETED | CLOSED
FEMSA/Linea1/ERP/OrderedQuantity    20000
FEMSA/Linea1/ERP/AvailableQuantity  12500   (producido)
FEMSA/Linea1/ERP/ReservedQuantity   7500    (faltante)
FEMSA/Linea1/ERP/ScheduleStart|ScheduleEnd|ActualStart|ActualEnd
```

**Ciclo de cumplimiento (actualizado, ver decisión #7 de `CLAUDE.md`):** cada
`GoodCount` descuenta la PO abierta de esa línea (FIFO) → al completarse, se
**valida la orden de fabricación vinculada** (`mrp.production →
button_mark_done`, no ya la recepción de la PO — esa se recibe de inmediato
al crearse, desde la página *Órdenes Odoo*) → Odoo descuenta la BOM y da
entrada al terminado → se republica la rama ERP con `CLOSED`.

## Reglas de red (causa #1 de "no conecta")

- **Fuera de Docker**: usar la **IP LAN del host** → `100.123.104.31:1883`.
  Nunca `localhost`, nunca el hostname del servicio Docker.
- **Dentro de docker-compose**: los nombres de servicio sí resuelven.
- Herramientas externas (Tecnomatix, RoboDK, UAExpert) → siempre IP LAN.
- **OPC UA**: el sufijo `/discovery` solo soporta FindServers/GetEndpoints, **no**
  CreateSession. La conexión de producción apunta directo al endpoint
  (`opc.tcp://host:62451` — ver `OPCUA_ENDPOINT` en `config/settings.py`,
  sin sufijo `/discovery`).
- **Certificados OPC UA**: la confianza es **bidireccional** — cliente y servidor
  deben confiar mutuamente.

## Probar

```bash
python middleware/run_middleware.py            # terminal 1
python tools/simulador_produccion.py --n 20    # terminal 2 (KPIs + GoodCount al UNS)
python tools/simulador_produccion.py --legacy  # contrato v1
python tools/simulador_produccion.py --offline # sin broker

mosquitto_sub -h 100.123.104.31 -t "FEMSA/+/ERP/#" -v   # ver la rama retenida
```

También hay diagnóstico en vivo en la **página 7 (Pruebas)** del dashboard: hace
un eco round-trip completo (publica y verifica recepción en
`FEMSA/_pruebas/Process/Ping`).

## Al depurar

Prueba **capa por capa**, nunca todo junto: broker → suscripción → parseo del
payload → escritura en `kpi_uns` → visualización. Agrega logging dentro de los
loops. Valida con herramientas externas (MQTT Explorer, UAExpert) antes de tocar
código de producción.
