<img src="https://raw.githubusercontent.com/ulogix-team/assets/main/banners/header-dark.svg" width="100%"/>

<img src="https://raw.githubusercontent.com/ulogix-team/assets/main/dividers/divider-dark.svg" width="100%"/>

<p align="center">
  <img src="https://raw.githubusercontent.com/ulogix-team/assets/main/logos/ulogix-icon-transparent-dark.svg" height="52" alt="ULogix"/>
</p>

# Documentación técnica

| Guía | Alcance |
|---|---|
| [Reporte para presentación](REPORTE_PRESENTACION_ULOGIX_FONTIBON.md) | Relato completo del proyecto, guion de diapositivas, preguntas y checklist de demostración |
| [Integración de APIs](INTEGRACION_APIS.md) | Odoo, Google Sheets, UNS MQTT, variables de entorno y pruebas funcionales |
| [Pipeline de demanda](PIPELINE_DEMANDA.md) | Holt-Winters, Bates-Granger, Monte Carlo, escenarios y publicación |
| [Referencias](REFERENCIAS.md) | Fuentes de demanda, ingeniería y supuestos |
| [Modelo financiero](https://github.com/ulogix-team/ulogix-data-finance) | CAPEX, APU, licencias, tiempos, OEE y viabilidad económica |

## Contratos principales

- Google Sheets gobierna CAPEX, licencias, APU, RRHH, parámetros y unit economics.
- Odoo gobierna productos, BOM y documentos transaccionales.
- El UNS MQTT gobierna los KPI de producción y OEE vivos.
- `AvailableQuantity` es la entrada principal para el avance de órdenes de fabricación.
- El ERP publica una única orden activa por línea y conserva idempotencia por referencia.

## Identidad visual

La documentación usa los assets centralizados de [`ulogix-team/assets`](https://github.com/ulogix-team/assets); no se duplican banners o logotipos en este repositorio.

<img src="https://raw.githubusercontent.com/ulogix-team/assets/main/banners/footer-dark.svg" width="100%"/>
