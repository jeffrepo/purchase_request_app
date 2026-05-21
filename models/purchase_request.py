from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PurchaseRequest(models.Model):
    _name = "purchase.request"
    _description = "Solicitud de Compra"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default="/", copy=False, tracking=True, readonly=True)
    request_datetime = fields.Datetime(string="Fecha y hora", default=fields.Datetime.now, required=True)
    request_type = fields.Selection([
        ("purchase", "Compra"),
        ("transfer", "Traslado"),
    ], default="purchase", required=True, tracking=True)
    location_id = fields.Many2one("stock.location", string="Ubicación destino", required=True)
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
            if not vals.get("name") or vals.get("name") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("purchase.request") or "/"
        return super().create(vals_list)

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
        if self.request_type != "purchase":
            raise UserError(_("Solo aplica para solicitudes de tipo compra."))

        grouped = defaultdict(list)
        for line in self.line_ids.filtered(lambda l: l.selected_for_action and l.qty_requested > 0):
            grouped[line.vendor_id.id or False].append(line)

        if not grouped:
            raise UserError(_("Selecciona líneas con cantidad solicitada."))

        po_model = self.env["purchase.order"]
        created_pos = self.env["purchase.order"]
        for vendor_id, lines in grouped.items():
            vals = {
                "partner_id": vendor_id,
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
        if self.request_type != "transfer":
            raise UserError(_("Solo aplica para solicitudes de tipo traslado."))

        grouped = defaultdict(list)
        for line in self.line_ids.filtered(lambda l: l.selected_for_action and l.qty_requested > 0 and l.source_location_id):
            grouped[line.source_location_id.id].append(line)

        if not grouped:
            raise UserError(_("Selecciona líneas con ubicación origen y cantidad."))

        picking_type = self.env["stock.picking.type"].search([("code", "=", "internal")], limit=1)
        if not picking_type:
            raise UserError(_("No hay tipo de operación interna configurado."))

        created_pickings = self.env["stock.picking"]
        for source_loc_id, lines in grouped.items():
            picking_vals = {
                "picking_type_id": picking_type.id,
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

    request_id = fields.Many2one("purchase.request", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", required=True)
    product_uom_id = fields.Many2one(related="product_id.uom_po_id", store=True)
    qty_available_location = fields.Float(string="Existencia", compute="_compute_qty_available_location")
    qty_requested = fields.Float(string="Cantidad a solicitar", required=True, default=1.0)
    vendor_id = fields.Many2one("res.partner", string="Proveedor", domain=[("supplier_rank", ">", 0)])
    source_location_id = fields.Many2one("stock.location", string="Ubicación origen")
    selected_for_action = fields.Boolean(string="Seleccionar")

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
