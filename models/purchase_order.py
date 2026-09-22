from odoo import api, fields, models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    purchase_request_id = fields.Many2one("purchase.request", string="Solicitud de compra")

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders._try_close_request()
        return orders

    def button_confirm(self):
        res = super().button_confirm()
        self._try_close_request()
        return res

    def _try_close_request(self):
        self.purchase_request_id._try_close_request()
