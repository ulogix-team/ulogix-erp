"""Compatibilidad para la antigua migracion de BOM de celdas.

Las celdas ya forman parte de las 85 filas del CAPEX vivo. La publicacion
vigente debe conservar la jerarquia L1/L2/L3 y el vinculo con Licencias, por
lo que este comando delega en ``normalizar_capex_licencias``.
"""
from normalizar_capex_licencias import main


if __name__ == "__main__":
    main()
