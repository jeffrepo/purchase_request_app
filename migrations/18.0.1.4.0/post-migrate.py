import logging


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Older versions only linked document headers to requests. Match the
    # available evidence conservatively: indistinguishable lines must not be
    # offered for generation again. Cancelled documents also consumed a line.
    cr.execute("""
        UPDATE purchase_request_line AS line
           SET is_processed = TRUE
         WHERE NOT COALESCE(line.is_processed, FALSE)
           AND (
               (line.request_type = 'purchase' AND EXISTS (
                   SELECT 1
                     FROM purchase_order_line AS pol
                     JOIN purchase_order AS po ON po.id = pol.order_id
                    WHERE po.purchase_request_id = line.request_id
                      AND pol.product_id = line.product_id
                      AND po.partner_id = line.vendor_id
               ))
               OR (line.request_type = 'transfer' AND EXISTS (
                   SELECT 1
                     FROM stock_move AS move
                     JOIN stock_picking AS picking ON picking.id = move.picking_id
                     JOIN stock_picking_type AS operation ON operation.id = picking.picking_type_id
                    WHERE picking.purchase_request_id = line.request_id
                      AND operation.code = 'internal'
                      AND move.product_id = line.product_id
                      AND move.location_id = line.source_location_id
               ))
           )
    """)
    _logger.info("Locked %s existing request lines matching generated documents", cr.rowcount)
