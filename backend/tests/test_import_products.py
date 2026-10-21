import csv
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import inspect

from app import create_app
from app.config import Config
from app.extensions import db
from app.models.product import Product

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import import_products as ip  # noqa: E402

HEADER = ["sku", "name", "category", "brand", "price", "stock", "description", "image", "is_active"]


def write_csv(path, rows, header=HEADER):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path


def load(path):
    rows, headers = ip.read_table(path)
    return ip.clean_rows(rows, headers)


@pytest.fixture
def app(tmp_path):
    class Cfg(Config):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.db'}"
    return create_app(Cfg)


def count(app):
    with app.app_context():
        return Product.query.count() if inspect(db.engine).has_table("products") else -1


# ------------------------------------------------------------------ parsers
def test_parse_price():
    assert ip.parse_price("$1,299.50") == Decimal("1299.50")
    assert ip.parse_price(" 19.9 ") == Decimal("19.90")
    for bad in ("", "abc", "-5"):
        with pytest.raises(ValueError):
            ip.parse_price(bad)


def test_parse_stock_and_bool():
    assert ip.parse_stock("12") == 12 and ip.parse_stock("12.0") == 12 and ip.parse_stock("") == 0
    for bad in ("1.5", "-1", "lots"):
        with pytest.raises(ValueError):
            ip.parse_stock(bad)
    assert ip.parse_bool("Yes") is True and ip.parse_bool("0") is False and ip.parse_bool("") is True
    with pytest.raises(ValueError):
        ip.parse_bool("maybe")


# ------------------------------------------------------------------ validation
def test_column_aliases_and_row_errors(tmp_path):
    f = write_csv(tmp_path / "p.csv", [
        ["Mouse X", "electronics", "$19.99", "5", "ok"],              # good (category gets title-cased)
        ["", "electronics", "5", "1", "no name"],                      # missing name
        ["Cable", "electronics", "abc", "1", "bad price"],             # bad price
        ["Lamp", "home", "9.00", "-3", "negative stock"],              # bad stock
    ], header=["Title", "Department", "Cost", "Qty", "Details"])
    records, issues = load(f)
    assert len(records) == 1 and records[0]["category"] == "Electronics"
    assert records[0]["sku"] == "ELE-MOUSE-X"                          # generated, repeatable
    errors = {(i["row"], i["field"]) for i in issues if i["level"] == "error"}
    assert errors == {(3, "name"), (4, "price"), (5, "stock")}         # row numbers match the file (header = row 1)


def test_duplicate_sku_and_bad_sku(tmp_path):
    f = write_csv(tmp_path / "p.csv", [
        ["A-1", "One", "Home", "", "1", "1", "", "", ""],
        ["a-1", "Two", "Home", "", "2", "1", "", "", ""],
        ["bad sku!", "Three", "Home", "", "3", "1", "", "", ""],
    ])
    records, issues = load(f)
    assert [r["sku"] for r in records] == ["A-1"]
    msgs = " ".join(i["message"] for i in issues if i["level"] == "error")
    assert "duplicate SKU" in msgs and "letters, numbers" in msgs


def test_missing_required_columns(tmp_path):
    f = write_csv(tmp_path / "p.csv", [["x", "y"]], header=["foo", "bar"])
    with pytest.raises(ip.ImportFailure) as e:
        load(f)
    assert "name, category, price" in str(e.value)


# ------------------------------------------------------------------ file formats
def test_json_jsonl_and_xlsx_give_the_same_records(tmp_path):
    items = [{"sku": "ELE-1", "name": "Mouse", "category": "Electronics", "price": 10, "stock": 3},
             {"sku": "ELE-2", "name": "Keyboard", "category": "Electronics", "price": "$20.5", "stock": 4}]
    (tmp_path / "p.json").write_text(json.dumps({"products": items}))
    (tmp_path / "p.jsonl").write_text("\n".join(json.dumps(i) for i in items))
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["sku", "name", "category", "price", "stock"])
    for i in items:
        ws.append([i["sku"], i["name"], i["category"], i["price"], i["stock"]])
    wb.save(tmp_path / "p.xlsx")
    results = []
    for name in ("p.json", "p.jsonl", "p.xlsx"):
        records, issues = load(tmp_path / name)
        assert not [i for i in issues if i["level"] == "error"]
        results.append([(r["sku"], r["name"], r["price"], r["stock"]) for r in records])
    assert results[0] == results[1] == results[2] == [("ELE-1", "Mouse", Decimal("10.00"), 3),
                                                      ("ELE-2", "Keyboard", Decimal("20.50"), 4)]


