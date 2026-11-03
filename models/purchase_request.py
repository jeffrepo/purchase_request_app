from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


STOCK_LOCATION_DOMAIN = [
    ("usage", "=", "internal"),
    ("complete_name", "=ilike", "%/stock"),
]


class PurchaseRequest(models.Model):
    _name = "purchase.request"
    _description = "Solicitud de Compra"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"
    _check_company_auto = True

    name = fields.Char(default="/", copy=False, tracking=True, readonly=True, required=True)
    request_datetime = fields.Datetime(string="Fecha y hora", default=fields.Datetime.now, required=True)
    company_id = fields.Many2one(
        "res.company", string="Compañía", required=True,
        default=lambda self: self.env.company,
    )
    location_id = fields.Many2one(
        "stock.location", string="Ubicación destino", required=True,
        domain=STOCK_LOCATION_DOMAIN, check_company=True,
        help="Obligatoria en todas las solicitudes, tanto de compra como de traslado.",
    )
    category_id = fields.Many2one(
        "product.category", string="Categoría de productos", required=True,
        help="Permite productos de esta categoría y de todas sus subcategorías.",
    )
    allowed_category_ids = fields.Many2many(
        "product.category", compute="_compute_allowed_category_ids",
        string="Categorías permitidas",
    )
    line_ids = fields.One2many("purchase.request.line", "request_id", string="Productos")
    state = fields.Selection([
        ("draft", "Borrador"),
        ("requested", "Solicitado"),
        ("confirmed", "Confirmado"),
        ("closed", "Cerrado"),
        ("cancelled", "Cancelado"),
    ], default="draft", tracking=True)
    purchase_order_ids = fields.One2many(
        "purchase.order", "purchase_request_id", string="Compras generadas", readonly=True,
    )
    picking_ids = fields.One2many(
        "stock.picking", "purchase_request_id", string="Traslados generados", readonly=True,
        domain=[("picking_type_id.code", "=", "internal")],
    )
    has_pending_purchases = fields.Boolean(compute="_compute_pending_operations")
    has_pending_transfers = fields.Boolean(compute="_compute_pending_operations")

    @api.depends("line_ids.request_type", "line_ids.is_processed", "line_ids.qty_requested")
    def _compute_pending_operations(self):
        for request in self:
            pending = request.line_ids.filtered(lambda line: not line.is_processed and line.qty_requested > 0)
            request.has_pending_purchases = any(line.request_type == "purchase" for line in pending)
            request.has_pending_transfers = any(line.request_type == "transfer" for line in pending)

    def write(self, vals):
        if "category_id" in vals and not vals["category_id"]:
            raise ValidationError(_("La Categoría de productos es obligatoria."))
        if "location_id" in vals and not vals["location_id"]:
            raise ValidationError(_("La Ubicación destino es obligatoria en todas las solicitudes."))
        if "location_id" not in vals:
            self._check_destination()
        if {"company_id", "location_id"} & vals.keys():
            self.line_ids._lock_for_processing()
            for request in self:
                processed = request.line_ids.filtered("is_processed")
                if processed and "company_id" in vals and vals["company_id"] != request.company_id.id:
                    raise UserError(_("No puedes cambiar la compañía de una solicitud con líneas procesadas."))
                if (any(line.request_type == "transfer" for line in processed)
                        and "location_id" in vals and vals["location_id"] != request.location_id.id):
                    raise UserError(_("No puedes cambiar la ubicación destino de un traslado ya generado."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_processed(self):
        self.line_ids._lock_for_processing()
        if any(self.line_ids.mapped("is_processed")):
            raise UserError(_("No puedes eliminar una solicitud con líneas procesadas."))

    @api.model_create_multi
    def create(self, vals_list):
        defaults = self.default_get(["category_id", "location_id"])
        for vals in vals_list:
            if not vals.get("category_id", defaults.get("category_id")):
                raise ValidationError(_("La Categoría de productos es obligatoria."))
            if not vals.get("location_id", defaults.get("location_id")):
                raise ValidationError(_("La Ubicación destino es obligatoria en todas las solicitudes."))
            if not vals.get("name") or vals["name"] in ("/", "Nuevo", _("Nuevo")):
                company = self.env["res.company"].browse(
                    vals.get("company_id") or self.default_get(["company_id"])["company_id"]
                )
                vals["name"] = self.with_company(company)._next_request_name()
        return super().create(vals_list)

    @api.model
    def _next_request_name(self):
        name = self.env["ir.sequence"].next_by_code("purchase.request")
        if not name:
            raise UserError(_("Configura una secuencia activa con el código purchase.request."))
        return name

    @api.model
    def _get_category_descendants(self, category):
        """Follow actual parents at every depth, even if parent_path is stale."""
        categories = category
        level = category
        while level:
            level = self.env["product.category"].search([
                ("parent_id", "in", level.ids),
            ]) - categories
            categories |= level
        return categories

    @api.depends("category_id")
    def _compute_allowed_category_ids(self):
        categories_by_root = {}
        for request in self:
            category = request.category_id
            if category.id not in categories_by_root:
                categories_by_root[category.id] = self._get_category_descendants(category)
            request.allowed_category_ids = categories_by_root[category.id]

    @api.constrains("category_id", "line_ids")
    def _check_product_category(self):
        if any(not request.category_id for request in self):
            raise ValidationError(_("La Categoría de productos es obligatoria."))
        for request in self.filtered("category_id"):
            categories = self._get_category_descendants(request.category_id)
            invalid_lines = request.line_ids.filtered(
                lambda line: line.product_id and line.product_id.categ_id not in categories
            )
            if invalid_lines:
                raise ValidationError(_(
                    "Los productos deben pertenecer a la categoría %(category)s o a sus "
                    "subcategorías. Revisa: %(products)s.",
                    category=request.category_id.display_name,
                    products=", ".join(invalid_lines.product_id.mapped("display_name")),
                ))

    def _notify_group(self, xmlid, message):
        group = self.env.ref(xmlid, raise_if_not_found=False)
        if not group:
            return
        partners = group.users.mapped("partner_id")
        if not partners:
            return
        self.message_notify(
            partner_ids=partners.ids,
            body=message,
            subject=_("Notificación de solicitud de compra"),
        )

    def action_request(self):
        self._check_destination()
        for rec in self:
            if not rec.line_ids:
                raise UserError(_("Agrega al menos una línea."))
            rec.state = "requested"
            rec._notify_group(
                "purchase_request_app.group_operations_manager",
                _("Hay una solicitud pendiente por confirmar: %s") % rec.name,
            )

    def action_confirm(self):
        self._check_product_category()
        self._check_destination()
        for rec in self:
            rec.state = "confirmed"
            rec._notify_group(
                "purchase_request_app.group_warehouse_lead",
                _("Solicitud confirmada (%s). Revisa el tipo de operación de cada línea.") % rec.name,
            )

    @api.constrains("location_id")
    def _check_destination(self):
        for request in self:
            if not request.location_id:
                raise ValidationError(_(
                    "Completa la Ubicación destino de la solicitud %s. Es obligatoria "
                    "tanto para compras como para traslados.",
                    request.name,
                ))

    def action_close(self):
        self.write({"state": "closed"})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_reset_to_draft(self):
        self.write({"state": "draft"})

    def _try_close_request(self):
        """Purchase confirmations and completed transfers fulfil different demand."""
        # Confirming a purchase or completing a transfer must not require read
        # access to the other operation's documents just to update this state.
        for request in self.sudo().filtered(lambda rec: rec.state not in ("closed", "cancelled")):
            requested = defaultdict(float)
            fulfilled = defaultdict(float)
            for line in request.line_ids.filtered(lambda line: line.qty_requested > 0):
                key = (line.request_type, line.product_id, False, False)
                if line.request_type == "transfer":
                    key = (line.request_type, line.product_id, line.source_location_id.id, request.location_id.id)
                requested[key] += line.product_uom_id._compute_quantity(
                    line.qty_requested, line.product_id.uom_id, round=False,
                )

            purchase_lines = request.purchase_order_ids.filtered(
                lambda order: order.state in ("purchase", "done")
            ).order_line.filtered("product_id")
            for line in purchase_lines:
                fulfilled[("purchase", line.product_id, False, False)] += line.product_uom._compute_quantity(
                    line.product_qty, line.product_id.uom_id, round=False,
                )
            for move in request.picking_ids.move_ids.filtered(lambda move: move.state == "done"):
                key = ("transfer", move.product_id, move.location_id.id, move.location_dest_id.id)
                fulfilled[key] += move.product_uom._compute_quantity(
                    move.quantity, move.product_id.uom_id, round=False,
                )
            if requested and all(
                float_compare(fulfilled[key], quantity, precision_rounding=key[1].uom_id.rounding) >= 0
                for key, quantity in requested.items()
            ):
                request.state = "closed"

    def action_generate_purchase_orders(self):
        self.ensure_one()
        self._check_destination()
        self = self.with_company(self.company_id)
        self.line_ids._lock_for_processing()
        lines = self.line_ids.filtered(
            lambda line: line.request_type == "purchase" and line.selected_for_action
            and line.qty_requested > 0 and not line.is_processed
        )
        if not lines:
            raise UserError(_(
                "Selecciona líneas de compra pendientes con cantidad solicitada mayor a cero. "
                "Las líneas procesadas no pueden generar otra compra."
            ))
        if any(not line.vendor_id for line in lines):
            raise UserError(_("Indica un proveedor en cada línea seleccionada."))
        self._check_product_category()

        company = self.company_id
        ab_category = company.purchase_request_ab_category_id
        if not ab_category:
            raise UserError(_("Configura la categoría de A&B en Ajustes > Compras > Solicitudes de compra."))
        ab_categories = self._get_category_descendants(ab_category)

        # A purchase order has one operation type, even when the vendor is shared.
        grouped = defaultdict(list)
        for line in lines:
            is_ab = line.product_id.categ_id in ab_categories
            picking_type = (
                company.purchase_request_ab_picking_type_id if is_ab
                else company.purchase_request_supplies_picking_type_id
            )
            if not picking_type:
                raise UserError(_(
                    "Configura el tipo de operación para %s en Ajustes > Compras > Solicitudes de compra.",
                    "A&B" if is_ab else "insumos",
                ))
            if (not picking_type.active or picking_type.code != "incoming"
                    or picking_type.company_id != company
                    or picking_type.default_location_dest_id.usage != "internal"
                    or not picking_type.default_location_dest_id.active):
                raise UserError(_(
                    "El tipo de operación %(operation)s debe ser una recepción activa de "
                    "%(company)s con una ubicación destino interna activa.",
                    operation=picking_type.display_name, company=company.display_name,
                ))
            grouped[(line.vendor_id.id, picking_type.id)].append(line)

        po_model = self.env["purchase.order"].with_company(company)
        created_pos = po_model.browse()
        for (vendor_id, picking_type_id), lines in grouped.items():
            vals = {
                "partner_id": vendor_id,
                "company_id": company.id,
                "picking_type_id": picking_type_id,
                "origin": self.name,
                "purchase_request_id": self.id,
                "order_line": [],
            }
            for l in lines:
                vals["order_line"].append((0, 0, {
                    "name": l.product_id.display_name,
                    "product_id": l.product_id.id,
                    "product_qty": l.qty_requested,
                    "product_uom": l.product_uom_id.id,
                    "price_unit": l.product_id.standard_price,
                    "date_planned": fields.Datetime.now(),
                }))
            po = po_model.create(vals)
            created_pos |= po
            self.env["purchase.request.line"].browse([line.id for line in lines])._mark_processed()
        return {
            "type": "ir.actions.act_window",
            "name": _("Órdenes de Compra"),
            "res_model": "purchase.order",
            "view_mode": "list,form",
            "domain": [("id", "in", created_pos.ids)],
        }

    def action_generate_transfers(self):
        self.ensure_one()
        self = self.with_company(self.company_id)
        self.line_ids._lock_for_processing()
        self._check_destination()
        lines = self.line_ids.filtered(
            lambda line: line.request_type == "transfer" and line.selected_for_action
            and line.qty_requested > 0 and not line.is_processed
        )
        if not lines:
            raise UserError(_(
                "Selecciona líneas de traslado pendientes con cantidad solicitada mayor a cero. "
                "Las líneas procesadas no pueden generar otro traslado."
            ))
        self._check_product_category()
        grouped = defaultdict(list)
        for line in lines:
            source = line.source_location_id
            destination = self.location_id
            if not source or not destination:
                raise UserError(_("Indica el origen de cada línea de traslado y el destino de la solicitud."))
            if source == destination:
                raise UserError(_("El origen y el destino del traslado deben ser diferentes."))
            locations = source | destination
            if locations - locations.filtered_domain(STOCK_LOCATION_DOMAIN):
                raise UserError(_("Los traslados requieren ubicaciones internas cuya ruta termine en /Stock."))
            if any(not location.active for location in locations):
                raise UserError(_("Las ubicaciones del traslado deben estar activas."))
            picking_type = source.warehouse_id.int_type_id
            if not picking_type:
                picking_type = self.env["stock.picking.type"].search([
                    ("code", "=", "internal"), ("company_id", "=", self.company_id.id),
                    ("default_location_src_id", "=", source.id),
                ], limit=1)
            if not picking_type or not picking_type.active or picking_type.company_id != self.company_id:
                raise UserError(_(
                    "Configura un tipo de operación interna activo para el almacén de origen de %s.",
                    source.display_name,
                ))
            grouped[(picking_type.id, source.id, destination.id)].append(line)

        created_pickings = self.env["stock.picking"]
        for (picking_type_id, source_loc_id, destination_loc_id), lines in grouped.items():
            picking_vals = {
                "picking_type_id": picking_type_id,
                "company_id": self.company_id.id,
                "location_id": source_loc_id,
                "location_dest_id": destination_loc_id,
                "origin": self.name,
                "purchase_request_id": self.id,
                "move_ids_without_package": [],
            }
            for l in lines:
                picking_vals["move_ids_without_package"].append((0, 0, {
                    "name": l.product_id.display_name,
                    "product_id": l.product_id.id,
                    "product_uom_qty": l.qty_requested,
                    "product_uom": l.product_uom_id.id,
                    "location_id": source_loc_id,
                    "location_dest_id": destination_loc_id,
                }))
            created_pickings |= self.env["stock.picking"].create(picking_vals)
            self.env["purchase.request.line"].browse([line.id for line in lines])._mark_processed()

        return {
            "type": "ir.actions.act_window",
            "name": _("Traslados"),
            "res_model": "stock.picking",
            "view_mode": "list,form",
            "domain": [("id", "in", created_pickings.ids)],
        }


class PurchaseRequestLine(models.Model):
    _name = "purchase.request.line"
    _description = "Línea de Solicitud"
    _check_company_auto = True

    request_id = fields.Many2one("purchase.request", required=True, ondelete="cascade")
    request_type = fields.Selection([
        ("purchase", "Compra"),
        ("transfer", "Traslado"),
    ], string="Tipo", default="purchase", required=True)
    company_id = fields.Many2one(related="request_id.company_id", store=True)
    category_id = fields.Many2one(related="request_id.category_id")
    allowed_category_ids = fields.Many2many(related="request_id.allowed_category_ids")
    product_id = fields.Many2one(
        "product.product", required=True, check_company=True,
        domain="[('categ_id', 'in', allowed_category_ids)]",
    )
    product_uom_id = fields.Many2one(
        "uom.uom", string="Unidad de medida", compute="_compute_product_uom_id",
        store=True, readonly=True,
        help="Unidad de compra para compras y unidad de venta del producto para traslados.",
    )
    qty_available_location = fields.Float(string="Existencia", compute="_compute_qty_available_location")
    qty_requested = fields.Float(string="Cantidad a solicitar", required=True, default=1.0)
    vendor_id = fields.Many2one(
        "res.partner", string="Proveedor", domain=[("supplier_rank", ">", 0)],
        check_company=True,
    )
    source_location_id = fields.Many2one(
        "stock.location", string="Ubicación origen",
        domain=STOCK_LOCATION_DOMAIN, check_company=True,
    )
    selected_for_action = fields.Boolean(string="Seleccionar")
    is_processed = fields.Boolean(
        string="Procesada", readonly=True, copy=False, default=False,
        help="La línea ya generó una compra o un traslado y no puede modificarse ni reutilizarse.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("is_processed"):
                raise UserError(_("El estado Procesada se asigna únicamente al generar documentos."))
            # Also override context defaults, including when duplicating a request.
            vals["is_processed"] = False
        return super().create(vals_list)

    def _lock_for_processing(self):
        """Serialize generation and edits; Odoo retries concurrent transactions."""
        if not self:
            return
        self.check_access("write")
        self.flush_recordset()
        self.env.cr.execute(
            "SELECT id FROM purchase_request_line WHERE id IN %s ORDER BY id FOR UPDATE",
            [tuple(self.ids)],
        )
        self.invalidate_recordset()

    def _mark_processed(self):
        # Private method: no RPC/context bypass can reset or set the marker.
        return super().write({"is_processed": True})

    def write(self, vals):
        if "is_processed" in vals:
            raise UserError(_("El estado Procesada no se puede modificar manualmente."))
        self._lock_for_processing()
        for line in self.filtered("is_processed"):
            for name, value in vals.items():
                field = self._fields[name]
                current = line[name].id if field.type == "many2one" else line[name]
                if current != value:
                    raise UserError(_(
                        "La línea de %(product)s ya generó una compra o un traslado. "
                        "No puedes modificarla ni cambiar su selección.",
                        product=line.product_id.display_name,
                    ))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_processed(self):
        self._lock_for_processing()
        if any(self.mapped("is_processed")):
            raise UserError(_("No puedes eliminar una línea que ya generó una compra o un traslado."))

    @api.depends("request_type", "product_id.uom_po_id", "product_id.uom_id")
    def _compute_product_uom_id(self):
        for line in self:
            if line.is_processed and line.product_uom_id:
                continue
            line.product_uom_id = (
                line.product_id.uom_po_id if line.request_type == "purchase" else line.product_id.uom_id
            )

    @api.constrains("request_type", "source_location_id")
    def _check_transfer_source(self):
        for line in self:
            if line.request_type == "transfer" and not line.source_location_id:
                raise ValidationError(_("La ubicación origen es obligatoria en las líneas de traslado."))

    @api.constrains("product_id", "request_id")
    def _check_product_category(self):
        self.request_id._check_product_category()

    @api.depends("product_id", "product_uom_id", "request_type", "source_location_id", "request_id.location_id")
    def _compute_qty_available_location(self):
        quant = self.env["stock.quant"]
        for line in self:
            location = line.source_location_id if line.request_type == "transfer" else line.request_id.location_id
            if line.product_id and location:
                quantity = sum(quant.search([
                    ("product_id", "=", line.product_id.id),
                    ("location_id", "child_of", location.id),
                ]).mapped("quantity"))
                line.qty_available_location = line.product_id.uom_id._compute_quantity(
                    quantity, line.product_uom_id, round=False,
                )
            else:
                line.qty_available_location = 0
