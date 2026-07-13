"""
Bootstrap de Odoo — configura la instancia DESDE CERO
via XML-RPC usando las credenciales del .env:

  1. Instala (si faltan) las apps: Compras (purchase), Inventario (stock),
     Fabricacion (mrp).  [en tu instancia ya estan Inventario y Manufactura]
  2. Crea las categorias y ubica las unidades de medida (un / kg / L).
  3. Crea los 3 productos terminados con EAN-13, precio y costo del maestro.
  4. Crea los componentes de la BOM (data/bom.csv) como comprables, con su
     proveedor (res.partner) y tarifa (product.supplierinfo: precio, MOQ,
     lead time).
  5. Crea las Listas de Materiales (mrp.bom) de P1/P2/P3.

Es IDEMPOTENTE: busca por referencia interna (default_code) / nombre antes de
crear; correrlo dos veces no duplica nada.

Uso:
    python tools/bootstrap_odoo.py            # ejecuta todo
    python tools/bootstrap_odoo.py --dry      # muestra el plan sin escribir

Requiere en .env: ODOO_URL, ODOO_DB, ODOO_USER (tu correo de login) y
ODOO_API_KEY. Con la API key como password (recomendado por Odoo).
"""
from __future__ import annotations

import argparse
import sys
import xmlrpc.client
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings

UOM_CANDIDATOS = {  # nombre en bom.csv -> nombres posibles en Odoo (es/en)
    "un": ["Unidades", "Units", "Unidad", "Unit"],
    "kg": ["kg", "Kg"],
    "L": ["L", "Litros", "Liters", "Litro", "Liter"],
}
APPS = ["purchase", "stock", "mrp"]


