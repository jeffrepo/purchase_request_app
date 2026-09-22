from odoo.tools.sql import column_exists


def migrate(cr, version):
    if not column_exists(cr, "purchase_request", "request_type"):
        return
    cr.execute("ALTER TABLE purchase_request_line ADD COLUMN IF NOT EXISTS request_type varchar")
    cr.execute("""
        UPDATE purchase_request_line AS line
           SET request_type = COALESCE(request.request_type, 'purchase')
          FROM purchase_request AS request
         WHERE line.request_id = request.id
    """)
    # Remove the old NOT NULL column only after its values have been copied.
    cr.execute("ALTER TABLE purchase_request DROP COLUMN request_type")
