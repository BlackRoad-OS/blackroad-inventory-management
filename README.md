# BlackRoad Inventory Management

![CI](https://github.com/BlackRoad-OS/blackroad-inventory-management/actions/workflows/ci.yml/badge.svg)

Production-quality Python inventory management system with SQLite persistence, barcode support, CSV import/export, transaction history, and a full CLI.

## Features

- **SQLite persistence** — zero-config, file-based storage
- **Barcode support** — EAN-13, EAN-8, UPC-A, CODE128, QR
- **CSV import/export** — bulk operations with error reporting
- **Transaction history** — full audit trail for every stock change
- **Low-stock alerts** — per-item reorder thresholds
- **Inventory valuation** — by category and location
- **CLI interface** — all operations via command line

## Installation

```bash
pip install -r requirements.txt
```

## CLI Usage

### Add an item
```bash
python -m src.inventory add WIDGET-001 "Blue Widget" \
  --qty 100 --price 9.99 --location SHELF-1 \
  --threshold 20 --category ELECTRONICS
```

### Update quantity (sale, purchase, adjustment)
```bash
python -m src.inventory update WIDGET-001 -10 --type SALE --ref "ORD-4521"
python -m src.inventory update WIDGET-001 50  --type PURCHASE --ref "PO-0099"
```

### Show low-stock items
```bash
python -m src.inventory low-stock
```

### Calculate inventory value
```bash
python -m src.inventory value
```

### Export to CSV
```bash
python -m src.inventory export inventory_export.csv
```

### Import from CSV
```bash
python -m src.inventory import items.csv
python -m src.inventory import items.csv --update   # overwrite existing SKUs
```

### Barcode lookup
```bash
python -m src.inventory barcode 1234567890123
```

### List items (with optional filters)
```bash
python -m src.inventory list
python -m src.inventory list --location SHELF-1
python -m src.inventory list --category ELECTRONICS --sort price
```

### Transaction history
```bash
python -m src.inventory history
python -m src.inventory history --sku WIDGET-001 --limit 50
```

### Reorder report
```bash
python -m src.inventory reorder
```

## Python API

```python
from src.inventory import InventoryManager, Item

mgr = InventoryManager(db_path="inventory.db")

# Add item
item = Item(
    sku="WIDGET-001",
    name="Blue Widget",
    quantity=100,
    price=9.99,
    location="SHELF-1",
    reorder_threshold=20,
    category="ELECTRONICS",
    barcode="1234567890123",
)
mgr.add_item(item)

# Update stock
mgr.update_quantity("WIDGET-001", -5, txn_type="SALE", reference="ORD-001")

# Check low stock
low = mgr.get_low_stock()

# Calculate value
report = mgr.calculate_value()
print(report["total_value"])

# Export / import
mgr.export_csv("backup.csv")
mgr.import_csv("new_items.csv", update_existing=False)

# Barcode lookup
item = mgr.barcode_lookup("1234567890123")

# Transaction history
history = mgr.get_transaction_history(sku="WIDGET-001", limit=20)
```

## SQLite Schema

### `items`
| Column | Type | Description |
|---|---|---|
| sku | TEXT PK | Stock-keeping unit (uppercase) |
| name | TEXT | Item display name |
| quantity | INTEGER | Current stock level |
| price | REAL | Unit price |
| location | TEXT | Storage zone |
| reorder_threshold | INTEGER | Low-stock trigger |
| category | TEXT | Item category |
| barcode | TEXT | Barcode string |
| unit | TEXT | Unit of measure (EACH, KG, etc.) |
| supplier | TEXT | Supplier name |
| notes | TEXT | Free-form notes |
| created_at | TEXT | ISO-8601 timestamp |
| updated_at | TEXT | ISO-8601 timestamp |

### `transactions`
| Column | Type | Description |
|---|---|---|
| id | TEXT PK | SHA-256 derived ID |
| sku | TEXT FK | References items.sku |
| transaction_type | TEXT | PURCHASE / SALE / ADJUSTMENT / TRANSFER / RETURN / SHRINKAGE / RECOUNT |
| quantity_delta | INTEGER | Change in quantity (signed) |
| quantity_before | INTEGER | Stock before transaction |
| quantity_after | INTEGER | Stock after transaction |
| timestamp | TEXT | ISO-8601 timestamp |
| reference | TEXT | External reference (PO, order ID) |
| notes | TEXT | Notes |
| user | TEXT | User who performed the action |

## Location Zones

`WAREHOUSE-A` · `WAREHOUSE-B` · `WAREHOUSE-C` · `SHELF-1` · `SHELF-2` · `COLD-STORAGE` · `LOADING-DOCK` · `RETURNS`

## Running Tests

```bash
pytest tests/ -v
```

## License

Proprietary — © BlackRoad OS, Inc. All rights reserved.
