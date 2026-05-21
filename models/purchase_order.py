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
        for order in self.filtered("purchase_request_id"):
            request = order.purchase_request_id
            if request.request_type != "purchase" or request.state in ("closed", "cancelled"):
                continue
            all_products = request.line_ids.mapped("product_id")
            purchased_lines = request.purchase_order_ids.filtered(lambda p: p.state in ("purchase", "done")).mapped("order_line")
            purchased_products = purchased_lines.mapped("product_id")
            if all(p in purchased_products for p in all_products):
                request.state = "closed"
