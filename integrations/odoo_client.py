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
import math
from datetime import date, timedelta
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
        if settings.EXTERNAL_ONLY and self.dry_run:
            raise OdooError("EXTERNAL_ONLY=true: Odoo real es obligatorio; dry-run deshabilitado")
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

    def _campos_disponibles(self, modelo: str) -> set[str]:
        """Campos expuestos por la version real de Odoo.

        Odoo cambia nombres entre versiones SaaS; consultar ``fields_get``
        evita que una lectura completa falle por pedir un campo opcional.
        """
        if self.dry_run:
            return set()
        return set(self._kw(modelo, "fields_get", [], {"attributes": ["type"]}))

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

    # -------------------------------------------------------------- RRHH / nomina
    def _asegurar_por_nombre(self, modelo: str, nombre: str,
                             extra: dict | None = None) -> int:
        ids = self._kw(modelo, "search", [[["name", "=", nombre]]], {"limit": 1})
        if ids:
            return ids[0]
        vals = {"name": nombre, **(extra or {})}
        return self._kw(modelo, "create", [vals])

    def sincronizar_empleados(self, empleados: list[dict]) -> dict:
        """Replica el roster vivo de Sheets en Empleados/Nomina de Odoo.

        Sheets sigue siendo la fuente editable. ``salario_mensual_cop`` es
        costo total empleador; Odoo ``wage`` recibe el salario base implicito
        y los campos ``x_ulogix_*`` conservan el costo y su desglose. Odoo 19
        administra el contrato como ``hr.version`` a traves de los campos
        delegados de ``hr.employee``.
        """
        if self.dry_run:
            return {"creados": 0, "actualizados": 0, "desactivados": 0,
                    "modo": "dry-run"}
        requeridos = {"x_ulogix_managed", "x_ulogix_rol", "x_ulogix_linea",
                      "x_ulogix_turno", "x_ulogix_fase", "x_ulogix_estado",
                      "x_ulogix_costo_empleador", "x_ulogix_factor_prestacional",
                      "x_ulogix_arl_clase"}
        faltan = requeridos - self._campos_disponibles("hr.employee")
        if faltan:
            raise OdooError("Faltan campos RRHH x_ulogix_*: " + ", ".join(sorted(faltan)))

        from core.rrhh import ARL_CLASE_POR_ROL, desglosar_costo_empleador

        creados = actualizados = 0
        cedulas_vivas: set[str] = set()
        ids_resultado: list[int] = []
        for r in empleados:
            cedula = str(r.get("cedula") or "").strip()
            nombre = str(r.get("nombre") or "").strip()
            if not cedula or not nombre:
                raise OdooError("Cada empleado requiere cedula y nombre")
            cedulas_vivas.add(cedula)
            fase = str(r.get("fase") or "").strip()
            cargo = str(r.get("cargo") or r.get("rol_personal") or "Sin cargo").strip()
            departamento = ("Implementacion ULogix" if fase == "Implementacion"
                            else "Operacion Fontibon")
            dep_id = self._asegurar_por_nombre(
                "hr.department", departamento, {"company_id": settings.ODOO_COMPANY_ID})
            job_id = self._asegurar_por_nombre(
                "hr.job", cargo, {"company_id": settings.ODOO_COMPANY_ID})
            rol = str(r.get("rol_personal") or "").strip()
            arl = ARL_CLASE_POR_ROL.get(rol, "IV")
            costo = float(r.get("salario_mensual_cop") or 0)
            desglose = desglosar_costo_empleador(costo, arl)
            fecha = str(r.get("fecha_ingreso") or date.today().isoformat())[:10]
            estado = str(r.get("estado") or "activo").lower().strip()
            vals = {
                "name": nombre,
                "identification_id": cedula,
                "job_id": job_id,
                "department_id": dep_id,
                "active": estado != "inactivo",
                "work_email": str(r.get("email") or "").strip() or False,
                "work_phone": str(r.get("telefono") or "").strip() or False,
                "wage": float(desglose["salario_base_cop"]),
                "date_version": fecha,
                "x_ulogix_managed": True,
                "x_ulogix_rol": rol,
                "x_ulogix_linea": str(r.get("linea") or "").strip(),
                "x_ulogix_turno": str(r.get("turno") or "").strip(),
                "x_ulogix_fase": fase,
                "x_ulogix_estado": estado,
                "x_ulogix_costo_empleador": costo,
                "x_ulogix_factor_prestacional": float(
                    desglose["factor_prestacional_pct"]),
                "x_ulogix_arl_clase": arl,
            }
            ids = self._kw("hr.employee", "search",
                           [[["identification_id", "=", cedula]]],
                           {"limit": 1, "context": {"active_test": False}})
            if ids:
                self._kw("hr.employee", "write", [[ids[0]], vals])
                emp_id = ids[0]
                actualizados += 1
            else:
                emp_id = self._kw("hr.employee", "create", [vals])
                creados += 1
            ids_resultado.append(emp_id)

        gestionados = self._kw("hr.employee", "search",
                               [[["x_ulogix_managed", "=", True]]],
                               {"context": {"active_test": False}})
        desactivar = []
        if gestionados:
            actuales = self._kw("hr.employee", "read",
                                [gestionados, ["identification_id", "active"]])
            desactivar = [e["id"] for e in actuales
                          if str(e.get("identification_id") or "") not in cedulas_vivas
                          and e.get("active")]
            if desactivar:
                self._kw("hr.employee", "write", [desactivar, {"active": False}])
        return {"creados": creados, "actualizados": actualizados,
                "desactivados": len(desactivar), "ids": ids_resultado,
                "modo": "odoo"}

    def listar_empleados_ulogix(self, incluir_inactivos: bool = True) -> list[dict]:
        if self.dry_run:
            return []
        dominio = [["x_ulogix_managed", "=", True]]
        ids = self._kw("hr.employee", "search", [dominio], {
            "order": "name", "context": {"active_test": not incluir_inactivos}})
        if not ids:
            return []
        campos = ["name", "identification_id", "job_id", "department_id", "active",
                  "wage", "work_email", "work_phone", "version_id",
                  "x_ulogix_rol", "x_ulogix_linea", "x_ulogix_turno",
                  "x_ulogix_fase", "x_ulogix_estado", "x_ulogix_costo_empleador",
                  "x_ulogix_factor_prestacional", "x_ulogix_arl_clase"]
        return self._kw("hr.employee", "read", [ids, campos])

    def estado_nomina(self) -> dict:
        """Diagnostico del maestro laboral y configuracion de payroll."""
        if self.dry_run:
            return {"empleados": 0, "versiones": 0, "estructuras": 0,
                    "recibos": 0, "modo": "dry-run"}
        empleados = self.listar_empleados_ulogix()
        versiones = self._kw("hr.version", "search_count",
                             [[["employee_id", "in", [e["id"] for e in empleados]]]]) \
            if empleados else 0
        estructuras = self._kw("hr.payroll.structure", "search_count", [[]])
        recibos = self._kw("hr.payslip", "search_count",
                           [[["employee_id", "in", [e["id"] for e in empleados]]]]) \
            if empleados else 0
        return {"empleados": len(empleados), "versiones": versiones,
                "estructuras": estructuras, "recibos": recibos, "modo": "odoo"}

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
                self._kw("account.move", "write",
                         [borradores, {"invoice_date": date.today().isoformat()}])
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
            campos_mo = self._campos_disponibles("mrp.production")
            if "x_ulogix_linea" in campos_mo:
                tmpl = self._kw("product.template", "read",
                                [[tmpl_id], ["x_ulogix_linea"]])[0]
                linea = tmpl.get("x_ulogix_linea") or ""
                partes = referencia.split("/")
                mes = partes[1] if len(partes) > 1 else ""
                prev = self._kw("mrp.production", "search_read",
                                [[['x_ulogix_linea', '=', linea],
                                  ['origin', 'like', 'ULOGIX/%']]],
                                {"fields": ["x_ulogix_sequence"],
                                 "order": "x_ulogix_sequence desc,id desc", "limit": 1})
                secuencia = int(prev[0].get("x_ulogix_sequence") or 0) + 1 if prev else 1
                vals.update({
                    "x_ulogix_linea": linea, "x_ulogix_mes": mes,
                    "x_ulogix_root_origin": referencia,
                    "x_ulogix_target_qty": cantidad,
                    "x_ulogix_available_qty": 0.0,
                    "x_ulogix_synced_qty": 0.0,
                    "x_ulogix_sequence": secuencia,
                })
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
            if estado == "done":
                return {"ok": True, "modo": "existente-completada"}
            if estado == "cancel":
                return {"ok": False, "modo": "error",
                        "detalle": f"MO {mo_id} esta cancelada"}
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

    def avanzar_produccion_parcial(self, mo_id: int | None, mo_name: str,
                                   qty_a_producir: float) -> dict:
        """
        Registra un AVANCE PARCIAL de una orden de fabricacion todavia
        abierta (no la ultima porcion): descuenta en Odoo, de inmediato, la
        BOM proporcional a `qty_a_producir` y da entrada a esa misma
        cantidad de producto terminado — sin esperar a que la orden completa
        cierre. Usa el flujo nativo de "backorder" de mrp.production: fija
        `qty_producing`, marca los `stock.move` de componentes recogidos en
        esa proporcion, llama `button_mark_done` (que en Odoo, cuando
        qty_producing < product_qty, no cierra la orden sino que devuelve la
        accion del wizard `mrp.production.backorder`) y completa ese wizard
        con `to_backorder=True`: la orden ORIGINAL queda 'done' solo por
        `qty_a_producir` unidades (con sufijo -00N en el nombre) y Odoo crea
        AUTOMATICAMENTE una MO nueva por el remanente (mismo `origin`,
        mismo producto/BOM) que sigue abierta para el siguiente avance o
        para el cierre final (`completar_orden_fabricacion`, sin backorder
        porque ese ultimo llamado siempre cubre TODO lo que quede).

        Verificado en vivo contra Odoo real (saas-19.3): la respuesta XML-RPC
        de `action_backorder` a veces trae un `Fault` de marshalling
        ("cannot marshal None") aunque la operacion SI se ejecuto en el
        servidor — por eso este metodo no confia en esa respuesta y en su
        lugar relee el estado para confirmar el resultado.

        Devuelve {'ok', 'mo_id_nuevo', 'mo_name_nuevo'} (la MO backorder que
        el middleware debe rastrear de ahora en adelante para este SKU) o
        {'ok': False, 'detalle'} si algo fallo de verdad.
        """
        if self.dry_run or mo_id is None or qty_a_producir <= 0:
            state_store.log("odoo", "avanzar_produccion_parcial (dry-run/no-op)",
                            f"{mo_name} x {qty_a_producir:g}")
            return {"ok": True, "modo": "dry-run", "mo_id_nuevo": mo_id, "mo_name_nuevo": mo_name}
        try:
            info = self._kw("mrp.production", "read",
                            [[mo_id], ["state", "product_qty", "origin"]])[0]
            if info["state"] in ("done", "cancel"):
                return {"ok": False, "detalle": f"MO {mo_id} ya esta {info['state']}"}
            if info["state"] == "draft":
                self._kw("mrp.production", "action_confirm", [[mo_id]])
            self._kw("mrp.production", "action_assign", [[mo_id]])
            objetivo_mo = info["product_qty"]
            qty_parcial = min(qty_a_producir, objetivo_mo)

            move_ids = self._kw("stock.move", "search",
                                [[["raw_material_production_id", "=", mo_id]]])
            moves = self._kw("stock.move", "read", [move_ids, ["product_uom_qty"]])
            self._kw("mrp.production", "write", [[mo_id], {"qty_producing": qty_parcial}])
            for mv in moves:
                cant = round(mv["product_uom_qty"] * qty_parcial / objetivo_mo, 6)
                try:  # Odoo <= 16
                    self._kw("stock.move", "write", [[mv["id"]], {"quantity_done": cant}])
                except Exception:  # Odoo 17+
                    self._kw("stock.move", "write",
                             [[mv["id"]], {"quantity": cant, "picked": True}])

            try:
                self._kw("mrp.production", "button_mark_done", [[mo_id]])
            except Exception:  # noqa: BLE001 — puede fallar si ya no hay wizard que mostrar
                pass

            estado = self._kw("mrp.production", "read", [[mo_id], ["state"]])[0]["state"]
            if estado == "done":
                # qty_parcial == objetivo_mo (cerro sin backorder): no deberia
                # pasar aqui (el middleware solo llama esto en ordenes que
                # AUN no completan), pero si pasa no hay MO nueva que rastrear
                state_store.log("odoo", "avanzar_produccion_parcial: cerro sin backorder",
                                f"id={mo_id} qty={qty_parcial:g}")
                return {"ok": True, "mo_id_nuevo": mo_id, "mo_name_nuevo": mo_name}

            try:
                wiz_id = self._kw("mrp.production.backorder", "create", [{
                    "mrp_production_ids": [(6, 0, [mo_id])],
                    "mrp_production_backorder_line_ids": [(0, 0, {
                        "mrp_production_id": mo_id, "to_backorder": True})],
                }])
                self._kw("mrp.production.backorder", "action_backorder", [[wiz_id]])
            except Exception:  # noqa: BLE001 — Fault de marshalling conocido, ver docstring
                pass

            nuevas = self._kw("mrp.production", "search",
                              [[["origin", "=", info["origin"]],
                                ["state", "not in", ["done", "cancel"]]]])
            if not nuevas:
                return {"ok": False, "detalle": f"no aparecio MO backorder para origin={info['origin']}"}
            nuevo_id = nuevas[0]
            nuevo_name = self._kw("mrp.production", "read", [[nuevo_id], ["name"]])[0]["name"]
            state_store.log("odoo", "avanzar_produccion_parcial",
                            f"{mo_name} +{qty_parcial:g} -> {nuevo_name} (id={nuevo_id})")
            return {"ok": True, "mo_id_nuevo": nuevo_id, "mo_name_nuevo": nuevo_name}
        except Exception as e:  # noqa: BLE001
            state_store.log("odoo", "avanzar_produccion_parcial ERROR", f"{mo_id}: {e}")
            return {"ok": False, "detalle": str(e)}

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
        reutiliza. En Odoo 19 usa el asistente publico
        `sale.advance.payment.inv`. Algunas instalaciones ejecutan
        `create_invoices` correctamente pero devuelven un Fault XML-RPC al
        intentar serializar ``None``; por eso la evidencia definitiva es
        releer `account.move`, no confiar solo en la respuesta del wizard.
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
                # Odoo SaaS 19 ya no expone metodos privados por XML-RPC
                # (`sale.order._create_invoices`) ni el legado
                # `action_invoice_create`. Se usa el wizard publico oficial.
                wiz_id = self._kw("sale.advance.payment.inv", "create", [{
                    "advance_payment_method": "delivered",
                    "sale_order_ids": [(6, 0, [so_id])],
                }])
                fallo_wizard = None
                try:
                    self._kw("sale.advance.payment.inv", "create_invoices", [[wiz_id]],
                             {"context": {"active_model": "sale.order",
                                          "active_id": so_id,
                                          "active_ids": [so_id]}})
                except Exception as exc:  # Odoo puede ejecutar y fallar al serializar None
                    fallo_wizard = exc
                factura_ids = self._kw("account.move", "search",
                                       [[["invoice_origin", "=", so_name],
                                         ["move_type", "=", "out_invoice"],
                                         ["state", "!=", "cancel"]]])
                if fallo_wizard and not factura_ids:
                    raise fallo_wizard
            if not factura_ids:
                return {"ok": False, "modo": "error",
                        "detalle": "Odoo no genero la factura (revisa que la SO "
                                   "tenga lineas entregadas/facturables)"}
            borradores = self._kw("account.move", "search",
                                  [[["id", "in", factura_ids], ["state", "=", "draft"]]])
            if borradores:
                self._kw("account.move", "write",
                         [borradores, {"invoice_date": date.today().isoformat()}])
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
        filas = self._kw("sale.order", "read",
                         [ids, ["name", "partner_id", "state", "amount_total",
                                "client_order_ref", "date_order"]])
        filas = self._aplanar_many2one(filas, "partner_id", "cliente")
        return self._normalizar_filas_tabla(
            filas, texto=("name", "cliente", "state", "client_order_ref", "date_order"),
            numerico=("amount_total",))

    def listar_facturas(self, tipo: str = "out_invoice", limit: int = 40) -> list[dict]:
        """`tipo`: 'out_invoice' (cliente) o 'in_invoice' (proveedor)."""
        if self.dry_run:
            return []
        ids = self._kw("account.move", "search", [[["move_type", "=", tipo]]],
                       {"limit": limit, "order": "id desc"})
        filas = self._kw("account.move", "read",
                         [ids, ["name", "partner_id", "state", "amount_total",
                                "invoice_origin", "invoice_date"]])
        filas = self._aplanar_many2one(filas, "partner_id", "tercero")
        return self._normalizar_filas_tabla(
            filas, texto=("name", "tercero", "state", "invoice_origin", "invoice_date"),
            numerico=("amount_total",))

    def listar_ordenes_fabricacion(self, limit: int = 40) -> list[dict]:
        if self.dry_run:
            return []
        ids = self._kw("mrp.production", "search", [[]],
                       {"limit": limit, "order": "id desc"})
        filas = self._kw("mrp.production", "read",
                         [ids, ["name", "product_id", "product_qty", "state", "origin"]])
        filas = self._aplanar_many2one(filas, "product_id", "producto")
        return self._normalizar_filas_tabla(
            filas, texto=("name", "producto", "state", "origin"),
            numerico=("product_qty",))

    @staticmethod
    def _aplanar_many2one(filas: list[dict], campo: str,
                          campo_nombre: str) -> list[dict]:
        """Convierte ``[id, nombre]`` de XML-RPC en columnas escalares.

        Pandas tolera la mezcla de enteros y listas/strings, pero PyArrow no;
        Streamlit usa Arrow para ``st.dataframe``. Mantener el id numerico y
        separar el nombre evita errores de conversion en cualquier tabla.
        """
        salida: list[dict] = []
        for original in filas:
            fila = dict(original)
            valor = fila.get(campo)
            if isinstance(valor, (list, tuple)):
                fila[campo] = valor[0] if valor else None
                fila[campo_nombre] = str(valor[1]) if len(valor) > 1 else ""
            elif isinstance(valor, (int, float)) and not isinstance(valor, bool):
                fila[campo] = int(valor)
                fila[campo_nombre] = ""
            elif valor:
                fila[campo] = None
                fila[campo_nombre] = str(valor)
            else:
                fila[campo] = None
                fila[campo_nombre] = ""
            salida.append(fila)
        return salida

    @staticmethod
    def _normalizar_filas_tabla(filas: list[dict],
                                texto: tuple[str, ...] = (),
                                numerico: tuple[str, ...] = ()) -> list[dict]:
        """Elimina los ``False`` que Odoo usa como nulos en tablas publicas.

        XML-RPC representa un Char/Date vacio como ``False``. Si otras filas
        contienen texto, Pandas crea una columna ``object`` mixta que PyArrow
        no puede serializar. Los campos declarados quedan homogeneos antes de
        llegar a Streamlit.
        """
        salida: list[dict] = []
        for original in filas:
            fila = dict(original)
            for campo in texto:
                valor = fila.get(campo)
                fila[campo] = "" if valor is False or valor is None else str(valor)
            for campo in numerico:
                valor = fila.get(campo)
                fila[campo] = 0.0 if valor is False or valor is None else float(valor)
            salida.append(fila)
        return salida

    def listar_mo_ulogix_activas(self, linea: str | None = None,
                                 limit: int = 200) -> list[dict]:
        """Cola de manufactura ULOGIX gobernada enteramente por Odoo."""
        if self.dry_run:
            por_sku = {"P1-CC350-RGB": "L1", "P2-QT1500-PET": "L2",
                       "P3-GARR25L": "L3"}
            salida = []
            for po in reversed(state_store.listar_pos(limit)):
                if po.get("estado") != "abierta":
                    continue
                linea_po = po.get("linea") or por_sku.get(po.get("sku"), "")
                if linea and linea_po != linea:
                    continue
                salida.append({**po, "id": po.get("mo_id"),
                               "name": po.get("mo_name"),
                               "x_ulogix_linea": linea_po,
                               "x_ulogix_mes": po.get("detalle") or "",
                               "x_ulogix_root_origin": po.get("detalle") or po["po_name"],
                               "x_ulogix_target_qty": po["qty_objetivo"],
                               "x_ulogix_available_qty": po["qty_producida"],
                               "x_ulogix_synced_qty": po["qty_sincronizada_odoo"],
                               "x_ulogix_sequence": po["id"]})
                if len(salida) >= limit:
                    break
            return salida
        campos = self._campos_disponibles("mrp.production")
        requeridos = {"x_ulogix_linea", "x_ulogix_root_origin",
                      "x_ulogix_target_qty", "x_ulogix_available_qty",
                      "x_ulogix_synced_qty", "x_ulogix_sequence"}
        if not requeridos.issubset(campos):
            raise OdooError("Faltan campos x_ulogix_* en mrp.production")
        dominio = [["origin", "like", "ULOGIX/%"],
                   ["state", "not in", ["done", "cancel"]]]
        if linea:
            dominio.append(["x_ulogix_linea", "=", linea])
        ids = self._kw("mrp.production", "search", [dominio],
                       {"limit": limit, "order": "x_ulogix_sequence,id"})
        leer = ["name", "product_id", "product_qty", "state", "origin",
                "x_ulogix_linea", "x_ulogix_mes", "x_ulogix_root_origin",
                "x_ulogix_target_qty", "x_ulogix_available_qty",
                "x_ulogix_synced_qty", "x_ulogix_sequence"]
        mos = self._kw("mrp.production", "read", [ids, leer]) if ids else []
        pids = sorted({m["product_id"][0] for m in mos if m.get("product_id")})
        productos = self._kw("product.product", "read",
                             [pids, ["default_code"]]) if pids else []
        codigos = {p["id"]: p.get("default_code") or "" for p in productos}
        salida = []
        for m in mos:
            objetivo = float(m.get("x_ulogix_target_qty") or m.get("product_qty") or 0)
            disponible = float(m.get("x_ulogix_available_qty") or 0)
            salida.append({**m, "sku": codigos.get(m["product_id"][0], ""),
                            "qty_objetivo": objetivo,
                            "qty_producida": disponible,
                            "qty_sincronizada_odoo": float(m.get("x_ulogix_synced_qty") or 0),
                            "mo_id": m["id"], "mo_name": m["name"],
                            "po_name": m["name"],
                            "estado": "abierta"})
        return salida

    def orden_activa_ulogix(self, linea: str) -> dict | None:
        if self.dry_run:
            sku = {"L1": "P1-CC350-RGB", "L2": "P2-QT1500-PET",
                   "L3": "P3-GARR25L"}.get(linea)
            po = state_store.orden_activa(sku) if sku else None
            if po is None:
                return None
            return {**po, "id": po.get("mo_id"), "name": po.get("mo_name"),
                    "x_ulogix_linea": linea,
                    "x_ulogix_mes": po.get("detalle") or "",
                    "x_ulogix_root_origin": po.get("detalle") or po["po_name"],
                    "x_ulogix_target_qty": po["qty_objetivo"],
                    "x_ulogix_available_qty": po["qty_producida"],
                    "x_ulogix_synced_qty": po["qty_sincronizada_odoo"],
                    "x_ulogix_sequence": po["id"]}
        mos = self.listar_mo_ulogix_activas(linea, 1)
        return mos[0] if mos else None

    def actualizar_disponible_ulogix(self, linea: str, disponible: float) -> dict | None:
        """Valida y persiste el contador absoluto MES en la MO activa."""
        mo = self.orden_activa_ulogix(linea)
        if mo is None:
            return None
        anterior = float(mo["qty_producida"])
        if disponible < anterior:
            return {**mo, "delta": 0.0, "ignorado": True, "completada": False}
        nuevo = min(float(disponible), float(mo["qty_objetivo"]))
        if self.dry_run:
            if nuevo <= anterior + 1e-9:
                return {**mo, "delta": 0.0, "ignorado": True,
                        "completada": False}
            state_store.actualizar_disponible(mo["sku"], nuevo)
            return {**mo, "qty_producida": nuevo, "delta": nuevo - anterior,
                    "ignorado": False,
                    "completada": nuevo >= float(mo["qty_objetivo"])}
        self._kw("mrp.production", "write",
                 [[mo["mo_id"]], {"x_ulogix_available_qty": nuevo}])
        return {**mo, "qty_producida": nuevo, "delta": nuevo - anterior,
                "ignorado": False, "completada": nuevo >= float(mo["qty_objetivo"])}

    def heredar_trazabilidad_backorder(self, anterior: dict, mo_id_nuevo: int,
                                       mo_name_nuevo: str, sincronizada: float) -> dict:
        vals = {
            "x_ulogix_linea": anterior["x_ulogix_linea"],
            "x_ulogix_mes": anterior.get("x_ulogix_mes") or "",
            "x_ulogix_root_origin": anterior.get("x_ulogix_root_origin") or anterior["origin"],
            "x_ulogix_target_qty": anterior["qty_objetivo"],
            "x_ulogix_available_qty": anterior["qty_producida"],
            "x_ulogix_synced_qty": sincronizada,
            "x_ulogix_sequence": anterior.get("x_ulogix_sequence") or 0,
        }
        self._kw("mrp.production", "write", [[mo_id_nuevo], vals])
        return {**anterior, **vals, "mo_id": mo_id_nuevo, "id": mo_id_nuevo,
                "mo_name": mo_name_nuevo, "name": mo_name_nuevo,
                "qty_sincronizada_odoo": sincronizada}

    def listar_ordenes(self, limit: int = 40) -> list[dict]:
        if self.dry_run:
            return [{"name": p["po_name"], "state": p["estado"],
                     "origin": p.get("detalle", ""), "amount_total": 0}
                    for p in state_store.listar_pos(limit)]
        ids = self._kw("purchase.order", "search", [[]],
                       {"limit": limit, "order": "id desc"})
        filas = self._kw("purchase.order", "read",
                         [ids, ["name", "partner_id", "state", "amount_total",
                                "origin", "date_order"]])
        filas = self._aplanar_many2one(filas, "partner_id", "proveedor")
        return self._normalizar_filas_tabla(
            filas, texto=("name", "proveedor", "state", "origin", "date_order"),
            numerico=("amount_total",))

    # ------------------------------------------------------ maestros/stock de lectura
    def listar_clientes(self, limit: int = 200) -> list[dict]:
        """Clientes activos de Odoo; no crea ni modifica contactos."""
        if self.dry_run:
            return []
        ids = self._kw("res.partner", "search",
                       [[["customer_rank", ">", 0], ["active", "=", True]]],
                       {"limit": limit, "order": "name"})
        campos = ["name", "email", "phone", "customer_rank"]
        if "x_ulogix_canal" in self._campos_disponibles("res.partner"):
            campos += ["city", "x_ulogix_canal", "x_ulogix_participacion"]
        filas = self._kw("res.partner", "read", [ids, campos])
        texto = tuple(c for c in ("name", "email", "phone", "city",
                                  "x_ulogix_canal") if c in campos)
        numerico = tuple(c for c in ("customer_rank", "x_ulogix_participacion")
                         if c in campos)
        return self._normalizar_filas_tabla(filas, texto=texto, numerico=numerico)

    def listar_stock(self, limit: int = 5000) -> list[dict]:
        """Saldo agregado de ``stock.quant`` en ubicaciones internas.

        Esta es la fuente de verdad del inventario mostrado por el ERP. La
        tabla SQLite ``inventario_stock`` queda como cache operativo del
        puente MQTT y nunca se usa para reemplazar este saldo.
        """
        if self.dry_run:
            return []
        ids = self._kw("stock.quant", "search",
                       [[["location_id.usage", "=", "internal"]]],
                       {"limit": limit})
        if not ids:
            return []
        campos = self._campos_disponibles("stock.quant")
        leer = [c for c in ["product_id", "quantity", "reserved_quantity"]
                if c in campos]
        quants = self._kw("stock.quant", "read", [ids, leer])
        pids = sorted({q["product_id"][0] for q in quants if q.get("product_id")})
        productos = self._kw(
            "product.product", "read",
            [pids, ["default_code", "display_name", "uom_id"]]) if pids else []
        por_id = {p["id"]: p for p in productos}
        agregado: dict[int, dict] = {}
        for q in quants:
            if not q.get("product_id"):
                continue
            pid = q["product_id"][0]
            p = por_id.get(pid, {})
            fila = agregado.setdefault(pid, {
                "product_id": pid,
                "codigo": p.get("default_code") or "",
                "producto": p.get("display_name") or q["product_id"][1],
                "uom": (p.get("uom_id") or [None, ""])[1],
                "cantidad": 0.0,
                "reservada": 0.0,
            })
            fila["cantidad"] += float(q.get("quantity") or 0.0)
            fila["reservada"] += float(q.get("reserved_quantity") or 0.0)
        for fila in agregado.values():
            fila["disponible"] = fila["cantidad"] - fila["reservada"]
        return sorted(agregado.values(), key=lambda x: (x["codigo"], x["producto"]))

    def listar_lotes_fabricados(self, limit: int = 300) -> list[dict]:
        """MO terminadas en Odoo y cantidad aun no comprometida en SO.

        La vinculacion usa el contrato idempotente
        ``ULOGIX-VTA/<mo_name>/<cliente>``. Se cuentan ordenes de venta no
        canceladas para impedir vender dos veces un mismo lote, incluso si
        el cache SQLite se borra o queda desactualizado.
        """
        if self.dry_run:
            return []
        campos_mo = self._campos_disponibles("mrp.production")
        campos = [c for c in ["name", "product_id", "product_qty", "qty_produced",
                              "state", "origin", "date_finished"] if c in campos_mo]
        ids = self._kw("mrp.production", "search",
                       [[["state", "=", "done"], ["origin", "like", "ULOGIX/%"]]],
                       {"limit": limit, "order": "id desc"})
        mos = self._kw("mrp.production", "read", [ids, campos]) if ids else []
        pids = sorted({m["product_id"][0] for m in mos if m.get("product_id")})
        productos = self._kw("product.product", "read",
                             [pids, ["default_code", "display_name", "list_price"]]) \
            if pids else []
        por_id = {p["id"]: p for p in productos}
        salida = []
        for mo in mos:
            pid = mo["product_id"][0]
            p = por_id.get(pid, {})
            prefijo = f"ULOGIX-VTA/{mo['name']}/"
            so_ids = self._kw("sale.order", "search",
                              [[["client_order_ref", "like", prefijo + "%"],
                                ["state", "!=", "cancel"]]])
            comprometida = 0.0
            if so_ids:
                line_ids = self._kw("sale.order.line", "search",
                                    [[["order_id", "in", so_ids],
                                      ["product_id", "=", pid]]])
                if line_ids:
                    lineas = self._kw("sale.order.line", "read",
                                      [line_ids, ["product_uom_qty"]])
                    comprometida = sum(float(l.get("product_uom_qty") or 0) for l in lineas)
            producida = float(mo.get("qty_produced") or mo.get("product_qty") or 0)
            salida.append({
                "mo_id": mo["id"], "mo_name": mo["name"],
                "sku": p.get("default_code") or "",
                "producto": p.get("display_name") or mo["product_id"][1],
                "cantidad_producida": producida,
                "cantidad_comprometida": comprometida,
                "cantidad_disponible": max(0.0, producida - comprometida),
                "precio_venta_cop": float(p.get("list_price") or 0),
                "origin": mo.get("origin") or "",
                "date_finished": mo.get("date_finished") or "",
            })
        return salida

    def plan_compras_desde_demanda(self, demanda_mensual, scrap: float = 0.02,
                                   cobertura_meses: int = 3) -> list[dict]:
        """Explosión MRP usando exclusivamente BOM, stock y proveedores Odoo.

        ``demanda_mensual`` sigue siendo el plan aprobado por el ERP/Sheets;
        las razones de consumo, existencias, MOQ, precio y plazo se leen de
        ``mrp.bom``, ``stock.quant`` y ``product.supplierinfo``. No consulta
        ``data/bom.csv`` ni otro maestro local.
        """
        if self.dry_run:
            raise OdooError("El MRP externo requiere conexion real a Odoo")
        meses = {"Enero": 1, "Ene": 1, "Febrero": 2, "Feb": 2,
                 "Marzo": 3, "Mar": 3, "Abril": 4, "Abr": 4,
                 "Mayo": 5, "May": 5, "Junio": 6, "Jun": 6,
                 "Julio": 7, "Jul": 7, "Agosto": 8, "Ago": 8,
                 "Septiembre": 9, "Sep": 9, "Octubre": 10, "Oct": 10,
                 "Noviembre": 11, "Nov": 11, "Diciembre": 12, "Dic": 12}
        from core.forecast import normalizar_demanda_mensual
        demanda_mensual = normalizar_demanda_mensual(demanda_mensual)
        faltan = {"ano", "mes", "etiqueta"} - set(demanda_mensual.columns)
        if faltan:
            raise OdooError("Demanda mensual sin campos temporales: "
                            + ", ".join(sorted(faltan)))
        registros = demanda_mensual.head(cobertura_meses).to_dict("records")
        stock = {r["codigo"]: float(r["disponible"]) for r in self.listar_stock()}
        filas: list[dict] = []
        for m in registros:
            ano, mes = int(m["ano"]), str(m["mes"])
            necesidad = date(ano, meses[mes], 1)
            for clave, unidades in m.items():
                if not str(clave).endswith("_unidades"):
                    continue
                sku = str(clave)[:-9]
                unidades = float(unidades)
                pids = self._kw("product.product", "search",
                                 [[["default_code", "=", sku]]], {"limit": 1})
                if not pids:
                    raise OdooError(f"Producto {sku} no existe en Odoo")
                prod = self._kw("product.product", "read",
                                [pids, ["product_tmpl_id"]])[0]
                tmpl = prod["product_tmpl_id"][0]
                bom_ids = self._kw("mrp.bom", "search",
                                   [[["product_tmpl_id", "=", tmpl]]], {"limit": 1})
                if not bom_ids:
                    raise OdooError(f"{sku} no tiene BOM en Odoo")
                bom = self._kw("mrp.bom", "read",
                               [bom_ids, ["product_qty", "bom_line_ids"]])[0]
                campos_linea = self._campos_disponibles("mrp.bom.line")
                campo_uom = "product_uom_id" if "product_uom_id" in campos_linea else "product_uom"
                leer_linea = ["product_id", "product_qty"]
                if campo_uom in campos_linea:
                    leer_linea.append(campo_uom)
                lineas = self._kw("mrp.bom.line", "read",
                                  [bom["bom_line_ids"], leer_linea])
                base_bom = float(bom.get("product_qty") or 1.0)
                for linea in lineas:
                    comp_id = linea["product_id"][0]
                    comp = self._kw("product.product", "read",
                                    [[comp_id], ["default_code", "display_name",
                                                 "product_tmpl_id"]])[0]
                    codigo = comp.get("default_code") or ""
                    ratio = float(linea["product_qty"]) / base_bom
                    bruto = unidades * ratio * (1 + scrap)
                    usado = min(stock.get(codigo, 0.0), bruto)
                    stock[codigo] = stock.get(codigo, 0.0) - usado
                    neto = bruto - usado
                    if neto <= 1e-9:
                        continue
                    sup_ids = self._kw(
                        "product.supplierinfo", "search",
                        [[["product_tmpl_id", "=", comp["product_tmpl_id"][0]]]],
                        {"limit": 1, "order": "sequence,id"})
                    if not sup_ids:
                        raise OdooError(f"{codigo} no tiene proveedor/precio en Odoo")
                    sup = self._kw("product.supplierinfo", "read",
                                   [sup_ids, ["partner_id", "price", "min_qty", "delay"]])[0]
                    moq = max(float(sup.get("min_qty") or 1.0), 1e-9)
                    qty = math.ceil(neto / moq) * moq
                    lead = int(sup.get("delay") or 0)
                    filas.append({
                        "etiqueta_mes": m["etiqueta"], "producto": sku,
                        "unidades_producto_mes": round(unidades),
                        "componente": codigo, "descripcion": comp["display_name"],
                        "uom": linea.get(campo_uom, [None, ""])[1],
                        "cantidad": round(qty, 6), "requerimiento_neto": round(neto, 6),
                        "proveedor": sup["partner_id"][1],
                        "precio_unitario_cop": float(sup.get("price") or 0),
                        "subtotal_cop": round(qty * float(sup.get("price") or 0)),
                        "lead_time_dias": lead,
                        "fecha_pedido": (necesidad - timedelta(days=lead)).isoformat(),
                        "fecha_necesidad": necesidad.isoformat(),
                    })
        return filas
