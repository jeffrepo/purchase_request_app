from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # The original XML implicitly limited the sequence to the install company.
    # Keep its counter and format while making it available as a shared fallback.
    sequence = env.ref("purchase_request_app.seq_purchase_request")
    sequence.company_id = False
    env["ir.model.data"].search([
        ("module", "=", "purchase_request_app"), ("name", "=", "seq_purchase_request"),
    ]).noupdate = True
    # Existing requests predate company_id; their destination identifies it.
    cr.execute("""
        UPDATE purchase_request AS request
           SET company_id = location.company_id
          FROM stock_location AS location
         WHERE request.location_id = location.id
           AND location.company_id IS NOT NULL
           AND request.company_id IS DISTINCT FROM location.company_id
        RETURNING request.id
    """)
    requests = env["purchase.request"].browse([row[0] for row in cr.fetchall()])
    requests.invalidate_recordset(["company_id"])
    requests.modified(["company_id"])

    # Assign numbers to the old placeholders without touching valid references.
    unnamed = env["purchase.request"].search([
        "|", ("name", "in", ["/", "Nuevo", ""]), ("name", "=", False),
    ], order="id")
    for request in unnamed:
        request.with_context(tracking_disable=True).write({
            "name": request.with_company(request.company_id)._next_request_name(),
        })
