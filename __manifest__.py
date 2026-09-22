{
    "name": "Solicitud de Compra Interna",
    "summary": "Gestión interna de solicitudes de compra o traslado",
    "description": "Solicitudes internas con secuencia, categorías y recepción diferenciada para A&B e insumos.",
    "version": "18.0.1.2.1",
    "author": "Mayan",
    "license": "LGPL-3",
    "depends": ["base", "stock", "purchase_stock", "mail"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/mail_template.xml",
        "views/purchase_request_views.xml",
        "views/purchase_order_views.xml",
        "views/stock_picking_views.xml",
        "views/res_config_settings_views.xml",
        "views/menu.xml"
    ],
    "application": True,
}
