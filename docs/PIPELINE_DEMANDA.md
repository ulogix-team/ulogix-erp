# Integracion del pipeline original de demanda

El paquete fuente de `Downloads/Repo/paquete` documenta la cadena 00-14 que
origino el modelo: extraccion KOF, reconstruccion mensual, pruebas, Holt-Winters,
backtest, inventario, distribuciones, Monte Carlo, escenarios y exportacion
Odoo. El ERP conserva esa metodologia, con tres mejoras operativas de v4:

- P3 usa el peso Bates-Granger optimo; no el promedio 50/50 de la base v3.
- P1/P2 incorporan deriva de mezcla y perfil mensual por formato.
- entradas, snapshots y metricas viven en las hojas `Forecast_*` de Sheets.

La correspondencia es:

| Pipeline base | Implementacion viva |
|---|---|
| 00-01 KOF/reconstruccion | `Forecast_KOF_Trimestral`, historicos y `core/forecast.py` |
| 03-04 HW/backtest | `core/forecast.py: pronostico_base()` y `Forecast_Metricas` |
| 05 inventario/lotes | `core/inventario.py` con BOM/proveedores de Odoo |
| 06 exportacion Odoo | `tools/bootstrap_odoo.py` + `integrations/odoo_client.py` |
| 08-09 distribuciones/MC | `Forecast_Configuracion` + bandas P05/P95 |
| 12 verificacion | `tools/verificar_pipeline_demanda.py` |
| 13-14 escenarios | `core/escenarios.py` + `DemandaEscenario` |

Validacion y publicacion del reporte, siempre dentro de Docker:

```bash
docker compose -f docker-compose.dashboard.yml exec dashboard \
  python tools/verificar_pipeline_demanda.py --publicar-qa
```

La prueba recalcula sin tocar `Demanda` y exige equivalencia con el snapshot
vigente. Solo admite diferencias pequenas de redondeo del optimizador.
