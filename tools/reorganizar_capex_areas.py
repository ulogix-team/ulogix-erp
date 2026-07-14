"""Compatibilidad: la organizacion vigente de CAPEX es por L1/L2/L3.

El esquema antiguo creaba un bloque por cada combinacion seccion+linea y
fragmentaba la hoja en 17 bloques. Se conserva este nombre de comando para
no romper automatizaciones, pero delega en el normalizador vigente, que
tambien enlaza correctamente las licencias capitalizables.
"""
from normalizar_capex_licencias import main


if __name__ == "__main__":
    main()
