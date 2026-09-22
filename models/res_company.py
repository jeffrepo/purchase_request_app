from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = "res.company"

    purchase_request_ab_category_id = fields.Many2one(
        "product.category", string="Categoría de A&B",
        help="Categoría de A&B; incluye todas sus subcategorías.",
    )
    purchase_request_ab_picking_type_id = fields.Many2one(
        "stock.picking.type", string="Tipo de operación de A&B",
        domain="[('code', '=', 'incoming'), ('company_id', '=', id)]",
        help="Recepción que se utilizará al comprar productos de A&B.",
    )
    purchase_request_supplies_picking_type_id = fields.Many2one(
        "stock.picking.type", string="Tipo de operación de insumos",
        domain="[('code', '=', 'incoming'), ('company_id', '=', id)]",
        help="Recepción que se utilizará para productos fuera de la categoría de A&B.",
    )

    @api.constrains("purchase_request_ab_picking_type_id", "purchase_request_supplies_picking_type_id")
    def _check_purchase_request_picking_types(self):
        for company in self:
            picking_types = (
                company.purchase_request_ab_picking_type_id
                | company.purchase_request_supplies_picking_type_id
            )
            for picking_type in picking_types:
                if (picking_type.code != "incoming" or picking_type.company_id != company
                        or not picking_type.active
                        or picking_type.default_location_dest_id.usage != "internal"
                        or not picking_type.default_location_dest_id.active):
                    raise ValidationError(_(
                        "Selecciona una recepción activa de la misma compañía con "
                        "una ubicación destino interna activa para las solicitudes de compra."
                    ))
