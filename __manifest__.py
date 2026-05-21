{
    "name": "Solicitud de Compra Interna",
    "summary": "Gestión interna de solicitudes de compra o traslado",
    "version": "18.0.1.0.0",
    "author": "Mayan",
    "license": "LGPL-3",
    "depends": ["base", "stock", "purchase", "mail"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/mail_template.xml",
        "views/purchase_request_views.xml",
        "views/purchase_order_views.xml",
        "views/stock_picking_views.xml",
        "views/menu.xml"
    ],
    "application": True,
}
