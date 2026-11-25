import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

from vaad.ledger import Ledger, METHODS
from vaad.store import Store, Problem


class FinancialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.store = Store(self.folder / "live.sqlite3")
        self.addCleanup(lambda: self.store.db.close())
        self.store.setup("test", "test", "2025-01-01", 500000, "test-password",
                         str(self.folder / "backups"), 10000, "test-split")
        self.ledger = Ledger(self.store)
        self.ledger.generate("2025-01-01")
        self.unit = self.ledger.units()[0]["id"]
        self.expense = self.store.rows("SELECT id FROM categories WHERE kind='expense'")[0]["id"]

    def pay(self, amount, token="test", day="2025-01-20", **kw):
        return self.ledger.post("payment",amount,day,METHODS[0],token,unit=self.unit,**kw)

    def spend(self, amount, day, token):
        return self.ledger.post("expense",amount,day,METHODS[0],token,category=self.expense,
                                party="test",description="test")

    def test_01_configuration(self):
        self.assertEqual(sum(r["apartments"] for r in self.store.rows("SELECT apartments FROM buildings")),20)
        rates = [u["rate"] for u in self.ledger.units()]
        self.assertEqual((len(rates),rates.count(10000),rates.count(5000),sum(rates)),(21,19,2,200000))

    def test_02_generation_idempotent(self):
        for _ in range(3):
            self.ledger.generate("2025-01-31")
        self.assertEqual(len(self.store.rows("SELECT id FROM entries WHERE kind='charge'")),21)

    def test_03_catchup_historic_rates(self):
        self.store.db.execute("INSERT INTO fee_rates VALUES (?,?,?)",(self.unit,"2025-03-01",12000))
        self.ledger.generate("2025-04-01")
        detail = self.ledger.account(self.unit)["charges"]
        self.assertEqual([r["due"] for r in detail.values()],[10000,10000,12000,12000])
        self.assertEqual(len(self.store.rows("SELECT id FROM entries WHERE kind='charge'")),84)

    def test_04_complete_payment(self):
        self.pay(10000)
        self.assertEqual(self.ledger.account(self.unit)["balance"],0)
        self.assertEqual(self.ledger.cash()[0],510000)

    def test_05_partial_payment(self):
        self.pay(4000)
        self.assertEqual(self.ledger.account(self.unit)["balance"],6000)
        self.assertEqual(self.ledger.cash()[0],504000)

    def test_06_advance(self):
        self.pay(60000)
        self.assertEqual(self.ledger.account(self.unit)["credit"],50000)
        self.ledger.generate("2025-06-01")
        self.assertEqual([c["left"] for c in self.ledger.account(self.unit)["charges"].values()],[0]*6)
        self.assertEqual(self.ledger.cash()[0],560000)

    def test_07_fifo(self):
        self.ledger.generate("2025-03-01")
        self.pay(15000,day="2025-03-03")
        data = self.ledger.account(self.unit)
        self.assertEqual([c["paid"] for c in data["charges"].values()],[10000,5000,0])
        self.assertEqual(data["balance"],15000)

    def test_08_rate_preserves_generated_charge(self):
        now = date.today().isoformat()
        self.ledger.generate(now)
        self.ledger.rate(self.unit,now,12000)
        self.ledger.generate(now)
        self.assertEqual(self.ledger.account(self.unit)["charges"][now[:7]]["due"],10000)

    def test_09_exemption(self):
        self.ledger.adjust(self.unit,"2025-01",0,"test")
        self.assertEqual(self.ledger.account(self.unit)["balance"],0)
        self.assertEqual(self.ledger.report("2025-01")["charges"],190000)
        self.assertEqual(self.ledger.cash()[0],500000)

    def test_10_expense(self):
        self.spend(75000,"2025-01-15","expense")
        self.assertEqual(self.ledger.cash()[0],425000)

    def test_11_correction(self):
        old = self.pay(50000)
        self.ledger.reverse(old,"test","2025-01-21")
        self.pay(30000,"replacement",day="2025-01-21")
        self.assertEqual(self.ledger.report("2025-01")["payment"],30000)
        self.assertEqual(self.ledger.account(self.unit)["credit"],20000)
        self.assertEqual([r["original"] for r in self.ledger.cash()[1]],[None,old,None])
        with self.assertRaises(Problem):
            self.ledger.reverse(old,"test")

    def test_12_opening(self):
        self.ledger.opening(self.unit,30000)
        self.assertEqual(self.ledger.account(self.unit)["balance"]-10000,30000)
        self.assertEqual(self.ledger.cash()[0],500000)
        self.pay(10000)
        self.assertEqual(self.ledger.account(self.unit)["charges"]["2025-01"]["paid"],0)

    def test_13_duplicate(self):
        entry = self.pay(4000)
        self.assertEqual(entry,self.pay(4000))
        with self.assertRaises(Problem):
            self.pay(4000,"second")
        self.pay(4000,"second",allow_duplicate=True)
        self.assertEqual(self.ledger.cash()[0],508000)

    def test_14_backdated(self):
        self.spend(10000,"2025-02-03","later")
        self.spend(30000,"2025-01-02","earlier")
        self.assertEqual([r["balance"] for r in self.ledger.cash()[1]],[470000,460000])
        self.assertEqual(self.ledger.report("2025-02")["initial"],470000)

    def test_15_backup_restore(self):
        self.pay(4000)
        snapshot = self.store.backup(self.folder/"backup")
        self.spend(10000,"2025-01-20","expense")
        self.store.restore(snapshot,self.folder/"safety")
        self.assertEqual(self.ledger.cash()[0],504000)
        self.assertTrue(self.store.authenticate("test-password"))
        self.assertEqual(len(list((self.folder/"safety").glob("*.sqlite3"))),1)

    def test_16_interruption(self):
        result = subprocess.run([sys.executable,"-c",
            "import sqlite3,sys,os; db=sqlite3.connect(sys.argv[1]); db.execute('BEGIN IMMEDIATE'); "
            "db.execute(\"INSERT INTO entries(day,kind,cash) VALUES ('2025-01-20','income',10000)\"); os._exit(17)",
            str(self.store.path)],check=False)
        self.assertEqual(result.returncode,17)
        self.assertEqual(self.ledger.cash()[0],500000)
        self.assertEqual(self.store.db.execute("PRAGMA integrity_check").fetchone()[0],"ok")

    def test_17_invalid_restore(self):
        invalid = self.folder/"bad.sqlite3"
        invalid.write_text("invalid",encoding="utf-8")
        with self.assertRaises((Problem,sqlite3.DatabaseError)):
            self.store.restore(invalid,self.folder/"safety")
        self.assertEqual(self.ledger.cash()[0],500000)

    def test_19_password_rate_limit(self):
        for _ in range(5):
            self.assertFalse(self.store.authenticate("invalid"))
        with self.assertRaises(Problem):
            self.store.authenticate("test-password")


if __name__ == "__main__":
    unittest.main()

