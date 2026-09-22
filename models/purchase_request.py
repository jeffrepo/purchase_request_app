from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


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
    request_type = fields.Selection([
        ("purchase", "Compra"),
        ("transfer", "Traslado"),
    ], default="purchase", required=True, tracking=True)
    company_id = fields.Many2one(
        "res.company", string="Compañía", required=True,
        default=lambda self: self.env.company,
    )
    location_id = fields.Many2one(
        "stock.location", string="Ubicación destino", required=True,
        domain=STOCK_LOCATION_DOMAIN, check_company=True,
    )
    category_id = fields.Many2one(
        "product.category", string="Categoría de productos",
        help="Permite productos de esta categoría y de todas sus subcategorías.",
    )
    line_ids = fields.One2many("purchase.request.line", "request_id", string="Productos")
    state = fields.Selection([
        ("draft", "Borrador"),
        ("requested", "Solicitado"),
        ("confirmed", "Confirmado"),
        ("closed", "Cerrado"),
        ("cancelled", "Cancelado"),
    ], default="draft", tracking=True)
    purchase_order_ids = fields.One2many("purchase.order", "purchase_request_id")
    picking_ids = fields.One2many("stock.picking", "purchase_request_id")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
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

    @api.constrains("category_id", "line_ids")
    def _check_product_category(self):
        for request in self.filtered("category_id"):
            categories = self.env["product.category"].search([
                ("id", "child_of", request.category_id.id),
            ])
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
        for rec in self:
            if not rec.line_ids:
                raise UserError(_("Agrega al menos una línea."))
            rec.state = "requested"
            rec._notify_group(
                "purchase_request_app.group_operations_manager",
                _("Hay una solicitud pendiente por confirmar: %s") % rec.name,
            )

    def action_confirm(self):
        for rec in self:
            rec.state = "confirmed"
            rec._notify_group(
                "purchase_request_app.group_warehouse_lead",
                _("Solicitud confirmada (%s). Tipo: %s") % (rec.name, rec.request_type),
            )

    def action_close(self):
        self.write({"state": "closed"})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_reset_to_draft(self):
        self.write({"state": "draft"})

    def action_generate_purchase_orders(self):
        self.ensure_one()
        self = self.with_company(self.company_id)
        if self.request_type != "purchase":
            raise UserError(_("Solo aplica para solicitudes de tipo compra."))

        lines = self.line_ids.filtered(lambda l: l.selected_for_action and l.qty_requested > 0)
        if not lines:
            raise UserError(_("Selecciona líneas con cantidad solicitada."))
        if any(not line.vendor_id for line in lines):
            raise UserError(_("Indica un proveedor en cada línea seleccionada."))
        self._check_product_category()

        company = self.company_id
        ab_category = company.purchase_request_ab_category_id
        if not ab_category:
            raise UserError(_("Configura la categoría de A&B en Ajustes > Compras > Solicitudes de compra."))
        ab_categories = self.env["product.category"].search([("id", "child_of", ab_category.id)])

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
        if self.request_type != "transfer":
            raise UserError(_("Solo aplica para solicitudes de tipo traslado."))

        grouped = defaultdict(list)
        for line in self.line_ids.filtered(lambda l: l.selected_for_action and l.qty_requested > 0 and l.source_location_id):
            grouped[line.source_location_id.id].append(line)

        if not grouped:
            raise UserError(_("Selecciona líneas con ubicación origen y cantidad."))

        picking_type = self.env["stock.picking.type"].search([
            ("code", "=", "internal"), ("company_id", "=", self.company_id.id),
        ], limit=1)
        if not picking_type:
            raise UserError(_("No hay tipo de operación interna configurado."))

        created_pickings = self.env["stock.picking"]
        for source_loc_id, lines in grouped.items():
            picking_vals = {
                "picking_type_id": picking_type.id,
                "company_id": self.company_id.id,
                "location_id": source_loc_id,
                "location_dest_id": self.location_id.id,
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
                    "location_dest_id": self.location_id.id,
                }))
            created_pickings |= self.env["stock.picking"].create(picking_vals)

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
    company_id = fields.Many2one(related="request_id.company_id", store=True)
    category_id = fields.Many2one(related="request_id.category_id")
    product_id = fields.Many2one(
        "product.product", required=True, check_company=True,
        domain="[('categ_id', 'child_of', category_id)] if category_id else []",
    )
    product_uom_id = fields.Many2one(related="product_id.uom_po_id", store=True)
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

    @api.constrains("product_id", "request_id")
    def _check_product_category(self):
        self.request_id._check_product_category()

    @api.depends("product_id", "request_id.location_id")
    def _compute_qty_available_location(self):
        quant = self.env["stock.quant"]
        for line in self:
            if line.product_id and line.request_id.location_id:
                line.qty_available_location = sum(quant.search([
                    ("product_id", "=", line.product_id.id),
                    ("location_id", "child_of", line.request_id.location_id.id),
                ]).mapped("quantity"))
            else:
                line.qty_available_location = 0
