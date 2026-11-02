def migrate(cr, version):
    # Old transfer quantities were expressed in the stored purchase UoM.
    # Convert before the new compute runs to preserve the physical quantity,
    # including requests that already have transfers in the old unit.
    cr.execute("""
        UPDATE purchase_request_line AS line
           SET qty_requested = line.qty_requested / old_uom.factor * sales_uom.factor,
               product_uom_id = sales_uom.id
          FROM product_product AS product
          JOIN product_template AS template ON template.id = product.product_tmpl_id
          JOIN uom_uom AS sales_uom ON sales_uom.id = template.uom_id,
               uom_uom AS old_uom
         WHERE line.product_id = product.id
           AND old_uom.id = COALESCE(line.product_uom_id, template.uom_po_id)
           AND line.request_type = 'transfer'
           AND old_uom.id != sales_uom.id
    """)
