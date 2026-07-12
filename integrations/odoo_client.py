"""
Cliente de la API externa de Odoo (XML-RPC, stdlib — sin dependencias extra).

Documentacion oficial:
https://www.odoo.com/documentation/17.0/developer/reference/external_api.html

Autenticacion: usuario + API key (Ajustes > Usuario > Seguridad de la cuenta >
Nueva API key). La key va en .env como ODOO_API_KEY; nunca en el codigo.

Modo DRY-RUN: sin credenciales (o con DRY_RUN=true) todas las operaciones se
registran en SQLite (log_acciones) y devuelven identificadores DRY-*, de modo
que el dashboard y el middleware funcionan end-to-end sin una instancia real.

Flujo de una orden de compra de insumos (concentrados, etiquetas, tapas, ...):
  crear_orden_compra(recibir=True) -> purchase.order + button_confirm + recibir_orden()
El recibo se hace INMEDIATO al crear la PO (para fines practicos: la suite no
modela el lead time real del proveedor) para que el insumo quede disponible
en inventario de inmediato.

Flujo de una orden de fabricacion (mrp.production) del producto terminado:
  crear_orden_fabricacion()     -> mrp.production ligada a la BOM del sku,
                                    action_confirm + action_assign (reserva
                                    los insumos ya recibidos)
  completar_orden_fabricacion() -> button_mark_done: descuenta los componentes
                                    de la BOM y da entrada al producto terminado
El middleware llama completar_orden_fabricacion() cuando la produccion real
reportada por MQTT cubre la cantidad objetivo del lote (PO de insumos + MO
quedan vinculadas via integrations.state_store.registrar_po(mo_id=..., ...)).
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
                           confirmar: bool = False, recibir: bool = False) -> dict:
        """Crea purchase.order. Devuelve {'id', 'name', 'modo'}.

        `recibir=True` confirma la orden (aunque `confirmar=False`) y valida
        de inmediato la recepcion (ver `recibir_orden`): para los insumos de
        produccion (concentrados, etiquetas, tapas, ...) la suite no modela
        el lead time real del proveedor, asi que quedan disponibles en
        inventario en el mismo paso en que se crea la orden.
        """
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
        if confirmar or recibir:
            self.confirmar_orden(po_id)
        recibida = False
        if recibir:
            res_recibo = self.recibir_orden(po_id, name)
            recibida = bool(res_recibo.get("ok"))
            if not recibida:
                state_store.log("odoo", "crear_orden_compra: recepcion fallida",
                                f"{name} (id={po_id}): {res_recibo.get('detalle')}")
        return {"id": po_id, "name": name, "modo": "creada", "recibida": recibida,
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
                # 'quantity_done' no existe como campo en Odoo 17+/saas recientes
                # (no solo se renombro: leerlo con 'read' ya lanza ValueError) —
                # solo se lee 'product_uom_qty' y se prueba el nombre de campo al
                # escribir la cantidad hecha.
                moves = self._kw("stock.move", "read", [move_ids, ["product_uom_qty"]])
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

    # -------------------------------------------------------------- ordenes de fabricacion
    def crear_orden_fabricacion(self, default_code_producto: str, cantidad: float,
                                referencia: str, confirmar: bool = True,
                                reservar: bool = True) -> dict:
        """Crea mrp.production (Orden de fabricacion) del producto terminado,
        ligada a su lista de materiales (mrp.bom creada por bootstrap_odoo.py).
        Al confirmar, Odoo genera la demanda de componentes (concentrados,
        etiquetas, tapas, ...) segun la BOM; `reservar=True` intenta asignar
        esa demanda contra el stock ya recibido (ver crear_orden_compra).
        Devuelve {'id', 'name', 'modo'}.
        """
        if self.dry_run:
            self._contador_dry += 1
            name = f"DRY-MO{self._contador_dry:05d}-{referencia[:24]}"
            state_store.log("odoo", "crear_orden_fabricacion (dry-run)",
                            f"{name} | {default_code_producto} x {cantidad:g}")
            return {"id": None, "name": name, "modo": "dry-run"}

        ids = self._kw("product.product", "search",
                       [[["default_code", "=", default_code_producto]]], {"limit": 1})
        if not ids:
            raise OdooError(f"Producto {default_code_producto} no existe en Odoo "
                            "(corre tools/bootstrap_odoo.py)")
        pid = ids[0]
        tmpl_id = self._kw("product.product", "read",
                           [[pid], ["product_tmpl_id"]])[0]["product_tmpl_id"][0]
        bom_ids = self._kw("mrp.bom", "search",
                           [[["product_tmpl_id", "=", tmpl_id]]], {"limit": 1})
        if not bom_ids:
            raise OdooError(f"{default_code_producto} no tiene lista de materiales "
                            "(mrp.bom) en Odoo — corre tools/bootstrap_odoo.py")
        vals = {"product_id": pid, "bom_id": bom_ids[0], "product_qty": cantidad,
                "origin": referencia}
        mo_id = self._kw("mrp.production", "create", [vals])
        name = self._kw("mrp.production", "read", [[mo_id], ["name"]])[0]["name"]
        state_store.log("odoo", "crear_orden_fabricacion",
                        f"{name} (id={mo_id}) | {default_code_producto} x {cantidad:g}")
        if confirmar:
            self._kw("mrp.production", "action_confirm", [[mo_id]])
            state_store.log("odoo", "confirmar_orden_fabricacion", f"id={mo_id}")
        if reservar:
            try:
                self._kw("mrp.production", "action_assign", [[mo_id]])
            except Exception as e:  # noqa: BLE001
                state_store.log("odoo", "reservar_orden_fabricacion ERROR",
                                f"id={mo_id}: {e}")
        return {"id": mo_id, "name": name, "modo": "creada"}

    def completar_orden_fabricacion(self, mo_id: int | None, mo_name: str = "") -> dict:
        """
        Valida la orden de fabricacion (button_mark_done): descuenta del
        inventario los componentes de la BOM (concentrados, etiquetas, tapas,
        ...) y da entrada al producto terminado. El middleware la llama
        cuando la produccion real reportada por MQTT cubre la cantidad
        objetivo del lote.
        """
        if self.dry_run or mo_id is None:
            state_store.log("odoo", "completar_orden_fabricacion (dry-run)",
                            mo_name or str(mo_id))
            return {"ok": True, "modo": "dry-run"}
        try:
            estado = self._kw("mrp.production", "read", [[mo_id], ["state"]])[0]["state"]
            if estado == "draft":
                self._kw("mrp.production", "action_confirm", [[mo_id]])
            if estado not in ("done", "cancel"):
                self._kw("mrp.production", "action_assign", [[mo_id]])
            move_ids = self._kw("stock.move", "search",
                                [[["raw_material_production_id", "=", mo_id]]])
            moves = self._kw("stock.move", "read", [move_ids, ["product_uom_qty"]])
            for mv in moves:
                try:  # Odoo <= 16
                    self._kw("stock.move", "write",
                             [[mv["id"]], {"quantity_done": mv["product_uom_qty"]}])
                except Exception:  # Odoo 17+: campo 'quantity'
                    self._kw("stock.move", "write",
                             [[mv["id"]], {"quantity": mv["product_uom_qty"], "picked": True}])
            try:  # Odoo 17+: cantidad a producir explicita
                qty = self._kw("mrp.production", "read",
                               [[mo_id], ["product_qty"]])[0]["product_qty"]
                self._kw("mrp.production", "write", [[mo_id], {"qty_producing": qty}])
            except Exception:  # noqa: BLE001
                pass
            self._kw("mrp.production", "button_mark_done", [[mo_id]])
            state_store.log("odoo", "completar_orden_fabricacion", f"id={mo_id}")
            return {"ok": True, "modo": "completada"}
        except Exception as e:  # noqa: BLE001
            state_store.log("odoo", "completar_orden_fabricacion ERROR", f"{mo_id}: {e}")
            return {"ok": False, "modo": "error", "detalle": str(e)}

    def listar_ordenes_fabricacion(self, limit: int = 40) -> list[dict]:
        if self.dry_run:
            return []
        ids = self._kw("mrp.production", "search", [[]],
                       {"limit": limit, "order": "id desc"})
        return self._kw("mrp.production", "read",
                        [ids, ["name", "product_id", "product_qty", "state", "origin"]])

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
