from odoo import fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    purchase_request_id = fields.Many2one("purchase.request", string="Solicitud de compra")
