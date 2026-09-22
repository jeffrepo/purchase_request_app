from pathlib import Path
import runpy

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestPurchaseRequest(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.po_double_validation = "one_step"
        cls.ab_warehouse = cls.env["stock.warehouse"].create({
            "name": "A&B", "code": "ABT", "company_id": cls.company.id,
        })
        cls.supplies_warehouse = cls.env["stock.warehouse"].create({
            "name": "Insumos", "code": "INST", "company_id": cls.company.id,
        })
        cls.root_category = cls.env["product.category"].create({"name": "Solicitud"})
        cls.ab_category = cls.env["product.category"].create({
            "name": "A&B", "parent_id": cls.root_category.id,
        })
        cls.ab_child = cls.env["product.category"].create({
            "name": "Bebidas", "parent_id": cls.ab_category.id,
        })
        cls.ab_grandchild = cls.env["product.category"].create({
            "name": "Jugos", "parent_id": cls.ab_child.id,
        })
        cls.supplies_category = cls.env["product.category"].create({
            "name": "Insumos", "parent_id": cls.root_category.id,
        })
        cls.ab_product = cls._product("Producto A&B", cls.ab_category)
        cls.ab_child_product = cls._product("Producto de subcategoría", cls.ab_child)
        cls.ab_grandchild_product = cls._product("Producto de categoría nieta", cls.ab_grandchild)
        cls.supplies_product = cls._product("Producto de insumos", cls.supplies_category)
        cls.vendor = cls.env["res.partner"].create({"name": "Proveedor", "supplier_rank": 1})
        cls.other_vendor = cls.env["res.partner"].create({"name": "Otro proveedor", "supplier_rank": 1})
        cls.company.write({
            "purchase_request_ab_category_id": cls.ab_category.id,
            "purchase_request_ab_picking_type_id": cls.ab_warehouse.in_type_id.id,
            "purchase_request_supplies_picking_type_id": cls.supplies_warehouse.in_type_id.id,
        })

    @classmethod
    def _product(cls, name, category):
        return cls.env["product.product"].create({
            "name": name, "categ_id": category.id, "type": "consu",
            "purchase_ok": True, "standard_price": 10,
        })

    def _line(self, product, **values):
        return Command.create({
            "product_id": product.id, "vendor_id": self.vendor.id,
            "qty_requested": 2, "selected_for_action": True, **values,
        })

    def _request(self, **values):
        return self.env["purchase.request"].create({
            "location_id": self.supplies_warehouse.lot_stock_id.id,
            "company_id": self.company.id, **values,
        })

    def test_sequence_omitted_placeholder_batch_and_copy(self):
        requests = self.env["purchase.request"].create([
            {"location_id": self.ab_warehouse.lot_stock_id.id, **values}
            for values in ({}, {"name": "/"}, {"name": False}, {"name": ""}, {"name": "Nuevo"})
        ])
        requests |= requests[0].copy()
        self.assertEqual(len(set(requests.mapped("name"))), 6)
        for request in requests:
            self.assertRegex(request.name, r"^SC\d{5,}$")
        self.assertEqual(self._request(name="LEGACY-123").name, "LEGACY-123")

    def test_missing_sequence_raises_instead_of_saving_placeholder(self):
        self.env["ir.sequence"].search([("code", "=", "purchase.request")]).active = False
        with self.assertRaisesRegex(UserError, "secuencia activa"):
            self._request()

    def test_form_creates_number_and_filters_descendant_products(self):
        with Form(self.env["purchase.request"]) as form:
            form.location_id = self.ab_warehouse.lot_stock_id
            form.category_id = self.ab_category
            with form.line_ids.new() as line:
                line.product_id = self.ab_grandchild_product
        self.assertRegex(form.record.name, r"^SC\d{5,}$")
        line = form.record.line_ids
        domain = safe_eval(line._fields["product_id"].domain, {"category_id": line.category_id.id})
        products = self.env["product.product"].search(domain)
        self.assertIn(self.ab_product, products)
        self.assertIn(self.ab_child_product, products)
        self.assertIn(self.ab_grandchild_product, products)
        self.assertNotIn(self.supplies_product, products)

    def test_location_domains_exclude_parents_and_other_internal_locations(self):
        shelf = self.env["stock.location"].create({
            "name": "Estante", "usage": "internal",
            "location_id": self.ab_warehouse.lot_stock_id.id,
        })
        self.ab_warehouse.lot_stock_id.name = "stock"
        for model, field in (
            ("purchase.request", "location_id"),
            ("purchase.request.line", "source_location_id"),
        ):
            domain = self.env[model]._fields[field].domain
            locations = self.env["stock.location"].search(domain)
            self.assertIn(self.ab_warehouse.lot_stock_id, locations)
            self.assertIn(self.supplies_warehouse.lot_stock_id, locations)
            self.assertNotIn(self.ab_warehouse.view_location_id, locations)
            self.assertNotIn(shelf, locations)
        self.assertEqual(self.ab_warehouse.lot_stock_id.display_name, "ABT/stock")

    def test_category_rejects_invalid_product_and_category_changes(self):
        request = self._request(category_id=self.ab_category.id, line_ids=[self._line(self.ab_child_product)])
        with self.assertRaises(ValidationError), self.cr.savepoint():
            request.line_ids.product_id = self.supplies_product
        with self.assertRaises(ValidationError), self.cr.savepoint():
            request.category_id = self.supplies_category
        with self.assertRaises(ValidationError), self.cr.savepoint():
            request.write({"line_ids": [self._line(self.supplies_product)]})

    def test_mixed_order_routes_parent_and_descendants_and_receipts(self):
        request = self._request(category_id=self.root_category.id, line_ids=[
            self._line(self.ab_product), self._line(self.ab_child_product),
            self._line(self.ab_grandchild_product), self._line(self.supplies_product),
        ])
        action = request.action_generate_purchase_orders()
        orders = self.env["purchase.order"].search(action["domain"])
        self.assertEqual(len(orders), 2)
        ab_order = orders.filtered(lambda order: order.picking_type_id == self.ab_warehouse.in_type_id)
        supplies_order = orders - ab_order
        self.assertEqual(ab_order.order_line.product_id, self.ab_product | self.ab_child_product | self.ab_grandchild_product)
        self.assertEqual(supplies_order.order_line.product_id, self.supplies_product)
        self.assertEqual(supplies_order.picking_type_id, self.supplies_warehouse.in_type_id)
        self.assertEqual(orders.purchase_request_id, request)
        for order in orders:
            self.assertEqual(order.origin, request.name)
            order.button_confirm()
            self.assertEqual(order.picking_ids.location_dest_id, order.picking_type_id.default_location_dest_id)
            self.assertEqual(order.picking_ids.move_ids.product_id, order.order_line.product_id)

    def test_selected_positive_lines_group_by_vendor_and_operation(self):
        request = self._request(line_ids=[
            self._line(self.ab_product),
            self._line(self.ab_child_product, vendor_id=self.other_vendor.id),
            self._line(self.supplies_product),
            self._line(self.supplies_product, selected_for_action=False),
            self._line(self.supplies_product, qty_requested=0),
            self._line(self.supplies_product, qty_requested=-1),
        ])
        request.action_generate_purchase_orders()
        self.assertEqual(len(request.purchase_order_ids), 3)
        self.assertEqual(len(request.purchase_order_ids.order_line), 3)
        self.assertEqual(sum(request.purchase_order_ids.order_line.mapped("product_qty")), 6)

    def test_missing_configuration_and_vendor_create_no_orders(self):
        request = self._request(line_ids=[self._line(self.ab_product), self._line(self.supplies_product)])
        for field in ("purchase_request_ab_category_id", "purchase_request_ab_picking_type_id", "purchase_request_supplies_picking_type_id"):
            value = self.company[field]
            self.company[field] = False
            with self.assertRaisesRegex(UserError, "Configura"):
                request.action_generate_purchase_orders()
            self.assertFalse(request.purchase_order_ids)
            self.company[field] = value
        request.line_ids[0].vendor_id = False
        with self.assertRaisesRegex(UserError, "proveedor"):
            request.action_generate_purchase_orders()
        self.assertFalse(request.purchase_order_ids)

    def test_only_selected_route_requires_configuration(self):
        self.company.purchase_request_supplies_picking_type_id = False
        request = self._request(line_ids=[self._line(self.ab_product)])
        request.action_generate_purchase_orders()
        self.assertEqual(request.purchase_order_ids.picking_type_id, self.ab_warehouse.in_type_id)

    def test_settings_save_on_company_and_reject_invalid_operations(self):
        settings = self.env["res.config.settings"].create({"company_id": self.company.id})
        self.assertEqual(settings.purchase_request_ab_category_id, self.ab_category)
        settings.purchase_request_ab_picking_type_id = self.supplies_warehouse.in_type_id
        self.assertEqual(self.company.purchase_request_ab_picking_type_id, self.supplies_warehouse.in_type_id)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            settings.purchase_request_ab_picking_type_id = self.ab_warehouse.out_type_id

    def test_archived_operation_cannot_silently_fall_back(self):
        request = self._request(line_ids=[self._line(self.ab_product)])
        self.ab_warehouse.in_type_id.active = False
        with self.assertRaisesRegex(UserError, "recepción activa"):
            request.action_generate_purchase_orders()
        self.assertFalse(request.purchase_order_ids)

    def test_routing_uses_request_company_not_active_company(self):
        other_company = self.env["res.company"].create({"name": "Otra compañía"})
        other_warehouse = self.env["stock.warehouse"].search([
            ("company_id", "=", other_company.id),
        ], limit=1)
        other_company.write({
            "purchase_request_ab_category_id": self.ab_category.id,
            "purchase_request_ab_picking_type_id": other_warehouse.in_type_id.id,
            "purchase_request_supplies_picking_type_id": other_warehouse.in_type_id.id,
        })
        self.ab_product.with_company(other_company).standard_price = 25
        with self.assertRaises(ValidationError), self.cr.savepoint():
            other_company.purchase_request_ab_picking_type_id = self.ab_warehouse.in_type_id
        request = self._request(
            company_id=other_company.id,
            location_id=other_warehouse.lot_stock_id.id,
            line_ids=[self._line(self.ab_product)],
        )
        self.assertEqual(request.env.company, self.company)
        request.action_generate_purchase_orders()
        self.assertEqual(request.purchase_order_ids.company_id, other_company)
        self.assertEqual(request.purchase_order_ids.picking_type_id, other_warehouse.in_type_id)
        self.assertEqual(request.purchase_order_ids.order_line.price_unit, 25)

        other_destination = self.env["stock.warehouse"].create({
            "name": "Otro destino", "code": "OT2", "company_id": other_company.id,
        }).lot_stock_id
        transfer = self._request(
            company_id=other_company.id, location_id=other_destination.id,
            line_ids=[self._line(
                self.ab_product, request_type="transfer", source_location_id=other_warehouse.lot_stock_id.id,
            )],
        )
        transfer.action_generate_transfers()
        self.assertEqual(transfer.picking_ids.company_id, other_company)
        self.assertEqual(transfer.picking_ids.picking_type_id.company_id, other_company)

    def test_transfer_keeps_source_and_destination(self):
        request = self._request(line_ids=[self._line(
            self.ab_product, request_type="transfer", source_location_id=self.ab_warehouse.lot_stock_id.id,
        )])
        request.action_generate_transfers()
        self.assertEqual(request.picking_ids.location_id, self.ab_warehouse.lot_stock_id)
        self.assertEqual(request.picking_ids.location_dest_id, self.supplies_warehouse.lot_stock_id)
        self.assertEqual(request.picking_ids.picking_type_id, self.ab_warehouse.int_type_id)

    def test_mixed_request_generates_and_displays_each_operation(self):
        request = self._request(state="confirmed", line_ids=[
            self._line(self.ab_product),
            self._line(self.supplies_product, request_type="transfer", vendor_id=False,
                       source_location_id=self.ab_warehouse.lot_stock_id.id),
        ])
        self.assertNotIn("request_type", request._fields)
        request.action_generate_purchase_orders()
        request.action_generate_transfers()
        self.assertEqual(request.purchase_order_ids.order_line.product_id, self.ab_product)
        self.assertEqual(request.picking_ids.move_ids.product_id, self.supplies_product)
        self.assertEqual(request.purchase_order_ids.purchase_request_id, request)
        self.assertEqual(request.picking_ids.purchase_request_id, request)
        # Both relations are available directly on the request form.
        view = self.env.ref("purchase_request_app.view_purchase_request_form").arch_db
        self.assertIn('name="purchase_order_ids"', view)
        self.assertIn('name="picking_ids"', view)
        request.purchase_order_ids.button_confirm()
        self.assertEqual(request.state, "confirmed")
        picking = request.picking_ids
        picking.action_confirm()
        picking.move_ids.quantity = 2
        picking.move_ids.picked = True
        picking._action_done()
        self.assertEqual(request.state, "closed")

    def test_transfer_grouping_respects_each_source_and_shared_destination(self):
        third = self.env["stock.warehouse"].create({"name": "Tercer almacén", "code": "THR"})
        request = self._request(line_ids=[
            self._line(self.ab_product, request_type="transfer", source_location_id=self.ab_warehouse.lot_stock_id.id),
            self._line(self.ab_child_product, request_type="transfer", source_location_id=self.ab_warehouse.lot_stock_id.id),
            self._line(self.ab_product, request_type="transfer", source_location_id=third.lot_stock_id.id),
            self._line(self.ab_product, request_type="transfer", source_location_id=third.lot_stock_id.id),
            self._line(self.ab_product, request_type="transfer", selected_for_action=False,
                       source_location_id=self.ab_warehouse.lot_stock_id.id),
            self._line(self.ab_product, request_type="transfer", qty_requested=0,
                       source_location_id=self.ab_warehouse.lot_stock_id.id),
            self._line(self.supplies_product),
        ])
        request.action_generate_transfers()
        self.assertEqual(len(request.picking_ids), 2)
        self.assertEqual(len(request.picking_ids.move_ids), 4)
        for picking in request.picking_ids:
            self.assertEqual(picking.move_ids.location_id, picking.location_id)
            self.assertEqual(picking.move_ids.location_dest_id, picking.location_dest_id)
            self.assertEqual(picking.location_dest_id, request.location_id)
            self.assertEqual(picking.picking_type_id, picking.location_id.warehouse_id.int_type_id)
        self.assertFalse(request.purchase_order_ids)

    def test_transfer_requires_source_and_rejects_invalid_routes(self):
        request = self._request(line_ids=[
            self._line(self.ab_product, request_type="transfer", source_location_id=self.ab_warehouse.lot_stock_id.id),
        ])
        with self.assertRaisesRegex(ValidationError, "origen es obligatoria"), self.cr.savepoint():
            request.write({"line_ids": [self._line(self.supplies_product, request_type="transfer")]})
        line = request.line_ids[-1]
        with self.assertRaisesRegex(ValidationError, "origen es obligatoria"), self.cr.savepoint():
            line.source_location_id = False
        line.source_location_id = request.location_id
        with self.assertRaisesRegex(UserError, "diferentes"):
            request.action_generate_transfers()
        line.source_location_id = self.ab_warehouse.view_location_id
        with self.assertRaisesRegex(UserError, "/Stock"):
            request.action_generate_transfers()
        self.assertFalse(request.picking_ids)

    def test_each_button_requires_selected_lines_of_its_own_type(self):
        request = self._request(line_ids=[self._line(self.ab_product)])
        with self.assertRaisesRegex(UserError, "líneas de traslado"):
            request.action_generate_transfers()
        request.line_ids.write({
            "request_type": "transfer", "source_location_id": self.ab_warehouse.lot_stock_id.id,
        })
        with self.assertRaisesRegex(UserError, "líneas de compra"):
            request.action_generate_purchase_orders()

    def test_mixed_form_keeps_destination_on_header_and_stock_uses_source(self):
        self.ab_product.is_storable = True
        self.env["stock.quant"]._update_available_quantity(self.ab_product, self.ab_warehouse.lot_stock_id, 9)
        self.env["stock.quant"]._update_available_quantity(self.ab_product, self.supplies_warehouse.lot_stock_id, 4)
        with Form(self.env["purchase.request"]) as form:
            form.location_id = self.supplies_warehouse.lot_stock_id
            with form.line_ids.new() as line:
                line.request_type = "transfer"
                line.product_id = self.ab_product
                line.source_location_id = self.ab_warehouse.lot_stock_id
                self.assertEqual(line.qty_available_location, 9)
            with form.line_ids.new() as line:
                line.product_id = self.ab_product
                self.assertEqual(line.qty_available_location, 4)
        self.assertEqual(form.record.line_ids.mapped("request_type"), ["transfer", "purchase"])
        self.assertEqual(form.record.location_id, self.supplies_warehouse.lot_stock_id)
        self.assertNotIn("location_id", form.record.line_ids._fields)

    def test_same_product_purchase_does_not_fulfil_transfer_or_duplicate_lines(self):
        request = self._request(state="confirmed", line_ids=[
            self._line(self.ab_product),
            self._line(self.ab_product, selected_for_action=False),
            self._line(self.ab_product, request_type="transfer", source_location_id=self.ab_warehouse.lot_stock_id.id),
        ])
        request.action_generate_purchase_orders()
        request.purchase_order_ids.button_confirm()
        self.assertEqual(request.state, "confirmed")
        request.action_generate_transfers()
        picking = request.picking_ids
        picking.action_confirm()
        picking.move_ids.quantity = 2
        picking.move_ids.picked = True
        picking._action_done()
        self.assertEqual(request.state, "confirmed")
        request.line_ids.selected_for_action = False
        request.line_ids[1].selected_for_action = True
        request.action_generate_purchase_orders()
        request.purchase_order_ids.filtered(lambda order: order.state == "draft").button_confirm()
        self.assertEqual(request.state, "closed")

    def test_partial_transfer_only_closes_after_backorder(self):
        request = self._request(state="confirmed", line_ids=[self._line(
            self.ab_product, request_type="transfer", source_location_id=self.ab_warehouse.lot_stock_id.id,
        )])
        request.action_generate_transfers()
        picking = request.picking_ids
        picking.action_confirm()
        picking.move_ids.quantity = 1
        picking.move_ids.picked = True
        picking._action_done()
        self.assertEqual(request.state, "confirmed")
        backorder = request.picking_ids - picking
        self.assertEqual(len(backorder), 1)
        backorder.move_ids.quantity = 1
        backorder.move_ids.picked = True
        backorder._action_done()
        self.assertEqual(request.state, "closed")

    def test_migration_numbers_existing_placeholders_once(self):
        unnamed = self._request()
        unnamed.name = "/"
        named = self._request(name="LEGACY-456")
        sequence = self.env.ref("purchase_request_app.seq_purchase_request")
        sequence.company_id = self.company
        sequence_ref = self.env["ir.model.data"].search([
            ("module", "=", "purchase_request_app"), ("name", "=", "seq_purchase_request"),
        ])
        sequence_ref.noupdate = False
        migration = Path(__file__).parents[1] / "migrations/18.0.1.1.0/post-migrate.py"
        migrate = runpy.run_path(str(migration))["migrate"]
        migrate(self.cr, "18.0.1.0.0")
        self.assertRegex(unnamed.name, r"^SC\d{5,}$")
        number = unnamed.name
        migrate(self.cr, "18.0.1.0.0")
        self.assertEqual(unnamed.name, number)
        self.assertEqual(named.name, "LEGACY-456")
        self.assertFalse(sequence.company_id)
        self.assertTrue(sequence_ref.noupdate)

    def test_migration_moves_legacy_header_type_to_lines(self):
        purchase = self._request(line_ids=[self._line(self.supplies_product)])
        transfer = self._request(line_ids=[self._line(
            self.ab_product, source_location_id=self.ab_warehouse.lot_stock_id.id,
        )])
        self.env.flush_all()
        self.cr.execute("ALTER TABLE purchase_request ADD COLUMN request_type varchar NOT NULL DEFAULT 'purchase'")
        self.cr.execute("UPDATE purchase_request SET request_type = 'transfer' WHERE id = %s", [transfer.id])
        migration = Path(__file__).parents[1] / "migrations/18.0.1.2.0/pre-migrate.py"
        migrate = runpy.run_path(str(migration))["migrate"]
        migrate(self.cr, "18.0.1.1.0")
        (purchase | transfer).line_ids.invalidate_recordset(["request_type"])
        self.assertEqual(purchase.line_ids.request_type, "purchase")
        self.assertEqual(transfer.line_ids.request_type, "transfer")
        self.assertEqual(transfer.line_ids.source_location_id, self.ab_warehouse.lot_stock_id)
        self.assertEqual(transfer.location_id, self.supplies_warehouse.lot_stock_id)
        migrate(self.cr, "18.0.1.1.0")  # Re-running cannot overwrite line choices.
