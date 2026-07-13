---
description: Regenera el libro financiero Excel, lo recalcula y valida los indicadores
---

Regenera el libro `Modelo_FEMSA_Ulogix_2026.xlsx` del repo hermano y valídalo:

1. **Generar**:
   ```bash
   cd ../femsa-modelo-financiero && python tools/generar_modelo.py
   ```
   Debe reportar 23 hojas.

2. **Recalcular con LibreOffice** (openpyxl NO calcula fórmulas — el libro sale
   con las celdas vacías si te saltas este paso). Usa el script de recálculo si
   existe en el entorno, o `soffice --headless`. **Exige 0 errores de fórmula.**

3. **Validar contra el motor Python** — los indicadores del libro
   (`Flujo_Caja!B19:B29`) deben coincidir con:
   ```bash
   cd ../ulogix-fontibon-suite && python core/finanzas_negocio.py
   ```
   Referencia (2026-07, CAPEX recortado — decisión #15 de CLAUDE.md): CAPEX
   ~$12.188 M · VPN ~$16.661 M · TIR ~85.7 % · ROI ~253.1 % · payback
   21/24 m. Si no coinciden, hay una fórmula mal — **no entregues el
   archivo**, arregla el generador.

4. Verifica también que `Balance!` fila de chequeo dé 0 en los 60 meses.

Errores típicos: `IRR` sin guess (`IRR(rango,0.02)`), `MATCH/INDEX` de paybacks,
referencias desplazadas tras editar filas.
