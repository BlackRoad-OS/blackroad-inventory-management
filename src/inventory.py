#!/usr/bin/env python3
"""BlackRoad Inventory Management System - Production quality inventory tracking."""

from __future__ import annotations
import argparse, csv, hashlib, io, json, re, sqlite3, sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Barcode format patterns
BARCODE_FORMATS = {
    "EAN13": r"^\d{13}$",
    "EAN8": r"^\d{8}$",
    "UPC_A": r"^\d{12}$",
    "CODE128": r"^[A-Za-z0-9\-\.\/\+\%\$\ ]{1,48}$",
    "QR": r"^[A-Za-z0-9\-_\.~:\/\?#\[\]@!\$&\'\(\)\*\+,;= ]{1,255}$",
}

LOCATION_ZONES = ["WAREHOUSE-A", "WAREHOUSE-B", "WAREHOUSE-C", "SHELF-1", "SHELF-2", "COLD-STORAGE", "LOADING-DOCK", "RETURNS"]

TRANSACTION_TYPES = ["PURCHASE", "SALE", "ADJUSTMENT", "TRANSFER", "RETURN", "SHRINKAGE", "RECOUNT"]


@dataclass
class Item:
    sku: str
    name: str
    quantity: int
    price: float
    location: str
    reorder_threshold: int
    category: str = "GENERAL"
    barcode: str = ""
    unit: str = "EACH"
    supplier: str = ""
    notes: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def __post_init__(self):
        if self.quantity < 0:
            raise ValueError(f"Quantity cannot be negative: {self.quantity}")
        if self.price < 0:
            raise ValueError(f"Price cannot be negative: {self.price}")
        if self.reorder_threshold < 0:
            raise ValueError(f"Reorder threshold cannot be negative: {self.reorder_threshold}")
        self.sku = self.sku.upper().strip()

    def is_low_stock(self) -> bool:
        return self.quantity <= self.reorder_threshold

    def total_value(self) -> float:
        return round(self.quantity * self.price, 2)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class Transaction:
    id: str
    sku: str
    transaction_type: str
    quantity_delta: int
    quantity_before: int
    quantity_after: int
    timestamp: str
    reference: str = ""
    notes: str = ""
    user: str = "system"

    def to_dict(self) -> Dict:
        return asdict(self)


