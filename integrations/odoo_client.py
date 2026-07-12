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

Flujo de venta del producto terminado a un cliente (distribuidor):
  crear_orden_venta()    -> sale.order, action_confirm + entrega (stock.picking
                             de la venta) + factura de cliente
  entregar_orden_venta() -> valida el picking de salida (descuenta el
                             terminado del inventario)
  facturar_orden_venta() -> genera y contabiliza la factura de cliente
                             (account.move out_invoice)
Y del lado de compras, `crear_orden_compra(facturar=True)` genera ademas la
factura de PROVEEDOR (account.move in_invoice) sobre la PO ya recibida: un
ERP real registra la cuenta por pagar, no solo el movimiento de inventario.

Idempotencia: crear_orden_compra/crear_orden_fabricacion/crear_orden_venta
buscan primero una orden existente y no cancelada con la misma referencia
(`origin` en PO/MO, `client_order_ref` en SO) antes de crear otra -- evita
duplicados si el usuario reintenta o hace doble clic en el dashboard (nos
paso de verdad probando contra Odoo real: ~21 POs duplicadas en una sesion).
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

    def _buscar_orden_existente(self, modelo: str, campo_referencia: str,
                                referencia: str) -> int | None:
        """Busca una orden no cancelada con la misma referencia antes de crear
        otra (PO/MO por `origin`, SO por `client_order_ref`). Evita duplicados
        si el usuario reintenta o hace doble clic -- bug real que nos dejo
        ~21 POs duplicadas probando contra Odoo real en una sola sesion."""
        if self.dry_run:
            return None
        ids = self._kw(modelo, "search",
                       [[[campo_referencia, "=", referencia], ["state", "!=", "cancel"]]],
                       {"limit": 1})
        return ids[0] if ids else None

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

    def asegurar_cliente(self, nombre: str) -> int:
        if self.dry_run:
            return -1
        ids = self._kw("res.partner", "search", [[["name", "=", nombre]]], {"limit": 1})
        if ids:
            return ids[0]
        return self._kw("res.partner", "create",
                        [{"name": nombre, "customer_rank": 1, "is_company": True}])

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
                           confirmar: bool = False, recibir: bool = False,
                           facturar: bool = False) -> dict:
        """Crea purchase.order. Devuelve {'id', 'name', 'modo', 'recibida',
        'facturada', 'total'}.

        Idempotente: si ya existe una PO no cancelada con `origin=referencia`
        la reutiliza en vez de duplicarla (ver `_buscar_orden_existente`).

        `recibir=True` confirma la orden (aunque `confirmar=False`) y valida
        de inmediato la recepcion (ver `recibir_orden`): para los insumos de
        produccion (concentrados, etiquetas, tapas, ...) la suite no modela
        el lead time real del proveedor, asi que quedan disponibles en
        inventario en el mismo paso en que se crea la orden. `facturar=True`
        ademas genera y contabiliza la factura de proveedor (cuenta por
        pagar) sobre esa PO ya recibida.
        """
        if self.dry_run:
            self._contador_dry += 1
            name = f"DRY-PO{self._contador_dry:05d}-{referencia[:24]}"
            total = sum(l.cantidad * l.precio_unitario for l in lineas)
            state_store.log("odoo", "crear_orden_compra (dry-run)",
                            f"{name} | {proveedor} | {len(lineas)} lineas | ${total:,.0f} COP")
            return {"id": None, "name": name, "modo": "dry-run", "total": total,
                    "recibida": recibir, "facturada": facturar}

        existente = self._buscar_orden_existente("purchase.order", "origin", referencia)
        if existente is not None:
            info = self._kw("purchase.order", "read", [[existente], ["name", "state"]])[0]
            po_id, name, estado = existente, info["name"], info["state"]
            state_store.log("odoo", "crear_orden_compra: reutilizada",
                            f"{name} (id={po_id}) origin={referencia} state={estado}")
        else:
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
            estado = "draft"
            state_store.log("odoo", "crear_orden_compra", f"{name} (id={po_id}) | {proveedor}")

        if (confirmar or recibir) and estado == "draft":
            self.confirmar_orden(po_id)
            estado = "purchase"
        recibida = False
        if recibir:
            res_recibo = self.recibir_orden(po_id, name)
            recibida = bool(res_recibo.get("ok"))
            if not recibida:
                state_store.log("odoo", "crear_orden_compra: recepcion fallida",
                                f"{name} (id={po_id}): {res_recibo.get('detalle')}")
        facturada = False
        if facturar:
            res_fact = self.facturar_orden_compra(po_id, name)
            facturada = bool(res_fact.get("ok"))
            if not facturada:
                state_store.log("odoo", "crear_orden_compra: facturacion fallida",
                                f"{name} (id={po_id}): {res_fact.get('detalle')}")
        return {"id": po_id, "name": name,
                "modo": "existente" if existente is not None else "creada",
                "recibida": recibida, "facturada": facturada,
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

    def facturar_orden_compra(self, po_id: int | None, po_name: str = "") -> dict:
        """
        Genera y contabiliza la factura de PROVEEDOR (account.move in_invoice)
        de una PO ya recibida: un ERP real registra la cuenta por pagar, no
        solo el movimiento de inventario. Idempotente: si ya existe una
        factura no cancelada con `invoice_origin=po_name` la reutiliza.
        """
        if self.dry_run or po_id is None:
            state_store.log("odoo", "facturar_orden_compra (dry-run)", po_name or str(po_id))
            return {"ok": True, "modo": "dry-run"}
        try:
            factura_ids = self._kw("account.move", "search",
                                   [[["invoice_origin", "=", po_name],
                                     ["move_type", "=", "in_invoice"],
                                     ["state", "!=", "cancel"]]])
            if not factura_ids:
                self._kw("purchase.order", "action_create_invoice", [[po_id]])
                factura_ids = self._kw("account.move", "search",
                                       [[["invoice_origin", "=", po_name],
                                         ["move_type", "=", "in_invoice"]]])
            if not factura_ids:
                return {"ok": False, "modo": "error",
                        "detalle": "Odoo no genero la factura (revisa que la PO "
                                   "tenga lineas recibidas)"}
            borradores = self._kw("account.move", "search",
                                  [[["id", "in", factura_ids], ["state", "=", "draft"]]])
            if borradores:
                self._kw("account.move", "action_post", [borradores])
            state_store.log("odoo", "facturar_orden_compra",
                            f"{po_name}: factura(s) {factura_ids}")
            return {"ok": True, "modo": "facturada", "invoice_ids": factura_ids}
        except Exception as e:  # noqa: BLE001
            state_store.log("odoo", "facturar_orden_compra ERROR", f"{po_name}: {e}")
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

        Idempotente: si ya existe una MO no cancelada con `origin=referencia`
        la reutiliza en vez de duplicarla (ver `_buscar_orden_existente`).
        """
        if self.dry_run:
            self._contador_dry += 1
            name = f"DRY-MO{self._contador_dry:05d}-{referencia[:24]}"
            state_store.log("odoo", "crear_orden_fabricacion (dry-run)",
                            f"{name} | {default_code_producto} x {cantidad:g}")
            return {"id": None, "name": name, "modo": "dry-run"}

        existente = self._buscar_orden_existente("mrp.production", "origin", referencia)
        if existente is not None:
            info = self._kw("mrp.production", "read", [[existente], ["name", "state"]])[0]
            mo_id, name, estado = existente, info["name"], info["state"]
            state_store.log("odoo", "crear_orden_fabricacion: reutilizada",
                            f"{name} (id={mo_id}) origin={referencia} state={estado}")
        else:
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
            estado = "draft"
            state_store.log("odoo", "crear_orden_fabricacion",
                            f"{name} (id={mo_id}) | {default_code_producto} x {cantidad:g}")

        if confirmar and estado == "draft":
            self._kw("mrp.production", "action_confirm", [[mo_id]])
            estado = "confirmed"
            state_store.log("odoo", "confirmar_orden_fabricacion", f"id={mo_id}")
        if reservar:
            try:
                self._kw("mrp.production", "action_assign", [[mo_id]])
            except Exception as e:  # noqa: BLE001
                state_store.log("odoo", "reservar_orden_fabricacion ERROR",
                                f"id={mo_id}: {e}")
        return {"id": mo_id, "name": name,
                "modo": "existente" if existente is not None else "creada"}

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

    # -------------------------------------------------------------- ventas
    def crear_orden_venta(self, cliente: str, lineas: list[LineaPedido],
                          referencia: str, confirmar: bool = True,
                          entregar: bool = True, facturar: bool = True) -> dict:
        """Crea sale.order del producto terminado a un cliente (distribuidor):
        cierra el flujo compra-insumo -> fabricacion -> venta -> factura que
        le faltaba a la suite. `confirmar` pasa la orden a 'sale' (genera la
        entrega en Odoo); `entregar` valida esa entrega (descuenta el
        terminado del inventario); `facturar` genera y contabiliza la
        factura de cliente (cuenta por cobrar). Devuelve {'id', 'name',
        'modo', 'entregada', 'facturada', 'total'}.

        Idempotente: si ya existe una SO no cancelada con
        `client_order_ref=referencia` la reutiliza en vez de duplicarla.
        """
        if self.dry_run:
            self._contador_dry += 1
            name = f"DRY-SO{self._contador_dry:05d}-{referencia[:24]}"
            total = sum(l.cantidad * l.precio_unitario for l in lineas)
            state_store.log("odoo", "crear_orden_venta (dry-run)",
                            f"{name} | {cliente} | {len(lineas)} lineas | ${total:,.0f} COP")
            return {"id": None, "name": name, "modo": "dry-run", "total": total,
                    "entregada": entregar, "facturada": facturar}

        existente = self._buscar_orden_existente("sale.order", "client_order_ref", referencia)
        if existente is not None:
            info = self._kw("sale.order", "read", [[existente], ["name", "state"]])[0]
            so_id, name, estado = existente, info["name"], info["state"]
            state_store.log("odoo", "crear_orden_venta: reutilizada",
                            f"{name} (id={so_id}) ref={referencia} state={estado}")
        else:
            partner_id = self.asegurar_cliente(cliente)
            order_line = []
            for l in lineas:
                pid = self.asegurar_producto(l.default_code, l.nombre, l.precio_unitario, l.uom)
                order_line.append((0, 0, {"product_id": pid, "product_uom_qty": l.cantidad,
                                          "price_unit": l.precio_unitario, "name": l.nombre}))
            vals = {"partner_id": partner_id, "client_order_ref": referencia,
                    "order_line": order_line}
            so_id = self._kw("sale.order", "create", [vals])
            name = self._kw("sale.order", "read", [[so_id], ["name"]])[0]["name"]
            estado = "draft"
            state_store.log("odoo", "crear_orden_venta", f"{name} (id={so_id}) | {cliente}")

        if confirmar and estado == "draft":
            self._kw("sale.order", "action_confirm", [[so_id]])
            estado = "sale"
            state_store.log("odoo", "confirmar_orden_venta", f"id={so_id}")

        entregada = False
        if entregar:
            res_entrega = self.entregar_orden_venta(so_id, name)
            entregada = bool(res_entrega.get("ok"))
            if not entregada:
                state_store.log("odoo", "crear_orden_venta: entrega fallida",
                                f"{name} (id={so_id}): {res_entrega.get('detalle')}")

        facturada = False
        if facturar:
            res_fact = self.facturar_orden_venta(so_id, name)
            facturada = bool(res_fact.get("ok"))
            if not facturada:
                state_store.log("odoo", "crear_orden_venta: facturacion fallida",
                                f"{name} (id={so_id}): {res_fact.get('detalle')}")

        return {"id": so_id, "name": name,
                "modo": "existente" if existente is not None else "creada",
                "entregada": entregada, "facturada": facturada,
                "total": sum(l.cantidad * l.precio_unitario for l in lineas)}

    def entregar_orden_venta(self, so_id: int | None, so_name: str = "") -> dict:
        """
        Valida la entrega (stock.picking) de una orden de venta confirmada:
        misma logica de cantidades que `recibir_orden` (campo `quantity_done`
        en Odoo <=16, `quantity`+`picked` en Odoo 17+).
        """
        if self.dry_run or so_id is None:
            state_store.log("odoo", "entregar_orden_venta (dry-run)", so_name or str(so_id))
            return {"ok": True, "modo": "dry-run"}
        try:
            pick_ids = self._kw("stock.picking", "search",
                                [[["sale_id", "=", so_id],
                                  ["state", "not in", ["done", "cancel"]]]])
            for pk in pick_ids:
                move_ids = self._kw("stock.move", "search", [[["picking_id", "=", pk]]])
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
            state_store.log("odoo", "entregar_orden_venta", f"id={so_id} pickings={pick_ids}")
            return {"ok": True, "modo": "entregada", "pickings": pick_ids}
        except Exception as e:  # noqa: BLE001
            state_store.log("odoo", "entregar_orden_venta ERROR", f"id={so_id}: {e}")
            return {"ok": False, "modo": "error", "detalle": str(e)}

    def facturar_orden_venta(self, so_id: int | None, so_name: str = "") -> dict:
        """
        Genera y contabiliza la factura de CLIENTE (account.move out_invoice)
        de una orden de venta confirmada: el cobro que le faltaba a la suite
        despues de compra-insumo -> fabricacion -> venta. Idempotente: si ya
        existe una factura no cancelada con `invoice_origin=so_name` la
        reutiliza. Prueba `_create_invoices` (Odoo 14+) con fallback a
        `action_invoice_create` (versiones previas).
        """
        if self.dry_run or so_id is None:
            state_store.log("odoo", "facturar_orden_venta (dry-run)", so_name or str(so_id))
            return {"ok": True, "modo": "dry-run"}
        try:
            factura_ids = self._kw("account.move", "search",
                                   [[["invoice_origin", "=", so_name],
                                     ["move_type", "=", "out_invoice"],
                                     ["state", "!=", "cancel"]]])
            if not factura_ids:
                try:
                    self._kw("sale.order", "_create_invoices", [[so_id]])
                except Exception:  # noqa: BLE001
                    self._kw("sale.order", "action_invoice_create", [[so_id]])
                factura_ids = self._kw("account.move", "search",
                                       [[["invoice_origin", "=", so_name],
                                         ["move_type", "=", "out_invoice"]]])
            if not factura_ids:
                return {"ok": False, "modo": "error",
                        "detalle": "Odoo no genero la factura (revisa que la SO "
                                   "tenga lineas entregadas/facturables)"}
            borradores = self._kw("account.move", "search",
                                  [[["id", "in", factura_ids], ["state", "=", "draft"]]])
            if borradores:
                self._kw("account.move", "action_post", [borradores])
            state_store.log("odoo", "facturar_orden_venta",
                            f"{so_name}: factura(s) {factura_ids}")
            return {"ok": True, "modo": "facturada", "invoice_ids": factura_ids}
        except Exception as e:  # noqa: BLE001
            state_store.log("odoo", "facturar_orden_venta ERROR", f"{so_name}: {e}")
            return {"ok": False, "modo": "error", "detalle": str(e)}

    def listar_ordenes_venta(self, limit: int = 40) -> list[dict]:
        if self.dry_run:
            return []
        ids = self._kw("sale.order", "search", [[]],
                       {"limit": limit, "order": "id desc"})
        return self._kw("sale.order", "read",
                        [ids, ["name", "partner_id", "state", "amount_total",
                               "client_order_ref", "date_order"]])

    def listar_facturas(self, tipo: str = "out_invoice", limit: int = 40) -> list[dict]:
        """`tipo`: 'out_invoice' (cliente) o 'in_invoice' (proveedor)."""
        if self.dry_run:
            return []
        ids = self._kw("account.move", "search", [[["move_type", "=", tipo]]],
                       {"limit": limit, "order": "id desc"})
        return self._kw("account.move", "read",
                        [ids, ["name", "partner_id", "state", "amount_total",
                               "invoice_origin", "invoice_date"]])

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
