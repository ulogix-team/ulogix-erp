"""Sincroniza el roster vivo de Sheets con Empleados/Nomina de Odoo.

Idempotente: identifica personas por cedula, actualiza su version laboral y
desactiva en Odoo solo registros gestionados por ULOGIX que ya no esten en
Sheets. No genera recibos: requiere una estructura salarial colombiana
configurada y validada en Odoo.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from integrations.odoo_client import OdooClient  # noqa: E402
from integrations.rrhh_client import leer_empleados  # noqa: E402
from tools.migrar_fuentes_externas import CAMPOS, _asegurar_campo  # noqa: E402


def main() -> None:
    odoo = OdooClient()
    for nombre, etiqueta, tipo in CAMPOS["hr.employee"]:
        _asegurar_campo(odoo, "hr.employee", nombre, etiqueta, tipo)
    roster, origen = leer_empleados(permitir_fallback=False)
    resultado = odoo.sincronizar_empleados(roster.to_dict("records"))
    estado = odoo.estado_nomina()
    print(f"RRHH origen={origen}: {resultado}")
    print(f"Nomina Odoo: {estado}")
    if estado["estructuras"] == 0:
        print("AVISO: maestro laboral sincronizado; no se generan recibos hasta "
              "configurar y validar una estructura salarial colombiana en Odoo.")


if __name__ == "__main__":
    main()
