---
description: Ponte al día con el estado del proyecto antes de empezar a trabajar
---

Ponte al día con el proyecto antes de tocar código:

1. Lee `CLAUDE.md` (arquitectura, decisiones que no se rompen, estado actual).
2. Lee `docs/INTEGRACION_APIS.md` (contratos de Sheets, Odoo y UNS).
3. Revisa `git log --oneline -15` y `git status` para ver qué cambió último.
4. Corre `python tools/verificacion.py` para confirmar que el estado está sano.

Después, **resume en 5-8 líneas**: qué hay, qué está validado, qué quedó
pendiente. Y pregunta en qué quiere trabajar el usuario — no empieces a cambiar
cosas por tu cuenta.

Pendientes conocidos: flujo Node-RED (Ignition → UNS), write-path a Odoo,
horas programadas reales para cerrar la tensión TEEP/utilización, y resolver
GRP001 con el taller.
