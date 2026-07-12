"""
Cliente de la API externa de Odoo (XML-RPC, stdlib — sin dependencias extra).

Documentacion oficial:
https://www.odoo.com/documentation/17.0/developer/reference/external_api.html

Autenticacion: usuario + API key (Ajustes > Usuario > Seguridad de la cuenta >
Nueva API key). La key va en .env como ODOO_API_KEY; nunca en el codigo.

Modo DRY-RUN: sin credenciales (o con DRY_RUN=true) todas las operaciones se
registran en SQLite (log_acciones) y devuelven identificadores DRY-*, de modo
que el dashboard y el middleware funcionan end-to-end sin una instancia real.

Flujo de una orden de compra:
  crear_orden_compra() -> purchase.order en borrador (draft)
  confirmar_orden()    -> button_confirm (draft -> purchase) y genera picking
  recibir_orden()      -> valida el stock.picking de recepcion (qty_done=100%)
El middleware llama recibir_orden() cuando la produccion reportada por MQTT
cubre la cantidad objetivo vinculada a la PO.
"""
from __future__ import annotations

import ssl
import xmlrpc.client
from dataclasses import dataclass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings
from integrations import state_store


class OdooError(RuntimeError):
    pass


@dataclass
class LineaPedido:
    nombre: str            # descripcion / default_code del producto en Odoo
    default_code: str      # referencia interna (se crea si no existe)
    cantidad: float
    precio_unitario: float
    uom: str = "un"


