"""Tests for v3.0: Bank vs Cash split, internal transfers, Shahrai spelling, default 21 units, and Excel 2025-2027 seed."""

import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from vaad.ledger import Ledger, METHODS
from vaad.store import Store, password_hash


class V3FeaturesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.store = Store(self.folder / "live.sqlite3")
        self.addCleanup(lambda: self.store.close())
        self.store.setup(
            "ועד הבית", "שחראי 14, 16, 18", "2026-01-01", 0, "admin-pass-123",
            str(self.folder / "backups"), 10000, "מחולקת",
            initial_bank=1500000, initial_cash=250000, seed_shahrai_names=True,
        )
        self.ledger = Ledger(self.store)
        self.admin = self.store.authenticate_user("admin", "admin-pass-123")
        self.exp_cat = self.store.rows("SELECT id FROM categories WHERE kind='expense'")[0]["id"]

    def test_default_21_shahrai_units_populated(self):
        units = self.ledger.units()
        self.assertEqual(len(units), 21)
        names = [u["owner"] for u in units]
        self.assertIn("טרייטסמן", names)
        self.assertIn("אביטן", names)
        self.assertIn("בל", names)
        self.assertIn("אסייג", names)
        self.assertIn("מרמלשטיין", names)
        # Split units at 50 NIS (5000 agorot)
        abitan = next(u for u in units if u["owner"] == "אביטן")
        bel = next(u for u in units if u["owner"] == "בל")
        self.assertEqual((abitan["building"], abitan["rate"], abitan["subunit"]), (16, 5000, "א"))
        self.assertEqual((bel["building"], bel["rate"], bel["subunit"]), (16, 5000, "ב"))
        self.assertEqual(sum(u["rate"] for u in units), 200000)

    def test_bank_and_cash_split_and_internal_transfers(self):
        b0 = self.ledger.balances()
        self.assertEqual(b0, {"total": 1750000, "bank": 1500000, "cash": 250000})

        u_id = self.ledger.units()[0]["id"]
        # Cash payment -> increases cash only
        self.ledger.post("payment", 10000, "2026-02-01", "מזומן", "p-cash", unit=u_id, actor=self.admin)
        # Bank transfer payment -> increases bank only
        self.ledger.post("payment", 20000, "2026-02-02", "העברה בנקאית", "p-bank", unit=u_id, actor=self.admin)
        # Cash expense -> decreases cash only
        self.ledger.post("expense", 5000, "2026-02-03", "מזומן", "e-cash", category=self.exp_cat, party="ניקיון", description="חומרים", actor=self.admin)

        b1 = self.ledger.balances()
        self.assertEqual(b1["bank"], 1520000)
        self.assertEqual(b1["cash"], 255000)
        self.assertEqual(b1["total"], 1775000)
        self.assertEqual(self.ledger.cash()[0], b1["total"])

        # Deposit 1000 NIS from cash into bank -> total unchanged!
        self.ledger.transfer_cash("cash", "bank", 100000, "2026-02-05", reference="DEP-1", notes="הפקדה לבנק", actor=self.admin)
        b2 = self.ledger.balances()
        self.assertEqual(b2["bank"], 1620000)
        self.assertEqual(b2["cash"], 155000)
        self.assertEqual(b2["total"], 1775000)
        self.assertEqual(len(self.ledger.list_transfers()), 1)

    def test_excel_seed_exact_2025_2026_2027_and_idempotency(self):
        added1 = self.ledger.load_shahrai_excel_data(target_bank=1500000, target_cash=250000, actor=self.admin)
        self.assertGreater(added1, 150)
        # Exact target balances preserved!
        bals = self.ledger.balances()
        self.assertEqual(bals, {"total": 1750000, "bank": 1500000, "cash": 250000})

        # Second call is 100% idempotent
        added2 = self.ledger.load_shahrai_excel_data(target_bank=1500000, target_cash=250000, actor=self.admin)
        self.assertEqual(added2, 0)
        self.assertEqual(self.ledger.balances(), {"total": 1750000, "bank": 1500000, "cash": 250000})

        # Verify 2025 matrix + compensation checks + previous names
        m2025 = {r["unit"]["owner"]: r for r in self.ledger.annual_matrix(2025)}
        self.assertEqual(m2025["טרייטסמן"]["paid_count"], 7)
        self.assertEqual((m2025["טרייטסמן"]["comp_amount"], m2025["טרייטסמן"]["comp_status"]), ("800", "שולם"))
        self.assertEqual((m2025["תמיר"]["comp_amount"], m2025["תמיר"]["comp_status"]), ("900+250", "שולם"))
        self.assertEqual((m2025["מונסונגו"]["comp_amount"], m2025["מונסונגו"]["comp_status"]), ("1300", "קוזז 2026"))
        # Bel 2025: Jan unpaid, Feb-Sep paid
        self.assertEqual(m2025["בל"]["months"][0], "unpaid")
        self.assertEqual(m2025["בל"]["paid_count"], 8)
        # Previous 2025 names displayed on 2025 sheet
        self.assertEqual(m2025["אסייג"]["display_name"], "שוחט")
        self.assertEqual(m2025["מרמלשטיין"]["display_name"], "סבן- אלמקייס")

        # Verify 2026 matrix (active ledger with for_period!)
        m2026 = {r["unit"]["owner"]: r for r in self.ledger.annual_matrix(2026)}
        # Assayag: Jan 2026 UNPAID, Feb-Dec 2026 PAID
        self.assertEqual(m2026["אסייג"]["months"][0], "unpaid")
        self.assertTrue(all(st == "paid" for st in m2026["אסייג"]["months"][1:]))
        self.assertEqual(m2026["אסייג"]["paid_count"], 11)
        # Hazan Daniel: Jan-Apr paid (4 months from 400 comp check)
        self.assertEqual(m2026["חזן דניאל"]["paid_count"], 4)
        # Abitan: Jan-Apr paid (4 months * 50 = 200 comp check)
        self.assertEqual(m2026["אביטן"]["paid_count"], 4)
        # Bel: Jan-Oct paid (10 months * 50 = 500 comp check)
        self.assertEqual(m2026["בל"]["paid_count"], 10)
        # Cohen Uriel: only Jan paid
        self.assertEqual(m2026["כהן אוריאל"]["paid_count"], 1)

        # Verify 2027 matrix: only Sagron Yitzhak & Monsonego have Jan 2027 paid
        m2027 = {r["unit"]["owner"]: r for r in self.ledger.annual_matrix(2027)}
        self.assertEqual(m2027["סגרון יצחק"]["months"][0], "paid")
        self.assertEqual(m2027["מונסונגו"]["months"][0], "paid")
        self.assertEqual(m2027["טרייטסמן"]["paid_count"], 0)

    def test_quick_pay_months_updates_matrix_and_cash_balance(self):
        self.ledger.load_shahrai_excel_data(target_bank=1000000, target_cash=50000, actor=self.admin)
        tr = next(u for u in self.ledger.units() if u["owner"] == "טרייטסמן")
        ids = self.ledger.quick_pay_months(
            tr["id"], ["2026-07", "2026-08"], "2026-11-26", "מזומן",
            account="cash", party="טרייטסמן", actor=self.admin,
        )
        self.assertEqual(len(ids), 2)
        self.assertEqual(self.ledger.balances()["cash"], 70000)
        m2026 = next(r for r in self.ledger.annual_matrix(2026) if r["unit"]["id"] == tr["id"])
        self.assertEqual(m2026["paid_count"], 8)
        self.assertEqual(m2026["months"][6], "paid")
        self.assertEqual(m2026["months"][7], "paid")

    def test_v3_to_v4_migration_fixes_shahrai_spelling_and_cashbox(self):
        legacy = self.folder / "v3.sqlite3"
        db = sqlite3.connect(legacy)
        for sql_name, ver in (("001.sql", 1), ("002.sql", 2), ("003.sql", 3)):
            sql = Path("vaad", sql_name).read_text(encoding="utf-8-sig")
            extra = f"PRAGMA application_id={Store.APP_ID};" if ver == 1 else ""
            db.executescript(f"BEGIN IMMEDIATE; {sql} {extra} PRAGMA user_version={ver}; COMMIT;")
        salt = os.urandom(16)
        pwd = password_hash("secret123", salt)
        db.executemany(
            "INSERT INTO settings VALUES (?,?)",
            [("name", "ועד שחריי"), ("complex", "שחריי 14, 16, 18"), ("start", "2026-01-01"),
             ("initial", "300000"), ("salt", salt.hex()), ("password", pwd)],
        )
        db.execute("INSERT INTO users(username,display_name,role,password_hash,salt,active) VALUES ('admin','מנהל','admin',?,?,1)", (pwd, salt.hex()))
        db.commit()
        db.close()

        upgraded = Store(legacy)
        self.addCleanup(upgraded.close)
        self.assertEqual(upgraded.get("complex"), "שחראי 14, 16, 18")
        self.assertEqual(upgraded.get("name"), "ועד שחראי")
        self.assertEqual(upgraded.get("initial_bank"), "300000")
        self.assertEqual(upgraded.get("initial_cash"), "0")


if __name__ == "__main__":
    unittest.main()