def test_unsupported_and_missing_files(tmp_path):
    (tmp_path / "x.pdf").write_text("nope")
    with pytest.raises(ip.ImportFailure):
        ip.read_table(tmp_path / "x.pdf")
    with pytest.raises(ip.ImportFailure):
        ip.read_table(tmp_path / "missing.csv")


# ------------------------------------------------------------------ images
def test_image_resolution_copy_and_organize(tmp_path):
    images, source = tmp_path / "images", tmp_path / "incoming"
    (images / "electronics").mkdir(parents=True)
    source.mkdir()
    (images / "electronics" / "ele-1.png").write_bytes(b"x")          # already in its category folder
    (images / "mouse-pad.png").write_bytes(b"x")                       # loose file
    (source / "ele-3.jpg").write_bytes(b"x")                           # to be copied in
    f = write_csv(tmp_path / "p.csv", [
        ["ELE-1", "Mouse", "Electronics", "", "1", "1", "", "", ""],
        ["ELE-2", "Mouse Pad", "Electronics", "", "1", "1", "", "", ""],
        ["ELE-3", "Webcam", "Electronics", "", "1", "1", "", "", ""],
        ["ELE-4", "Ghost", "Electronics", "", "1", "1", "", "", ""],
        ["ELE-5", "Remote", "Electronics", "", "1", "1", "", "https://example.com/a.png", ""],
    ])
    records, _ = load(f)
    stats = ip.resolve_images(records, images, copy_from=source, organize=True)
    paths = {r["sku"]: r["image_path"] for r in records}
    assert paths["ELE-1"] == "electronics/ele-1.png"
    assert paths["ELE-2"] == "electronics/mouse-pad.png" and (images / "electronics" / "mouse-pad.png").exists()
    assert not (images / "mouse-pad.png").exists()                     # moved, not copied
    assert paths["ELE-3"] == "electronics/ele-3.jpg" and (images / "electronics" / "ele-3.jpg").exists()
    assert paths["ELE-4"] is None and paths["ELE-5"].startswith("https://")
    assert (stats["found"], stats["moved"], stats["copied"], stats["missing"], stats["remote"]) == (1, 1, 1, 1, 1)


def test_dry_run_does_not_touch_files(tmp_path):
    images, source = tmp_path / "images", tmp_path / "incoming"
    images.mkdir()
    source.mkdir()
    (source / "ele-1.png").write_bytes(b"x")
    records, _ = load(write_csv(tmp_path / "p.csv", [["ELE-1", "Mouse", "Electronics", "", "1", "1", "", "", ""]]))
    ip.resolve_images(records, images, copy_from=source, dry_run=True)
    assert not (images / "electronics").exists()


# ------------------------------------------------------------------ database
def rows_for(n):
    return [[f"ELE-{i}", f"Item {i}", "Electronics", "", f"{i}.50", i, f"desc {i}", "", "true"] for i in range(1, n + 1)]


def test_upsert_is_repeatable_and_updates(app, tmp_path):
    records, _ = load(write_csv(tmp_path / "p.csv", rows_for(5)))
    assert ip.write_db(app, records)["inserted"] == 5
    again = ip.write_db(app, records)
    assert again["inserted"] == 0 and again["updated"] == 5 and count(app) == 5        # no duplicates
    records[0]["price"] = Decimal("99.00")
    ip.write_db(app, records)
    with app.app_context():
        assert Product.query.filter_by(sku="ELE-1").one().price == Decimal("99.00")