class OdooClient:
    def __init__(self) -> None:
        self.dry_run = settings.DRY_RUN_FORZADO or not settings.ODOO_ENABLED
        self._uid: int | None = None
        self._modelos = None
        self._contador_dry = 0

    # -------------------------------------------------------------- conexion
    def _conectar(self) -> None:
        if self.dry_run or self._uid is not None:
            return
        ctx = ssl.create_default_context()
        common = xmlrpc.client.ServerProxy(f"{settings.ODOO_URL}/xmlrpc/2/common",
                                           context=ctx, allow_none=True)
        uid = common.authenticate(settings.ODOO_DB, settings.ODOO_USER,
                                  settings.ODOO_API_KEY, {})
        if not uid:
            raise OdooError("Autenticacion fallida: revisa ODOO_DB / ODOO_USER / ODOO_API_KEY")
        self._uid = uid
        self._modelos = xmlrpc.client.ServerProxy(f"{settings.ODOO_URL}/xmlrpc/2/object",
                                                  context=ctx, allow_none=True)

    def _kw(self, modelo: str, metodo: str, args: list, kwargs: dict | None = None):
        self._conectar()
        return self._modelos.execute_kw(settings.ODOO_DB, self._uid,
                                        settings.ODOO_API_KEY, modelo, metodo,
                                        args, kwargs or {})

    def probar_conexion(self) -> dict:
        if self.dry_run:
            return {"ok": True, "modo": "dry-run",
                    "detalle": "Sin credenciales Odoo: acciones registradas en SQLite."}
        try:
            self._conectar()
            ver = xmlrpc.client.ServerProxy(f"{settings.ODOO_URL}/xmlrpc/2/common").version()
            return {"ok": True, "modo": "conectado", "uid": self._uid,
                    "detalle": f"Odoo {ver.get('server_version', '?')} en {settings.ODOO_URL}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "modo": "error", "detalle": str(e)}

    # -------------------------------------------------------------- maestros
    def asegurar_proveedor(self, nombre: str) -> int:
        if self.dry_run:
            return -1
        ids = self._kw("res.partner", "search", [[["name", "=", nombre]]], {"limit": 1})
        if ids:
            return ids[0]
        return self._kw("res.partner", "create",
                        [{"name": nombre, "supplier_rank": 1, "is_company": True}])

    def asegurar_producto(self, default_code: str, nombre: str,
                          precio: float, uom: str = "un") -> int:
        if self.dry_run:
            return -1
        ids = self._kw("product.product", "search",
                       [[["default_code", "=", default_code]]], {"limit": 1})
        if ids:
            return ids[0]
        vals = {"name": nombre, "default_code": default_code,
                "standard_price": precio, "purchase_ok": True,
                # 'product' requiere Inventario; fallback a 'consu' si no aplica
                "type": "product"}
        try:
            return self._kw("product.product", "create", [vals])
        except Exception:  # noqa: BLE001
            vals["type"] = "consu"
            return self._kw("product.product", "create", [vals])

    # -------------------------------------------------------------- ordenes de compra
    def crear_orden_compra(self, proveedor: str, lineas: list[LineaPedido],
                           referencia: str, fecha_planeada: str | None = None,
                           confirmar: bool = False) -> dict:
        """Crea purchase.order (borrador). Devuelve {'id', 'name', 'modo'}."""
        if self.dry_run:
            self._contador_dry += 1
            name = f"DRY-PO{self._contador_dry:05d}-{referencia[:24]}"
            total = sum(l.cantidad * l.precio_unitario for l in lineas)
            state_store.log("odoo", "crear_orden_compra (dry-run)",
                            f"{name} | {proveedor} | {len(lineas)} lineas | ${total:,.0f} COP")
            return {"id": None, "name": name, "modo": "dry-run", "total": total}

        partner_id = self.asegurar_proveedor(proveedor)
        order_line = []
        for l in lineas:
            pid = self.asegurar_producto(l.default_code, l.nombre, l.precio_unitario, l.uom)
            ol = {"product_id": pid, "product_qty": l.cantidad,
                  "price_unit": l.precio_unitario, "name": l.nombre}
            if fecha_planeada:
                ol["date_planned"] = f"{fecha_planeada} 08:00:00"
            order_line.append((0, 0, ol))
        vals = {"partner_id": partner_id, "origin": referencia,
                "order_line": order_line}
        po_id = self._kw("purchase.order", "create", [vals])
        name = self._kw("purchase.order", "read", [[po_id], ["name"]])[0]["name"]
        state_store.log("odoo", "crear_orden_compra", f"{name} (id={po_id}) | {proveedor}")
        if confirmar:
            self.confirmar_orden(po_id)
        return {"id": po_id, "name": name, "modo": "creada",
                "total": sum(l.cantidad * l.precio_unitario for l in lineas)}

    def confirmar_orden(self, po_id: int) -> None:
        if self.dry_run:
            state_store.log("odoo", "confirmar_orden (dry-run)", str(po_id))
            return
        self._kw("purchase.order", "button_confirm", [[po_id]])
        state_store.log("odoo", "confirmar_orden", f"id={po_id}")

    def recibir_orden(self, po_id: int | None, po_name: str = "") -> dict:
        """
        Valida la recepcion (stock.picking) asociada a la PO: fija las
        cantidades hechas al 100% y ejecuta button_validate. Maneja el wizard
        de transferencia inmediata si la version de Odoo lo lanza.
        """
        if self.dry_run or po_id is None:
            state_store.log("odoo", "recibir_orden (dry-run)", po_name or str(po_id))
            return {"ok": True, "modo": "dry-run"}
        try:
            pick_ids = self._kw("stock.picking", "search",
                                [[["purchase_id", "=", po_id],
                                  ["state", "not in", ["done", "cancel"]]]])
            for pk in pick_ids:
                move_ids = self._kw("stock.move", "search", [[["picking_id", "=", pk]]])
                moves = self._kw("stock.move", "read",
                                 [move_ids, ["product_uom_qty", "quantity_done"]])
                for mv in moves:
                    try:  # Odoo <= 16
                        self._kw("stock.move", "write",
                                 [[mv["id"]], {"quantity_done": mv["product_uom_qty"]}])
                    except Exception:  # Odoo 17+: campo 'quantity'
                        self._kw("stock.move", "write",
                                 [[mv["id"]], {"quantity": mv["product_uom_qty"],
                                               "picked": True}])
                res = self._kw("stock.picking", "button_validate", [[pk]])
                if isinstance(res, dict) and res.get("res_model") == "stock.immediate.transfer":
                    wiz = res.get("res_id")
                    self._kw("stock.immediate.transfer", "process", [[wiz]])
            state_store.log("odoo", "recibir_orden", f"id={po_id} pickings={pick_ids}")
            return {"ok": True, "modo": "recibida", "pickings": pick_ids}
        except Exception as e:  # noqa: BLE001
            state_store.log("odoo", "recibir_orden ERROR", f"id={po_id}: {e}")
            return {"ok": False, "modo": "error", "detalle": str(e)}

    def listar_ordenes(self, limit: int = 40) -> list[dict]:
        if self.dry_run:
            return [{"name": p["po_name"], "state": p["estado"],
                     "origin": p.get("detalle", ""), "amount_total": 0}
                    for p in state_store.listar_pos(limit)]
        ids = self._kw("purchase.order", "search", [[]],
                       {"limit": limit, "order": "id desc"})
        return self._kw("purchase.order", "read",
                        [ids, ["name", "partner_id", "state", "amount_total",
                               "origin", "date_order"]])