class Bootstrap:
    def __init__(self, dry: bool = False) -> None:
        self.dry = dry
        comun = xmlrpc.client.ServerProxy(f"{settings.ODOO_URL}/xmlrpc/2/common")
        self.uid = comun.authenticate(settings.ODOO_DB, settings.ODOO_USER,
                                      settings.ODOO_API_KEY, {})
        if not self.uid:
            raise SystemExit(
                "Autenticacion fallida. Verifica en .env: ODOO_USER debe ser el "
                "CORREO con el que inicias sesion en tu instancia Odoo y "
                "ODOO_API_KEY la clave generada en Ajustes > Seguridad de la cuenta. "
                "Si el nombre de la base no coincide, ajusta ODOO_DB "
                "(en odoo.com suele ser el subdominio).")
        self.mod = xmlrpc.client.ServerProxy(f"{settings.ODOO_URL}/xmlrpc/2/object")
        print(f"[ok] autenticado uid={self.uid} en {settings.ODOO_URL} "
              f"(db={settings.ODOO_DB})")

    def kw(self, modelo, metodo, args, kwargs=None):
        return self.mod.execute_kw(settings.ODOO_DB, self.uid,
                                   settings.ODOO_API_KEY, modelo, metodo,
                                   args, kwargs or {})

    # -------------------------------------------------------------- pasos
    def instalar_apps(self) -> None:
        for app in APPS:
            mods = self.kw("ir.module.module", "search_read",
                           [[["name", "=", app]]], {"fields": ["state"]})
            if not mods:
                print(f"[!] modulo {app} no encontrado (version SaaS)"); continue
            estado = mods[0]["state"]
            if estado == "installed":
                print(f"[=] {app} ya instalado")
            elif self.dry:
                print(f"[dry] instalaria {app} (estado {estado})")
            else:
                print(f"[+] instalando {app}...")
                self.kw("ir.module.module", "button_immediate_install",
                        [[mods[0]["id"]]])

    def uom_id(self, clave: str) -> int:
        for nombre in UOM_CANDIDATOS.get(clave, [clave]):
            ids = self.kw("uom.uom", "search", [[["name", "=", nombre]]],
                          {"limit": 1})
            if ids:
                return ids[0]
        for nombre in UOM_CANDIDATOS.get(clave, [clave]):
            ids = self.kw("uom.uom", "search",
                          [[["name", "ilike", nombre]]], {"limit": 1})
            if ids:
                return ids[0]
        raise SystemExit(f"UoM '{clave}' no existe en la base; crearla en "
                         "Inventario > Configuracion > Unidades de medida")

    def _crear_producto(self, vals: dict) -> int:
        """Crea product.template siendo robusto al cambio de esquema de tipo
        de producto entre versiones (17: detailed_type; 18: type+is_storable)."""
        intentos = [
            {**vals, "is_storable": True, "type": "consu"},   # Odoo 18+
            {**vals, "detailed_type": "product"},             # Odoo 15-17
            {**vals, "type": "product"},                      # legado
            vals,
        ]
        ultimo = None
        for v in intentos:
            try:
                return self.kw("product.template", "create", [v])
            except Exception as e:  # noqa: BLE001
                ultimo = e
        raise ultimo

    def asegurar_partner(self, nombre: str) -> int:
        ids = self.kw("res.partner", "search", [[["name", "=", nombre]]],
                      {"limit": 1})
        if ids:
            return ids[0]
        if self.dry:
            print(f"[dry] crearia proveedor {nombre}"); return 0
        pid = self.kw("res.partner", "create",
                      [{"name": nombre, "supplier_rank": 1,
                        "is_company": True}])
        print(f"[+] proveedor {nombre} (id {pid})")
        return pid

    def asegurar_producto(self, code, nombre, uom, precio=0.0, costo=0.0,
                          barcode=None, comprable=False, vendible=False) -> int:
        ids = self.kw("product.template", "search",
                      [[["default_code", "=", code]]], {"limit": 1})
        if ids:
            print(f"[=] producto {code} ya existe (id {ids[0]})"); return ids[0]
        if self.dry:
            print(f"[dry] crearia producto {code} — {nombre}"); return 0
        uid_uom = self.uom_id(uom)
        vals = {"name": nombre, "default_code": code, "uom_id": uid_uom,
                "uom_po_id": uid_uom, "list_price": precio,
                "standard_price": costo, "sale_ok": vendible,
                "purchase_ok": comprable}
        if barcode:
            vals["barcode"] = str(barcode)
        pid = self._crear_producto(vals)
        print(f"[+] producto {code} — {nombre} (id {pid})")
        return pid

    def variante(self, tmpl_id: int) -> int:
        return self.kw("product.product", "search",
                       [[["product_tmpl_id", "=", tmpl_id]]], {"limit": 1})[0]

    def tarifa_proveedor(self, tmpl_id, partner_id, precio, moq, lead) -> None:
        if self.dry or not tmpl_id or not partner_id:
            return
        existentes = self.kw("product.supplierinfo", "search",
                             [[["product_tmpl_id", "=", tmpl_id],
                               ["partner_id", "=", partner_id]]], {"limit": 1})
        if existentes:
            return
        self.kw("product.supplierinfo", "create",
                [{"product_tmpl_id": tmpl_id, "partner_id": partner_id,
                  "price": float(precio), "min_qty": float(moq),
                  "delay": int(lead)}])

    def asegurar_bom(self, tmpl_id: int, code: str,
                     lineas: list[tuple[int, float]]) -> None:
        if self.dry or not tmpl_id:
            print(f"[dry] crearia BOM de {code} ({len(lineas)} componentes)")
            return
        ids = self.kw("mrp.bom", "search",
                      [[["product_tmpl_id", "=", tmpl_id]]], {"limit": 1})
        if ids:
            print(f"[=] BOM de {code} ya existe"); return
        self.kw("mrp.bom", "create",
                [{"product_tmpl_id": tmpl_id, "product_qty": 1, "type": "normal",
                  "bom_line_ids": [(0, 0, {"product_id": vid, "product_qty": q})
                                   for vid, q in lineas]}])
        print(f"[+] BOM de {code}: {len(lineas)} componentes")

    # -------------------------------------------------------------- corrida
    def correr(self) -> None:
        self.instalar_apps()
        maestro = pd.read_csv(settings.DATA_DIR / "maestro_productos.csv")
        bom = pd.read_csv(settings.DATA_DIR / "bom.csv")

        tmpl: dict[str, int] = {}
        for _, r in maestro.iterrows():
            tmpl[r["sku"]] = self.asegurar_producto(
                r["sku"], r["nombre"], "un", precio=float(r["precio_venta_cop"]),
                costo=float(r["costo_material_cop"]), barcode=r["ean13"],
                vendible=True)
        for _, r in bom.drop_duplicates("componente").iterrows():
            cid = self.asegurar_producto(
                r["componente"], r["descripcion"], r["uom"],
                costo=float(r["precio_unitario_cop"]), comprable=True)
            pid = self.asegurar_partner(r["proveedor"])
            self.tarifa_proveedor(cid, pid, r["precio_unitario_cop"],
                                  r["moq"], r["lead_time_dias"])
        comp_tmpl = {r["componente"]: self.kw(
            "product.template", "search",
            [[["default_code", "=", r["componente"]]]], {"limit": 1})
            for _, r in bom.drop_duplicates("componente").iterrows()} \
            if not self.dry else {}
        for sku, g in bom.groupby("producto"):
            if self.dry:
                self.asegurar_bom(0, sku, []); continue
            lineas = [(self.variante(comp_tmpl[r["componente"]][0]),
                       float(r["cantidad_por_unidad"]))
                      for _, r in g.iterrows() if comp_tmpl.get(r["componente"])]
            self.asegurar_bom(tmpl.get(sku, 0), sku, lineas)
        print("\nBootstrap completado. Verifica en Odoo: Inventario > Productos, "
              "Fabricacion > Listas de materiales, Compras > Proveedores.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    if not settings.ODOO_ENABLED:
        raise SystemExit("Faltan credenciales Odoo en .env (ODOO_USER = tu "
                         "correo de login; ODOO_API_KEY ya esta configurada).")
    Bootstrap(dry=args.dry).correr()