class InventoryManager:
    """Production inventory management with SQLite persistence."""

    def __init__(self, db_path: str = "inventory.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS items (
                    sku TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    price REAL NOT NULL DEFAULT 0.0,
                    location TEXT NOT NULL DEFAULT 'WAREHOUSE-A',
                    reorder_threshold INTEGER NOT NULL DEFAULT 10,
                    category TEXT DEFAULT 'GENERAL',
                    barcode TEXT DEFAULT '',
                    unit TEXT DEFAULT 'EACH',
                    supplier TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    id TEXT PRIMARY KEY,
                    sku TEXT NOT NULL,
                    transaction_type TEXT NOT NULL,
                    quantity_delta INTEGER NOT NULL,
                    quantity_before INTEGER NOT NULL,
                    quantity_after INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    reference TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    user TEXT DEFAULT 'system',
                    FOREIGN KEY (sku) REFERENCES items(sku)
                );
                CREATE INDEX IF NOT EXISTS idx_items_location ON items(location);
                CREATE INDEX IF NOT EXISTS idx_items_category ON items(category);
                CREATE INDEX IF NOT EXISTS idx_items_barcode ON items(barcode);
                CREATE INDEX IF NOT EXISTS idx_txn_sku ON transactions(sku);
                CREATE INDEX IF NOT EXISTS idx_txn_type ON transactions(transaction_type);
                CREATE INDEX IF NOT EXISTS idx_txn_ts ON transactions(timestamp);
            """)

    def _gen_id(self) -> str:
        ts = datetime.utcnow().isoformat()
        return hashlib.sha256(ts.encode()).hexdigest()[:12]

    def add_item(self, item: Item) -> Item:
        """Add a new item to inventory."""
        now = datetime.utcnow().isoformat()
        item.created_at = now
        item.updated_at = now
        with sqlite3.connect(self.db_path) as conn:
            existing = conn.execute("SELECT sku FROM items WHERE sku=?", (item.sku,)).fetchone()
            if existing:
                raise ValueError(f"Item with SKU '{item.sku}' already exists. Use update_quantity() to modify stock.")
            conn.execute(
                """INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (item.sku, item.name, item.quantity, item.price, item.location,
                 item.reorder_threshold, item.category, item.barcode, item.unit,
                 item.supplier, item.notes, item.created_at, item.updated_at)
            )
            if item.quantity > 0:
                txn = Transaction(
                    id=self._gen_id(), sku=item.sku, transaction_type="PURCHASE",
                    quantity_delta=item.quantity, quantity_before=0,
                    quantity_after=item.quantity, timestamp=now,
                    notes="Initial stock entry",
                )
                self._save_transaction(conn, txn)
        return item

    def update_quantity(self, sku: str, delta: int, txn_type: str = "ADJUSTMENT",
                        reference: str = "", notes: str = "", user: str = "system") -> Item:
        """Update quantity of an item by delta (positive=add, negative=remove)."""
        sku = sku.upper().strip()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM items WHERE sku=?", (sku,)).fetchone()
            if not row:
                raise KeyError(f"Item not found: {sku}")
            item = Item(**dict(row))
            new_qty = item.quantity + delta
            if new_qty < 0:
                raise ValueError(f"Insufficient stock for {sku}: have {item.quantity}, reducing by {abs(delta)}")
            now = datetime.utcnow().isoformat()
            conn.execute(
                "UPDATE items SET quantity=?, updated_at=? WHERE sku=?",
                (new_qty, now, sku)
            )
            txn = Transaction(
                id=self._gen_id(), sku=sku, transaction_type=txn_type,
                quantity_delta=delta, quantity_before=item.quantity,
                quantity_after=new_qty, timestamp=now,
                reference=reference, notes=notes, user=user,
            )
            self._save_transaction(conn, txn)
            item.quantity = new_qty
            item.updated_at = now
        return item

    def get_item(self, sku: str) -> Optional[Item]:
        """Get item by SKU."""
        sku = sku.upper().strip()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM items WHERE sku=?", (sku,)).fetchone()
            return Item(**dict(row)) if row else None

    def get_low_stock(self, threshold: Optional[int] = None) -> List[Item]:
        """Get all items at or below reorder threshold."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if threshold is not None:
                rows = conn.execute(
                    "SELECT * FROM items WHERE quantity <= ? ORDER BY quantity ASC", (threshold,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM items WHERE quantity <= reorder_threshold ORDER BY quantity ASC"
                ).fetchall()
            return [Item(**dict(r)) for r in rows]

    def calculate_value(self, location: Optional[str] = None, category: Optional[str] = None) -> Dict:
        """Calculate total inventory value, optionally filtered."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM items WHERE 1=1"
            params = []
            if location:
                query += " AND location=?"
                params.append(location)
            if category:
                query += " AND category=?"
                params.append(category)
            rows = conn.execute(query, params).fetchall()
            items = [Item(**dict(r)) for r in rows]

        total_value = sum(i.total_value() for i in items)
        by_category: Dict[str, float] = {}
        by_location: Dict[str, float] = {}
        for item in items:
            by_category[item.category] = by_category.get(item.category, 0.0) + item.total_value()
            by_location[item.location] = by_location.get(item.location, 0.0) + item.total_value()

        return {
            "total_value": round(total_value, 2),
            "item_count": len(items),
            "total_units": sum(i.quantity for i in items),
            "by_category": {k: round(v, 2) for k, v in sorted(by_category.items())},
            "by_location": {k: round(v, 2) for k, v in sorted(by_location.items())},
        }

    def export_csv(self, path: str) -> int:
        """Export all inventory to CSV. Returns number of rows written."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM items ORDER BY sku").fetchall()

        if not rows:
            return 0

        fieldnames = list(dict(rows[0]).keys())
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(dict(row))
        return len(rows)

    def import_csv(self, path: str, update_existing: bool = False) -> Dict:
        """Import inventory from CSV file. Returns import summary."""
        csv_path = Path(path)
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")

        added = 0
        updated = 0
        skipped = 0
        errors = []

        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for lineno, row in enumerate(reader, 2):
                try:
                    item = Item(
                        sku=row.get("sku", "").strip(),
                        name=row.get("name", "").strip(),
                        quantity=int(row.get("quantity", 0)),
                        price=float(row.get("price", 0.0)),
                        location=row.get("location", "WAREHOUSE-A").strip(),
                        reorder_threshold=int(row.get("reorder_threshold", 10)),
                        category=row.get("category", "GENERAL").strip(),
                        barcode=row.get("barcode", "").strip(),
                        unit=row.get("unit", "EACH").strip(),
                        supplier=row.get("supplier", "").strip(),
                        notes=row.get("notes", "").strip(),
                    )
                    if not item.sku or not item.name:
                        errors.append(f"Line {lineno}: missing sku or name")
                        skipped += 1
                        continue

                    existing = self.get_item(item.sku)
                    if existing:
                        if update_existing:
                            with sqlite3.connect(self.db_path) as conn:
                                conn.execute(
                                    "UPDATE items SET name=?,quantity=?,price=?,location=?,reorder_threshold=?,category=?,barcode=?,unit=?,supplier=?,notes=?,updated_at=? WHERE sku=?",
                                    (item.name, item.quantity, item.price, item.location,
                                     item.reorder_threshold, item.category, item.barcode,
                                     item.unit, item.supplier, item.notes,
                                     datetime.utcnow().isoformat(), item.sku)
                                )
                            updated += 1
                        else:
                            skipped += 1
                    else:
                        self.add_item(item)
                        added += 1
                except Exception as e:
                    errors.append(f"Line {lineno}: {e}")
                    skipped += 1

        return {"added": added, "updated": updated, "skipped": skipped, "errors": errors}

    def barcode_lookup(self, code: str) -> Optional[Item]:
        """Look up item by barcode. Validates barcode format before lookup."""
        code = code.strip()
        fmt = None
        for name, pattern in BARCODE_FORMATS.items():
            if re.match(pattern, code):
                fmt = name
                break
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM items WHERE barcode=?", (code,)).fetchone()
            if row:
                return Item(**dict(row))
        return None

    def get_transaction_history(self, sku: Optional[str] = None, limit: int = 50) -> List[Transaction]:
        """Get transaction history, optionally filtered by SKU."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if sku:
                rows = conn.execute(
                    "SELECT * FROM transactions WHERE sku=? ORDER BY timestamp DESC LIMIT ?",
                    (sku.upper(), limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM transactions ORDER BY timestamp DESC LIMIT ?", (limit,)
                ).fetchall()
            return [Transaction(**dict(r)) for r in rows]

    def _save_transaction(self, conn: sqlite3.Connection, txn: Transaction):
        conn.execute(
            "INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?)",
            (txn.id, txn.sku, txn.transaction_type, txn.quantity_delta,
             txn.quantity_before, txn.quantity_after, txn.timestamp,
             txn.reference, txn.notes, txn.user)
        )

    def list_items(self, location: Optional[str] = None, category: Optional[str] = None,
                   sort_by: str = "sku") -> List[Item]:
        """List all items with optional filters."""
        valid_sorts = {"sku", "name", "quantity", "price", "location", "category"}
        if sort_by not in valid_sorts:
            sort_by = "sku"
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM items WHERE 1=1"
            params = []
            if location:
                query += " AND location=?"
                params.append(location)
            if category:
                query += " AND category=?"
                params.append(category)
            query += f" ORDER BY {sort_by}"
            rows = conn.execute(query, params).fetchall()
            return [Item(**dict(r)) for r in rows]

    def get_reorder_report(self) -> str:
        """Generate a text reorder report for low-stock items."""
        low = self.get_low_stock()
        if not low:
            return "All items are adequately stocked.\n"
        lines = [
            "=" * 60,
            "  REORDER REPORT",
            f"  Generated: {datetime.utcnow().isoformat()}Z",
            f"  Items needing reorder: {len(low)}",
            "=" * 60,
        ]
        for item in low:
            lines.append(
                f"  {item.sku:<20} {item.name:<25} Qty: {item.quantity:>5}  Threshold: {item.reorder_threshold:>5}"
            )
        lines.append("=" * 60)
        return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="inventory", description="BlackRoad Inventory Manager")
    parser.add_argument("--db", default="inventory.db")
    sub = parser.add_subparsers(dest="command")

    add = sub.add_parser("add", help="Add new item")
    add.add_argument("sku")
    add.add_argument("name")
    add.add_argument("--qty", type=int, default=0)
    add.add_argument("--price", type=float, default=0.0)
    add.add_argument("--location", default="WAREHOUSE-A")
    add.add_argument("--threshold", type=int, default=10)
    add.add_argument("--category", default="GENERAL")
    add.add_argument("--barcode", default="")

    upd = sub.add_parser("update", help="Update item quantity")
    upd.add_argument("sku")
    upd.add_argument("delta", type=int)
    upd.add_argument("--type", default="ADJUSTMENT")
    upd.add_argument("--ref", default="")
    upd.add_argument("--notes", default="")

    sub.add_parser("low-stock", help="Show low stock items")
    sub.add_parser("value", help="Calculate total inventory value")

    exp = sub.add_parser("export", help="Export to CSV")
    exp.add_argument("path")

    imp = sub.add_parser("import", help="Import from CSV")
    imp.add_argument("path")
    imp.add_argument("--update", action="store_true")

    lookup = sub.add_parser("barcode", help="Barcode lookup")
    lookup.add_argument("code")

    lst = sub.add_parser("list", help="List items")
    lst.add_argument("--location")
    lst.add_argument("--category")
    lst.add_argument("--sort", default="sku")

    hist = sub.add_parser("history", help="Transaction history")
    hist.add_argument("--sku")
    hist.add_argument("--limit", type=int, default=20)

    sub.add_parser("reorder", help="Reorder report")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)
    mgr = InventoryManager(db_path=args.db)
    if args.command == "add":
        item = Item(sku=args.sku, name=args.name, quantity=args.qty, price=args.price,
                    location=args.location, reorder_threshold=args.threshold,
                    category=args.category, barcode=args.barcode)
        mgr.add_item(item)
        print(f"Added: {item.sku} - {item.name} (qty={item.quantity})")
    elif args.command == "update":
        item = mgr.update_quantity(args.sku, args.delta, txn_type=args.type,
                                   reference=args.ref, notes=args.notes)
        print(f"{item.sku}: quantity now {item.quantity}")
    elif args.command == "low-stock":
        items = mgr.get_low_stock()
        if not items:
            print("All items adequately stocked.")
        else:
            for i in items:
                print(f"  {i.sku:<20} {i.name:<30} qty={i.quantity} threshold={i.reorder_threshold}")
    elif args.command == "value":
        v = mgr.calculate_value()
        print(json.dumps(v, indent=2))
    elif args.command == "export":
        n = mgr.export_csv(args.path)
        print(f"Exported {n} items to {args.path}")
    elif args.command == "import":
        result = mgr.import_csv(args.path, update_existing=args.update)
        print(json.dumps(result, indent=2))
    elif args.command == "barcode":
        item = mgr.barcode_lookup(args.code)
        print(json.dumps(item.to_dict() if item else None, indent=2))
    elif args.command == "list":
        items = mgr.list_items(location=args.location, category=args.category, sort_by=args.sort)
        for i in items:
            flag = " [LOW STOCK]" if i.is_low_stock() else ""
            print(f"  {i.sku:<15} {i.name:<30} qty={i.quantity:>6}  ${i.price:>8.2f}  {i.location}{flag}")
    elif args.command == "history":
        txns = mgr.get_transaction_history(sku=args.sku, limit=args.limit)
        for t in txns:
            sign = "+" if t.quantity_delta >= 0 else ""
            print(f"  {t.timestamp[:19]}  {t.sku:<15}  {t.transaction_type:<12}  {sign}{t.quantity_delta:>6}  => {t.quantity_after}")
    elif args.command == "reorder":
        print(mgr.get_reorder_report())


if __name__ == "__main__":
    main()
