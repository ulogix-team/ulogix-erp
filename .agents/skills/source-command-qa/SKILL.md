---
name: "source-command-qa"
description: "Corre la verificación completa (13 pasos) y reporta el estado del proyecto"
---

# source-command-qa

Use this skill when the user asks to run the migrated source command `qa`.

## Command Template

Corre la verificación de 13 pasos del proyecto:

```bash
python tools/verificacion.py
```

Interpreta el resultado:
- **Todo verde** → reporta los indicadores clave que imprime (MAPE, fill rate,
  OEE, VPN/TIR/ROI) y confirma que el estado está sano.
- **Algo en rojo** → identifica el paso que falló, lee el módulo correspondiente,
  diagnostica la causa y **propón** el arreglo antes de tocar nada.

Referencia de pasos: 1 datos · 2 pronóstico · 3 escenarios · 4 inventario ·
5 MRP · 6 sensibilidad · 7 Odoo dry-run · 8 middleware MQTT · 9 contabilidad ·
10 UNS · 11 base ERP · 12 tiempos/OEE · 13 caso de negocio.

Si el paso 9 falla con un error de openpyxl sobre hojas, borra
`data/contabilidad_local.xlsx` y vuelve a correr (es un artefacto de prueba).
