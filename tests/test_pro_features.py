"""Comprehensive tests for Vaad Bayt v2.0 features & bug fixes."""

import csv
from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from vaad.banking import commit_bank_rows, parse_bank_file
from vaad.excel import read_xlsx, write_xlsx
from vaad.ledger import Ledger, METHODS
from vaad.reports import build_receipt_html, build_report_html, export_full_archive, monthly_chart_svg
from vaad.store import Problem, Store, has_permission
from vaad.ui_widgets import sort_key


class ProFeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.store = Store(self.folder / "live.sqlite3")
        self.addCleanup(lambda: self.store.close())
        self.store.setup(
            "ועד הבית", "שחראי 14, 16, 18", "2025-01-01", 500000, "admin-pass-123",
            str(self.folder / "backups"), 10000, "3",
        )
        self.ledger = Ledger(self.store)
        self.ledger.generate("2025-02-01")
        self.units = self.ledger.units()
        self.unit = self.units[0]["id"]
        self.exp_cat = self.store.rows("SELECT id FROM categories WHERE kind='expense'")[0]["id"]
        self.inc_cat = self.store.rows("SELECT id FROM categories WHERE kind='income'")[0]["id"]
        self.admin = self.store.authenticate_user("admin", "admin-pass-123")

    def test_v1_to_v3_real_migration_preserves_data_and_migrates_admin(self):
        v1_path = self.folder / "legacy_v1.sqlite3"
        sql001 = Path("vaad/001.sql").read_text(encoding="utf-8-sig")
        db = sqlite3.connect(v1_path)
        db.executescript(f"BEGIN IMMEDIATE; {sql001} PRAGMA application_id={Store.APP_ID}; PRAGMA user_version=1; COMMIT;")
        import os
        from vaad.store import password_hash
        salt = os.urandom(16)
        db.executemany(
            "INSERT INTO settings VALUES (?,?)",
            [
                ("name", "Legacy Vaad"), ("complex", "Shahrai"), ("start", "2025-01-01"),
                ("initial", "100000"), ("salt", salt.hex()), ("password", password_hash("legacy-secret", salt)),
            ],
        )
        db.commit()
        db.close()

        upgraded = Store(v1_path)
        self.addCleanup(upgraded.close)
        self.assertEqual(upgraded.db.execute("PRAGMA user_version").fetchone()[0], Store.SCHEMA)
        user = upgraded.authenticate_user("admin", "legacy-secret")
        self.assertIsNotNone(user)
        self.assertEqual(user["role"], "admin")

    def test_supplier_totals_subtract_reversed_expenses(self):
        sid = self.ledger.save_supplier("חברת ניקיון", "ניקיון", "050-1234567", actor=self.admin)
        e1 = self.ledger.post(
            "expense", 40000, "2025-01-10", METHODS[1], "sup-exp-1",
            category=self.exp_cat, party="חברת ניקיון", description="ניקיון ינואר", supplier=sid, actor=self.admin,
        )
        e2 = self.ledger.post(
            "expense", 15000, "2025-01-12", METHODS[1], "sup-exp-2",
            category=self.exp_cat, party="חברת ניקיון", description="תיקון טעות", supplier=sid, actor=self.admin,
        )
        self.ledger.reverse(e2, "טעות בסכום", "2025-01-13", actor=self.admin)

        summary = next(s for s in self.ledger.suppliers_summary("2025-01-01", "2025-12-31") if s["id"] == sid)
        self.assertEqual(summary["period_total"], 40000)
        by_sup = dict(self.ledger.expenses_by_supplier("2025-01-01", "2025-12-31"))
        self.assertEqual(by_sup["חברת ניקיון"], 40000)
        self.assertEqual(len(self.ledger.supplier_history(sid)), 3)  # e1, e2, reversal

    def test_recurring_reappears_when_matched_expense_is_reversed_and_can_be_edited(self):
        rec_id = self.ledger.save_recurring(
            category=self.exp_cat, usual_amount=25000, frequency_months=1, due_day=15,
            starts="2025-01-01", notes="חשמל חדר מדרגות", actor=self.admin,
        )
        due_before = self.ledger.recurring_due("2025-01-31")
        self.assertEqual(len(due_before), 1)
        exp_id = self.ledger.post(
            "expense", 25000, "2025-01-15", METHODS[1], "rec-pay-1",
            category=self.exp_cat, party="חברת חשמל", description="חשמל", actor=self.admin,
        )
        self.ledger.match_recurring(rec_id, "2025-01", exp_id, actor=self.admin)
        self.assertEqual(self.ledger.recurring_due("2025-01-31"), [])

        # Reverse the matched expense -> due item must reappear and be rematchable!
        self.ledger.reverse(exp_id, "בוטל", "2025-01-16", actor=self.admin)
        self.assertEqual(len(self.ledger.recurring_due("2025-01-31")), 1)

        exp_id2 = self.ledger.post(
            "expense", 26000, "2025-01-16", METHODS[1], "rec-pay-2",
            category=self.exp_cat, party="חברת חשמל", description="חשמל מתוקן", actor=self.admin,
        )
        self.ledger.match_recurring(rec_id, "2025-01", exp_id2, actor=self.admin)
        self.assertEqual(self.ledger.recurring_due("2025-01-31"), [])

        # Edit and deactivate template
        self.ledger.save_recurring(
            category=self.exp_cat, usual_amount=30000, frequency_months=1, due_day=15,
            starts="2025-01-01", notes="חשמל", active=False, rec_id=rec_id, actor=self.admin,
        )
        self.assertEqual(self.ledger.recurring_due("2025-03-31"), [])

    def test_occupants_history_tracks_sequential_arrived_dates(self):
        self.ledger.unit_update(self.unit, ("1", "משה לוי", "דני כהן", "050-111", "a@b.c", ""), True, actor=self.admin)
        self.ledger.replace_resident(self.unit, "tenant", "יוסי מזרחי", "050-222", "y@b.c", "2025-03-01", "עזיבה מסודרת", actor=self.admin)
        self.ledger.replace_resident(self.unit, "tenant", "רונית דוד", "050-333", "r@b.c", "2025-06-01", "החלפה שנייה", actor=self.admin)
        occs = self.ledger.unit_occupants(self.unit)
        self.assertEqual(len(occs), 2)
        # Most recent departed first
        self.assertEqual(occs[0]["name"], "יוסי מזרחי")
        self.assertEqual(occs[0]["arrived"], "2025-03-01")
        self.assertEqual(occs[0]["departed"], "2025-06-01")
        self.assertEqual(occs[1]["name"], "דני כהן")
        self.assertEqual(occs[1]["arrived"], "2025-01-01")
        self.assertEqual(occs[1]["departed"], "2025-03-01")

    def test_add_unit_and_charge_generation(self):
        new_id = self.ledger.add_unit(18, "9", "", 10000, owner="ישראל ישראלי", start="2025-02-01", actor=self.admin)
        self.assertEqual(len(self.ledger.units("2025-02-01")), 22)
        self.ledger.generate("2025-03-01")
        self.assertIn("2025-03", self.ledger.account(new_id)["charges"])

    def test_rbac_users_and_audit_log(self):
        uid = self.store.create_user("vaad1", "דוד חבר ועד", "member", "member-pass-1", actor=self.admin)
        vid = self.store.create_user("viewer1", "רואה חשבון", "viewer", "viewer-pass-1", actor=self.admin)
        member = self.store.authenticate_user("vaad1", "member-pass-1")
        viewer = self.store.authenticate_user("viewer1", "viewer-pass-1")
        self.assertEqual(member["role"], "member")
        self.assertEqual(viewer["role"], "viewer")
        self.assertTrue(has_permission("member", "record_payment"))
        self.assertFalse(has_permission("member", "manage_users"))
        self.assertFalse(has_permission("viewer", "record_payment"))
        self.assertTrue(has_permission("viewer", "view"))

        # Cannot deactivate the only active admin
        with self.assertRaises(Problem):
            self.store.update_user(self.admin["id"], "מנהל", "admin", False, actor=self.admin)

        logs = self.store.audit_entries()
        self.assertTrue(any(r["action"] == "create_user" for r in logs))

    def test_attachments_and_full_zip_backup_restore(self):
        exp_id = self.ledger.post(
            "expense", 5000, "2025-01-20", METHODS[0], "att-exp",
            category=self.exp_cat, party="חשמלאי", description="תיקון תאורה", actor=self.admin,
        )
        invoice = self.folder / "invoice_123.pdf"
        invoice.write_bytes(b"%PDF-1.4 fake invoice content")
        att_id = self.store.add_attachment(exp_id, invoice, actor=self.admin)
        self.assertEqual(len(self.store.list_attachments(entry_id=exp_id)), 1)

        bundle = self.store.backup_bundle(self.folder / "backups", kind="manual", actor=self.admin)
        self.assertTrue(zipfile.is_zipfile(bundle))

        # Delete attachment and post another expense, then restore from bundle
        self.store.delete_attachment(att_id, actor=self.admin)
        self.assertEqual(len(self.store.list_attachments(entry_id=exp_id)), 0)
        self.ledger.post("expense", 9000, "2025-01-22", METHODS[0], "after-backup", category=self.exp_cat, party="x", description="y")

        self.store.restore(bundle, self.folder / "safety")
        self.assertEqual(self.ledger.cash()[0], 495000)
        restored_atts = self.store.list_attachments(entry_id=exp_id)
        self.assertEqual(len(restored_atts), 1)
        restored_path, _ = self.store.attachment_path(restored_atts[0]["id"])
        self.assertEqual(restored_path.read_bytes(), b"%PDF-1.4 fake invoice content")

    def test_pure_python_excel_roundtrip_hebrew(self):
        xlsx_path = self.folder / "report.xlsx"
        write_xlsx(
            xlsx_path,
            [{
                "title": "דוח גבייה",
                "headers": ["יחידה", "שם דייר", "סכום"],
                "rows": [["14 / 1", "דני כהן", 100.50], ["16 / 3 א", "רונית לוי", 50.00]],
                "totals": ["סה״כ", "", 150.50],
            }],
        )
        rows = read_xlsx(xlsx_path)
        self.assertEqual(rows[0], ["יחידה", "שם דייר", "סכום"])
        self.assertEqual(rows[1][1], "דני כהן")
        self.assertEqual(float(rows[1][2]), 100.5)
        self.assertEqual(float(rows[3][2]), 150.5)

    def test_bank_import_csv_xlsx_smart_matching_dedup_and_ignore(self):
        self.ledger.unit_update(self.unit, ("1", "משה לוי", "דני כהן", "050-111", "", ""), True, actor=self.admin)
        bank_csv = self.folder / "bank.csv"
        with open(bank_csv, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["דוח תנועות חשבון 12345"])
            w.writerow(["תאריך", "תיאור", "אסמכתא", "זכות", "חובה"])
            w.writerow(["15/01/2025", "העברה מאת דני כהן דירה 1", "REF001", "100.00", ""])
            w.writerow(["16/01/2025", "הפקדה לא קשורה", "REF002", "250.00", ""])
            w.writerow(["17/01/2025", "חברת חשמל", "REF003", "", "80.00"])

        parsed = parse_bank_file(bank_csv, self.store, self.ledger)
        self.assertEqual(len(parsed), 3)
        # First row should auto-match unit with high confidence
        self.assertEqual(parsed[0]["suggested_unit"], self.unit)
        self.assertEqual(parsed[0]["confidence"], "גבוהה")
        self.assertEqual(parsed[0]["action"], "payment")

        # Mark 2nd row as ignored (not related to Vaad) and 3rd row as expense
        parsed[1]["action"] = "ignore"
        parsed[2]["action"] = "expense"
        parsed[2]["category_id"] = self.exp_cat

        imported, ignored = commit_bank_rows(self.store, self.ledger, parsed, actor=self.admin)
        self.assertEqual((imported, ignored), (2, 1))
        self.assertEqual(self.ledger.cash()[0], 500000 + 10000 - 8000)

        # Re-importing the exact same bank file must detect all 3 rows as already processed!
        reparsed = parse_bank_file(bank_csv, self.store, self.ledger)
        self.assertEqual(reparsed[0]["already_status"], "matched")
        self.assertEqual(reparsed[1]["already_status"], "ignored")
        self.assertEqual(reparsed[2]["already_status"], "matched")
        imp2, ign2 = commit_bank_rows(self.store, self.ledger, reparsed, actor=self.admin)
        self.assertEqual((imp2, ign2), (0, 0))

    def test_receipt_reports_svg_chart_and_full_export(self):
        pay_id = self.ledger.post("payment", 10000, "2025-01-20", METHODS[0], "pay-rcpt", unit=self.unit, party="דני", actor=self.admin)
        rcpt_html = build_receipt_html(self.ledger.receipt_data(pay_id))
        self.assertIn(f"VB-{pay_id:05d}", rcpt_html)
        self.assertIn("100.00 ₪", rcpt_html)

        series = self.ledger.monthly_series(6, through="2025-06-01")
        self.assertEqual(len(series), 6)
        svg = monthly_chart_svg(series)
        self.assertIn("<svg", svg)

        html_doc = build_report_html(self.store, "דוח שנתי", ("חודש", "סכום"), [(1, ("01/2025", "100.00 ₪"))], chart_svg=svg)
        self.assertIn("שחראי 14, 16, 18", html_doc)

        archive = self.folder / "full_export.zip"
        export_full_archive(self.store, self.ledger, archive)
        with zipfile.ZipFile(archive) as zf:
            self.assertIn("vaad-data.xlsx", zf.namelist())

    def test_sort_key_handles_currency_and_dates(self):
        money_vals = ["\u200e1,200.00 ₪\u200e", "\u200e50.00 ₪\u200e", "\u200e−200.00 ₪\u200e", "\u200e100.00 ₪\u200e"]
        self.assertEqual(
            sorted(money_vals, key=sort_key),
            ["\u200e−200.00 ₪\u200e", "\u200e50.00 ₪\u200e", "\u200e100.00 ₪\u200e", "\u200e1,200.00 ₪\u200e"],
        )
        dates = ["15/02/2025", "01/03/2024", "02/01/2025"]
        self.assertEqual(sorted(dates, key=sort_key), ["01/03/2024", "02/01/2025", "15/02/2025"])


if __name__ == "__main__":
    unittest.main()
