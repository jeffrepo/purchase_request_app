from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    purchase_request_ab_category_id = fields.Many2one(
        related="company_id.purchase_request_ab_category_id", readonly=False,
    )
    purchase_request_ab_picking_type_id = fields.Many2one(
        related="company_id.purchase_request_ab_picking_type_id", readonly=False,
        domain="[('code', '=', 'incoming'), ('company_id', '=', company_id)]",
    )
    purchase_request_supplies_picking_type_id = fields.Many2one(
        related="company_id.purchase_request_supplies_picking_type_id", readonly=False,
        domain="[('code', '=', 'incoming'), ('company_id', '=', company_id)]",
    )
