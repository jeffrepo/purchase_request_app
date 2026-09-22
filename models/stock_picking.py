from odoo import fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    purchase_request_id = fields.Many2one("purchase.request", string="Solicitud de compra")

    def _action_done(self):
        result = super()._action_done()
        self.purchase_request_id._try_close_request()
        return result
