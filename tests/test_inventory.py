import pytest
import csv
import os
from src.inventory import InventoryManager, Item, Transaction


def make_mgr(tmp_path):
    return InventoryManager(db_path=str(tmp_path / "test.db"))


def test_add_and_get_item(tmp_path):
    mgr = make_mgr(tmp_path)
    item = Item(sku="WIDGET-001", name="Blue Widget", quantity=100, price=9.99,
                location="SHELF-1", reorder_threshold=20)
    mgr.add_item(item)
    fetched = mgr.get_item("WIDGET-001")
    assert fetched is not None
    assert fetched.name == "Blue Widget"
    assert fetched.quantity == 100


def test_update_quantity_positive(tmp_path):
    mgr = make_mgr(tmp_path)
    item = Item(sku="GADGET-001", name="Gadget", quantity=50, price=5.0,
                location="WAREHOUSE-A", reorder_threshold=10)
    mgr.add_item(item)
    updated = mgr.update_quantity("GADGET-001", 25, txn_type="PURCHASE")
    assert updated.quantity == 75


def test_update_quantity_negative(tmp_path):
    mgr = make_mgr(tmp_path)
    item = Item(sku="TOOL-001", name="Tool", quantity=30, price=15.0,
                location="WAREHOUSE-B", reorder_threshold=5)
    mgr.add_item(item)
    updated = mgr.update_quantity("TOOL-001", -10, txn_type="SALE")
    assert updated.quantity == 20


def test_update_quantity_insufficient_raises(tmp_path):
    mgr = make_mgr(tmp_path)
    item = Item(sku="RARE-001", name="Rare Item", quantity=5, price=100.0,
                location="WAREHOUSE-A", reorder_threshold=1)
    mgr.add_item(item)
    with pytest.raises(ValueError):
        mgr.update_quantity("RARE-001", -10)


def test_get_low_stock(tmp_path):
    mgr = make_mgr(tmp_path)
    item1 = Item(sku="A001", name="A", quantity=5, price=1.0, location="W-A", reorder_threshold=10)
    item2 = Item(sku="B001", name="B", quantity=100, price=1.0, location="W-A", reorder_threshold=10)
    mgr.add_item(item1)
    mgr.add_item(item2)
    low = mgr.get_low_stock()
    skus = [i.sku for i in low]
    assert "A001" in skus
    assert "B001" not in skus


def test_calculate_value(tmp_path):
    mgr = make_mgr(tmp_path)
    mgr.add_item(Item(sku="V001", name="V1", quantity=10, price=5.0,
                      location="W-A", reorder_threshold=2))
    mgr.add_item(Item(sku="V002", name="V2", quantity=4, price=10.0,
                      location="W-A", reorder_threshold=2))
    val = mgr.calculate_value()
    assert val["total_value"] == pytest.approx(90.0)
    assert val["item_count"] == 2


def test_export_import_csv(tmp_path):
    mgr = make_mgr(tmp_path)
    mgr.add_item(Item(sku="CSV001", name="CSV Item", quantity=50, price=3.0,
                      location="W-A", reorder_threshold=5))
    csv_path = str(tmp_path / "export.csv")
    n = mgr.export_csv(csv_path)
    assert n == 1
    mgr2 = InventoryManager(db_path=str(tmp_path / "test2.db"))
    result = mgr2.import_csv(csv_path)
    assert result["added"] == 1
    assert result["skipped"] == 0


def test_barcode_lookup(tmp_path):
    mgr = make_mgr(tmp_path)
    mgr.add_item(Item(sku="BC001", name="Barcode Item", quantity=10, price=2.0,
                      location="W-A", reorder_threshold=3, barcode="1234567890123"))
    found = mgr.barcode_lookup("1234567890123")
    assert found is not None
    assert found.sku == "BC001"


def test_transaction_history(tmp_path):
    mgr = make_mgr(tmp_path)
    mgr.add_item(Item(sku="H001", name="Hist Item", quantity=20, price=1.0,
                      location="W-A", reorder_threshold=5))
    mgr.update_quantity("H001", 10, txn_type="PURCHASE")
    mgr.update_quantity("H001", -5, txn_type="SALE")
    history = mgr.get_transaction_history(sku="H001")
    assert len(history) >= 2


def test_duplicate_sku_raises(tmp_path):
    mgr = make_mgr(tmp_path)
    item = Item(sku="DUP-001", name="Dup", quantity=10, price=1.0,
                location="W-A", reorder_threshold=2)
    mgr.add_item(item)
    with pytest.raises(ValueError, match="already exists"):
        mgr.add_item(Item(sku="DUP-001", name="Dup2", quantity=5, price=2.0,
                          location="W-A", reorder_threshold=2))


def test_negative_quantity_raises():
    with pytest.raises(ValueError):
        Item(sku="BAD-001", name="Bad", quantity=-1, price=1.0,
             location="W-A", reorder_threshold=0)


def test_list_items_filtered(tmp_path):
    mgr = make_mgr(tmp_path)
    mgr.add_item(Item(sku="L001", name="L1", quantity=10, price=1.0,
                      location="SHELF-1", reorder_threshold=2, category="ELECTRONICS"))
    mgr.add_item(Item(sku="L002", name="L2", quantity=20, price=2.0,
                      location="WAREHOUSE-A", reorder_threshold=5, category="TOOLS"))
    by_loc = mgr.list_items(location="SHELF-1")
    assert len(by_loc) == 1
    assert by_loc[0].sku == "L001"
    by_cat = mgr.list_items(category="TOOLS")
    assert len(by_cat) == 1
    assert by_cat[0].sku == "L002"


def test_reorder_report(tmp_path):
    mgr = make_mgr(tmp_path)
    mgr.add_item(Item(sku="R001", name="Reorder Me", quantity=2, price=5.0,
                      location="W-A", reorder_threshold=10))
    report = mgr.get_reorder_report()
    assert "R001" in report
    assert "REORDER REPORT" in report