def test_modes_insert_and_update(app, tmp_path):
    records, _ = load(write_csv(tmp_path / "p.csv", rows_for(3)))
    ip.write_db(app, records[:2])
    s = ip.write_db(app, records, mode="insert")
    assert (s["inserted"], s["skipped_existing"]) == (1, 2)
    s = ip.write_db(app, load(write_csv(tmp_path / "q.csv", rows_for(5)))[0], mode="update")
    assert (s["updated"], s["skipped_missing"]) == (3, 2) and count(app) == 3


def test_dry_run_changes_nothing(app, tmp_path):
    records, _ = load(write_csv(tmp_path / "p.csv", rows_for(4)))
    assert ip.write_db(app, records, dry_run=True)["inserted"] == 4
    assert count(app) == -1                                            # the table was not even created
    ip.write_db(app, records)
    more, _ = load(write_csv(tmp_path / "q.csv", rows_for(6)))
    ip.write_db(app, more, dry_run=True)
    assert count(app) == 4


def test_all_or_nothing_on_database_error(app, tmp_path):
    records, _ = load(write_csv(tmp_path / "p.csv", rows_for(3)))
    records[2]["price"] = Decimal("-1")                                # violates the CHECK constraint
    with pytest.raises(Exception):
        ip.write_db(app, records)
    assert count(app) == 0                                             # nothing half-imported


# ------------------------------------------------------------------ SQL seed + command line
def test_sql_block_escapes_and_preserves_other_sql(tmp_path):
    records, _ = load(write_csv(tmp_path / "p.csv", [["X-1", "Men's Watch", "Home", "", "5", "2", "It's nice", "", "true"]]))
    block = ip.sql_block(records)
    assert "'Men''s Watch'" in block and "ON CONFLICT (sku) DO UPDATE" in block
    seed = tmp_path / "seed.sql"
    seed.write_text("-- mine\nSELECT 1;\n")
    ip.update_marked_block(seed, block)
    ip.update_marked_block(seed, ip.sql_block(records))                # second run replaces, never duplicates
    text = seed.read_text()
    assert text.count(ip.BEGIN) == 1 and "SELECT 1;" in text


def test_products_csv_template_is_valid():
    records, issues = load(REPO / "database" / "products.csv")
    assert len(records) >= 30 and not [i for i in issues if i["level"] == "error"]
    assert len({r["sku"] for r in records}) == len(records)


def test_command_line_end_to_end(tmp_path, capsys):
    f = write_csv(tmp_path / "p.csv", rows_for(3) + [["", "", "Home", "", "x", "", "", "", ""]])
    url = f"sqlite:///{tmp_path / 'cli.db'}"
    args = [str(f), "--database-url", url, "--images-dir", str(tmp_path / "img"), "--errors-out", str(tmp_path / "err.csv")]
    assert ip.main(args + ["--strict"]) == 2                           # bad row + --strict: nothing imported
    assert ip.main(args) == 0                                          # otherwise: good rows go in, bad rows reported
    out = capsys.readouterr().out
    assert "3 new" in out and (tmp_path / "err.csv").exists()
    err_rows = list(csv.reader(open(tmp_path / "err.csv", newline="", encoding="utf-8-sig")))
    assert err_rows[0][:2] == ["row", "problem"] and err_rows[0][2:] == HEADER      # original columns kept
    assert err_rows[1][0] == "5" and "name is required" in err_rows[1][1]
    assert err_rows[1][4] == "Home"                                                 # original values kept


def test_excel_style_csv_bom_semicolons_and_units_in_headers(tmp_path):
    f = tmp_path / "excel.csv"
    f.write_bytes("\ufeffProduct Name;Department;Price (INR);Qty;Active\nTrail Backpack;accessories;\u20b91,299.50;12;Yes\n"
                  "Canvas Belt;ACCESSORIES;249;0;no\n".encode("utf-8"))
    records, issues = load(f)
    assert [(r["name"], r["category"], r["price"], r["stock"], r["is_active"]) for r in records] == [
        ("Trail Backpack", "Accessories", Decimal("1299.50"), 12, True),
        ("Canvas Belt", "Accessories", Decimal("249.00"), 0, False)]
    assert not [i for i in issues if i["level"] == "error"]
