from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from contextlib import contextmanager, closing
import hashlib
import hmac
import os
import sqlite3
import tempfile
import time


class Problem(ValueError):
    pass


def money(value):
    try:
        amount = Decimal(str(value).strip()) * 100
        if not amount.is_finite() or abs(amount) > 10**12 or amount != amount.to_integral_value():
            raise ValueError
        return int(amount)
    except (InvalidOperation, ValueError):
        raise Problem("יש להזין סכום תקין עם עד שתי ספרות אחרי הנקודה")


def valid_day(value):
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise Problem("יש להזין תאריך תקין")


def month_next(value):
    year, month = map(int, value.split("-"))
    return f"{year + (month == 12):04d}-{month % 12 + 1:02d}"


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1, maxmem=64*1024**2).hex()


class Store:
    SCHEMA = 1
    APP_ID = 0x56414144

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = self.connect(self.path)
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            migration = Path(__file__).with_name("001.sql").read_text(encoding="utf-8-sig")
            self.db.executescript(
                f"BEGIN IMMEDIATE; {migration} PRAGMA application_id={self.APP_ID}; "
                f"PRAGMA user_version=1; COMMIT;"
            )
        self.verify(self.db)

    @staticmethod
    def connect(path, readonly=False):
        db = sqlite3.connect(path.absolute().as_uri() + "?mode=ro" if readonly else path,
                             uri=readonly, isolation_level=None, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @classmethod
    def verify(cls, db):
        if (db.execute("PRAGMA application_id").fetchone()[0] != cls.APP_ID
            or db.execute("PRAGMA user_version").fetchone()[0] != cls.SCHEMA
            or db.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            or db.execute("PRAGMA foreign_key_check").fetchone()):
            raise Problem("קובץ הנתונים פגום או אינו תואם לגרסה זו")
        if db.execute("SELECT COUNT(*) FROM sqlite_schema WHERE type='table' AND name IN "
                      "('settings','buildings','units','unit_status','fee_rates','categories','entries')").fetchone()[0] != 7:
            raise Problem("מבנה קובץ הנתונים אינו תקין")

    @contextmanager
    def write(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def rows(self, sql, *params):
        return self.db.execute(sql, params).fetchall()

    def get(self, key, default=""):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def save(self, **settings):
        self.db.executemany("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            settings.items())

    def set_password(self, password):
        if len(password) < 8:
            raise Problem("הסיסמה חייבת לכלול לפחות שמונה תווים")
        salt = os.urandom(16)
        self.save(salt=salt.hex(), password=password_hash(password, salt), failures=0, locked_until=0)

    def authenticate(self, password):
        if time.time() < float(self.get("locked_until", "0")):
            raise Problem("בוצעו ניסיונות רבים מדי. יש להמתין דקה")
        ok = hmac.compare_digest(self.get("password"), password_hash(password, bytes.fromhex(self.get("salt"))))
        with self.write():
            failures = 0 if ok else int(self.get("failures", "0")) + 1
            self.save(failures=0 if failures >= 5 else failures,
                      locked_until=time.time()+60 if failures >= 5 else 0)
        return ok

    def setup(self, name, complex_name, start, initial, password, backup, rate, split):
        start = valid_day(start)
        if not name.strip() or not complex_name.strip() or not backup.strip() or not split.strip():
            raise Problem("יש למלא שם ועד, שם מתחם, תיקיית גיבוי ומספר דירה מחולקת")
        if start > date.today().isoformat() or rate <= 0:
            raise Problem("יש להזין מועד התחלה עד היום ותעריף חיובי")
        with self.write():
            if self.get("start"):
                raise Problem("המערכת כבר הוגדרה")
            self.set_password(password)
            self.save(name=name, complex=complex_name, start=start, initial=initial, backup=backup, rate=rate)
            for building, count in ((14,6), (16,6), (18,8)):
                self.db.execute("INSERT INTO buildings VALUES (?,?)", (building,count))
                for slot in range(1, count + 1):
                    parts = ("א", "ב") if building == 16 and slot == 1 else ("",)
                    for index, part in enumerate(parts):
                        unit = self.db.execute("INSERT INTO units(building,slot,apartment,subunit) VALUES (?,?,?,?)",
                                               (building, slot*2+index, split.strip() if part else f'@{slot}', part)).lastrowid
                        self.db.execute("INSERT INTO unit_status VALUES (?,?,1)", (unit,start))
                        self.db.execute("INSERT INTO fee_rates VALUES (?,?,?)",
                                        (unit,start, (rate + (index == 0))//2 if part else rate))
            categories = {"expense": "חשמל|ניקיון|מעליות|גינון|תיקונים|תחזוקה|ביטוח|הוצאות כלליות|אחר",
                          "income": "הכנסות כלליות|אחר"}
            for kind, names in categories.items():
                self.db.executemany("INSERT INTO categories(kind,name) VALUES (?,?)",
                                    [(kind, name) for name in names.split("|")])

    def backup(self, folder):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / datetime.now().strftime("vaad-%Y%m%d-%H%M%S-%f.sqlite3")
        with closing(self.connect(target)) as destination:
            self.db.backup(destination)
            self.verify(destination)
        self.save(last_backup=datetime.now().isoformat(timespec="seconds"))
        return target

    def inspect_backup(self, source):
        with closing(self.connect(Path(source), readonly=True)) as candidate:
            self.verify(candidate)
            settings = dict(candidate.execute("SELECT key,value FROM settings"))
            if not all(settings.get(key) for key in ("start","password","salt","name","initial")):
                raise Problem("הגיבוי אינו כולל מערכת מוגדרת")

    def restore(self, source, safety_folder):
        self.inspect_backup(source)
        with tempfile.TemporaryDirectory(dir=self.path.parent) as directory:
            staged = Path(directory) / "restore.sqlite3"
            with closing(self.connect(Path(source), readonly=True)) as candidate, closing(self.connect(staged)) as copy:
                candidate.backup(copy)
                self.verify(copy)
            self.inspect_backup(staged)
            if self.get("start"):
                self.backup(safety_folder)
            self.db.close()
            try:
                os.replace(staged, self.path)
            finally:
                self.db = self.connect(self.path)

