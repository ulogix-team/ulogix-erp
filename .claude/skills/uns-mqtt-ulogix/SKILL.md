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

**Conexión directa al broker — este flujo no necesita Node-RED de por medio.**

**Suscribe:**
- `FEMSA/+/MES/KPI/#` → `Availability, Quality, Performance, OEE, TEEP, DT, MTTR, MTBF, MLT`
  Payload: número plano (`0.7712`) o JSON `{"value": 0.7712}` → tabla `kpi_uns`
- `FEMSA/+/MES/Maintance/#` → estado de mantenimiento
- `FEMSA/MES/KPI/#` y `FEMSA/MES/Maintance/#` → **agregado de planta completa**,
  sin segmento de línea (existe en el broker real, verificado). Mismas hojas
  que arriba; `interpretar_topico()` las etiqueta `linea='PLANTA'` — quedan en
  la misma tabla `kpi_uns`, sin lógica ni vista aparte
- **`FEMSA/+/ERP/AvailableQuantity`** → camino **PRINCIPAL** de producción,
  ver más abajo
- `FEMSA/+/Process/#` → contrato **LEGADO** de producción (delta, no valor
  absoluto). La rama está libre en el YAML; por convención se leen las hojas
  `GoodCount / Count / Produccion / Production / value` como unidades buenas.
  Sigue funcionando pero ya no es necesario en producción
- `plant/+/production` → contrato legado v1 (compatibilidad)

**Ruido del broker que NO es UNS FEMSA** (visto suscribiendo a `#` en
Coreflux): `celda/status/nodered` (liveness del bridge Node-RED, aún sin
integrar al UNS) y **`Agent/*`** (telemetría interna de Coreflux Hub con IA
— **verificado que puede inyectar valores arbitrarios en cualquier hoja del
UNS a pedido**, incluida `ERP/AvailableQuantity`; es la razón de ser de la
protección contra ruido descrita abajo) — no forman parte de este contrato,
pero a diferencia de antes **no se pueden ignorar sin más**: cualquier hoja
que el ERP lea como entrada debe validarse, nunca confiar en el valor crudo.

**Publica (retained)** la rama ERP de cada línea — **excepto
`AvailableQuantity`, que es de solo lectura para el ERP** (la escribe el MES;
si el ERP la publicara también se generaría una carrera/eco) — para que
cualquier suscriptor nuevo (Ignition, Tecnomatix, Grafana) reciba el último
estado al conectarse:

```
FEMSA/Linea1/ERP/OrderNumber        WH/MO/00042   (nombre de la MO activa)
FEMSA/Linea1/ERP/OrderStatus        IN_PROGRESS | COMPLETED | CLOSED
FEMSA/Linea1/ERP/OrderedQuantity    20000
FEMSA/Linea1/ERP/ReservedQuantity   7500    (faltante)
FEMSA/Linea1/ERP/ScheduleStart|ScheduleEnd|ActualStart|ActualEnd
FEMSA/Linea1/ERP/AvailableQuantity  12500   (la ESCRIBE el MES, el ERP solo la lee)
```

**Ciclo de cumplimiento (rediseñado — ver decisión #14 de `CLAUDE.md`):** el
ERP publica **una sola orden de fabricación activa por línea/SKU a la vez**
(`state_store.orden_activa()` — la más antigua `'abierta'`). El MES escribe
`AvailableQuantity` como **valor absoluto** de avance; `state_store.
actualizar_disponible()` exige que sea monótono (ignora retrocesos = ruido) y
recorta cualquier exceso al objetivo. Al alcanzarlo: se **valida la orden de
fabricación vinculada** (`mrp.production → button_mark_done`, no ya la
recepción de la PO — esa se recibe de inmediato al crearse, desde la página
*Órdenes Odoo*) → Odoo descuenta la BOM (tapas, etiquetas, concentrado) y da
entrada al terminado → se marca `cumplida → recibida_odoo` en SQLite → **recién
entonces** se publica la SIGUIENTE orden de la cola de ese SKU (nunca dos
activas a la vez en la misma línea). El middleware reafirma la orden activa
cada 15 s (`INTERVALO_REPUBLICAR`) como autocuración contra ruido externo. El
contrato legado `Process/GoodCount` sigue el mismo camino de cierre vía
`acumular_produccion()` (wrapper sobre `actualizar_disponible()`).

**Probar esta lógica:** página *Pruebas → 4 · Producción (orden activa)* —
simula `AvailableQuantity` local (sin MQTT) o publícalo de verdad al broker.
`tools/verificacion.py` paso 16 cubre cola de 2 órdenes + ruido descendente +
recorte al exceder el objetivo.

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
