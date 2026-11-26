"""Local SQLite storage, schema migrations, auth/RBAC, audit log, attachments, and backups."""

from contextlib import closing, contextmanager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
from uuid import uuid4
import zipfile

from .__version__ import __version__
from .seed_data import SHAHRAI_DATA

logger = logging.getLogger("vaad")

ROLES = {
    "admin": "מנהל ראשי",
    "member": "חבר ועד",
    "viewer": "צפייה בלבד",
}

PERMISSIONS = {
    "admin": {"view", "record_payment", "record_expense", "manage_units", "manage_suppliers",
              "manage_recurring", "reverse", "adjust", "bank_import", "attachments",
              "manage_rates", "manage_settings", "manage_users", "backup", "restore", "view_audit"},
    "member": {"view", "record_payment", "record_expense", "manage_units", "manage_suppliers",
               "manage_recurring", "bank_import", "attachments", "backup"},
    "viewer": {"view"},
}

EXPECTED_TABLES = (
    "settings", "buildings", "units", "unit_status", "fee_rates", "categories", "entries",
    "occupants", "suppliers", "recurring_expenses", "recurring_matches",
    "users", "audit_log", "attachments", "bank_imports", "backup_history",
    "cash_transfers", "excel_history", "compensation_checks",
)


def configure_logging(data_dir):
    log_dir = Path(data_dir) / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "vaad.log"
        root = logging.getLogger("vaad")
        if not any(isinstance(h, RotatingFileHandler) and Path(h.baseFilename) == log_file for h in root.handlers):
            handler = RotatingFileHandler(log_file, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
            root.addHandler(handler)
            root.setLevel(logging.INFO)
    except OSError:
        pass


class Problem(ValueError):
    pass


def money(value):
    try:
        text = str(value).strip().replace(",", "").replace("₪", "").replace("\u200e", "").replace("−", "-")
        amount = Decimal(text) * 100
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
    return hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1, maxmem=64 * 1024**2).hex()


def has_permission(role, perm):
    return perm in PERMISSIONS.get(role, set())


class Store:
    SCHEMA = 4
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
            version = 1
        if version == 1:
            migration = Path(__file__).with_name("002.sql").read_text(encoding="utf-8-sig")
            self.db.executescript(f"BEGIN IMMEDIATE; {migration} PRAGMA user_version=2; COMMIT;")
            version = 2
        if version == 2:
            migration = Path(__file__).with_name("003.sql").read_text(encoding="utf-8-sig")
            self.db.executescript(f"BEGIN IMMEDIATE; {migration} PRAGMA user_version=3; COMMIT;")
            self._migrate_legacy_admin()
            version = 3
        if version == 3:
            migration = Path(__file__).with_name("004.sql").read_text(encoding="utf-8-sig")
            self.db.executescript(f"BEGIN IMMEDIATE; {migration} PRAGMA user_version=4; COMMIT;")
            self._migrate_v4()
        self.verify(self.db)

    def _migrate_legacy_admin(self):
        """Migrate single-password settings from v1/v2 into a default admin user."""
        existing = self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        pwd = self.get("password")
        salt = self.get("salt")
        if existing == 0 and pwd and salt:
            with self.write():
                self.db.execute(
                    "INSERT INTO users(username,display_name,role,password_hash,salt,active) VALUES (?,?,?,?,?,1)",
                    ("admin", "מנהל ראשי", "admin", pwd, salt),
                )

    def _migrate_v4(self):
        """Fix Shahrai spelling (שחריי -> שחראי) and initialize split bank/cash opening balances."""
        with self.write():
            for key in ("name", "complex", "address"):
                val = self.get(key)
                if "שחריי" in val:
                    self.save(**{key: val.replace("שחריי", "שחראי")})
            if self.get("initial") != "" and self.get("initial_bank") == "":
                self.save(initial_bank=self.get("initial", "0"), initial_cash="0")

    @property
    def attachments_dir(self):
        folder = self.path.parent / "attachments"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    @staticmethod
    def connect(path, readonly=False):
        db = sqlite3.connect(
            path.absolute().as_uri() + "?mode=ro" if readonly else path,
            uri=readonly,
            isolation_level=None,
            timeout=10,
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @classmethod
    def verify(cls, db):
        if (
            db.execute("PRAGMA application_id").fetchone()[0] != cls.APP_ID
            or db.execute("PRAGMA user_version").fetchone()[0] != cls.SCHEMA
            or db.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            or db.execute("PRAGMA foreign_key_check").fetchone()
        ):
            raise Problem("קובץ הנתונים פגום או אינו תואם לגרסה זו")
        placeholders = ",".join("?" for _ in EXPECTED_TABLES)
        count = db.execute(
            f"SELECT COUNT(*) FROM sqlite_schema WHERE type='table' AND name IN ({placeholders})",
            EXPECTED_TABLES,
        ).fetchone()[0]
        if count != len(EXPECTED_TABLES):
            raise Problem("מבנה קובץ הנתונים אינו תקין")

    @contextmanager
    def write(self):
        if self.db.in_transaction:
            yield
            return
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
        with self.write():
            self.db.executemany(
                "INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                [(k, str(v)) for k, v in settings.items()],
            )

    # ------------------------------------------------------------------
    # Authentication, Users & RBAC
    # ------------------------------------------------------------------

    def set_password(self, password, username="admin"):
        if len(password) < 8:
            raise Problem("הסיסמה חייבת לכלול לפחות שמונה תווים")
        salt = os.urandom(16)
        digest = password_hash(password, salt)
        with self.write():
            user = self.rows("SELECT id FROM users WHERE username=?", username)
            if user:
                self.db.execute(
                    "UPDATE users SET password_hash=?,salt=?,failures=0,locked_until=0 WHERE id=?",
                    (digest, salt.hex(), user[0]["id"]),
                )
            else:
                self.db.execute(
                    "INSERT INTO users(username,display_name,role,password_hash,salt,active) VALUES (?,?,?,?,?,1)",
                    (username, "מנהל ראשי", "admin", digest, salt.hex()),
                )
            if username == "admin":
                self.save(salt=salt.hex(), password=digest, failures=0, locked_until=0)

    def list_users(self, active_only=False):
        sql = "SELECT id,username,display_name,role,active,created_at FROM users"
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY CASE role WHEN 'admin' THEN 0 WHEN 'member' THEN 1 ELSE 2 END, username"
        return self.rows(sql)

    def create_user(self, username, display_name, role, password, actor=None):
        username = username.strip().lower()
        display_name = display_name.strip()
        if not username or not display_name:
            raise Problem("יש להזין שם משתמש ושם תצוגה")
        if role not in ROLES:
            raise Problem("תפקיד משתמש אינו תקין")
        if len(password) < 8:
            raise Problem("הסיסמה חייבת לכלול לפחות שמונה תווים")
        salt = os.urandom(16)
        digest = password_hash(password, salt)
        with self.write():
            user_id = self.db.execute(
                "INSERT INTO users(username,display_name,role,password_hash,salt,active) VALUES (?,?,?,?,?,1)",
                (username, display_name, role, digest, salt.hex()),
            ).lastrowid
            self.log_action(actor, "create_user", "user", user_id, f"{username} ({ROLES[role]})")
            return user_id

    def update_user(self, user_id, display_name, role, active, actor=None):
        display_name = display_name.strip()
        if not display_name or role not in ROLES:
            raise Problem("יש להזין שם תצוגה ותפקיד תקין")
        with self.write():
            target = self.rows("SELECT * FROM users WHERE id=?", user_id)
            if not target:
                raise Problem("המשתמש לא נמצא")
            target = target[0]
            if target["role"] == "admin" and (role != "admin" or not active):
                other_admins = self.rows(
                    "SELECT COUNT(*) c FROM users WHERE role='admin' AND active=1 AND id<>?", user_id
                )[0]["c"]
                if other_admins == 0:
                    raise Problem("חייב להישאר לפחות מנהל ראשי פעיל אחד במערכת")
            self.db.execute(
                "UPDATE users SET display_name=?,role=?,active=? WHERE id=?",
                (display_name, role, int(active), user_id),
            )
            self.log_action(actor, "update_user", "user", user_id, f"{target['username']} -> {ROLES[role]}, active={int(active)}")

    def reset_user_password(self, user_id, new_password, actor=None):
        if len(new_password) < 8:
            raise Problem("הסיסמה חייבת לכלול לפחות שמונה תווים")
        salt = os.urandom(16)
        digest = password_hash(new_password, salt)
        with self.write():
            target = self.rows("SELECT username FROM users WHERE id=?", user_id)
            if not target:
                raise Problem("המשתמש לא נמצא")
            self.db.execute(
                "UPDATE users SET password_hash=?,salt=?,failures=0,locked_until=0 WHERE id=?",
                (digest, salt.hex(), user_id),
            )
            if target[0]["username"] == "admin":
                self.save(salt=salt.hex(), password=digest, failures=0, locked_until=0)
            self.log_action(actor, "reset_password", "user", user_id, target[0]["username"])

    def authenticate_user(self, username, password):
        rows = self.rows("SELECT * FROM users WHERE username=? AND active=1", username.strip().lower())
        if not rows:
            return None
        user = rows[0]
        if time.time() < float(user["locked_until"] or 0):
            raise Problem("בוצעו ניסיונות רבים מדי. יש להמתין דקה")
        ok = hmac.compare_digest(user["password_hash"], password_hash(password, bytes.fromhex(user["salt"])))
        with self.write():
            failures = 0 if ok else int(user["failures"] or 0) + 1
            locked_until = time.time() + 60 if failures >= 5 else 0
            self.db.execute(
                "UPDATE users SET failures=?,locked_until=? WHERE id=?",
                (0 if failures >= 5 else failures, locked_until, user["id"]),
            )
            if user["username"] == "admin":
                self.save(failures=0 if failures >= 5 else failures, locked_until=locked_until)
            if ok:
                self.log_action(dict(user), "login", "user", user["id"], "כניסה למערכת")
        return dict(user) if ok else None

    def authenticate(self, password, username=None):
        """Backward-compatible authentication helper returning bool."""
        if username:
            return self.authenticate_user(username, password) is not None
        users = self.list_users(active_only=True)
        if users:
            primary = next((u for u in users if u["username"] == "admin"), users[0])
            return self.authenticate_user(primary["username"], password) is not None
        if time.time() < float(self.get("locked_until", "0")):
            raise Problem("בוצעו ניסיונות רבים מדי. יש להמתין דקה")
        ok = hmac.compare_digest(self.get("password"), password_hash(password, bytes.fromhex(self.get("salt"))))
        with self.write():
            failures = 0 if ok else int(self.get("failures", "0")) + 1
            self.save(
                failures=0 if failures >= 5 else failures,
                locked_until=time.time() + 60 if failures >= 5 else 0,
            )
        return ok

    # ------------------------------------------------------------------
    # Audit Log
    # ------------------------------------------------------------------

    def log_action(self, actor, action, entity_type="", entity_id="", details=""):
        user_id = actor.get("id") if isinstance(actor, dict) else None
        username = (actor.get("display_name") or actor.get("username") or "") if isinstance(actor, dict) else str(actor or "")
        with self.write():
            self.db.execute(
                "INSERT INTO audit_log(user_id,username,action,entity_type,entity_id,details) VALUES (?,?,?,?,?,?)",
                (user_id, username, action, entity_type, str(entity_id or ""), details),
            )

    def audit_entries(self, limit=300, query=""):
        rows = self.rows("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", limit)
        if not query.strip():
            return rows
        needle = query.strip().casefold()
        return [
            r for r in rows
            if needle in f"{r['username']} {r['action']} {r['entity_type']} {r['entity_id']} {r['details']}".casefold()
        ]

    # ------------------------------------------------------------------
    # Attachments (Invoices & Receipts)
    # ------------------------------------------------------------------

    def add_attachment(self, entry_id, source_path, actor=None):
        source = Path(source_path)
        if not source.is_file():
            raise Problem("הקובץ שנבחר לא נמצא")
        if not self.rows("SELECT id FROM entries WHERE id=?", entry_id):
            raise Problem("התנועה הכספית לא נמצאה")
        ext = source.suffix.lower()[:12]
        stored_name = f"entry-{entry_id}-{uuid4().hex[:12]}{ext}"
        destination = self.attachments_dir / stored_name
        shutil.copy2(source, destination)
        size_bytes = destination.stat().st_size
        uploader = (actor.get("display_name") or actor.get("username") or "") if isinstance(actor, dict) else ""
        try:
            with self.write():
                att_id = self.db.execute(
                    "INSERT INTO attachments(entry,filename,stored_name,size_bytes,uploaded_by) VALUES (?,?,?,?,?)",
                    (entry_id, source.name, stored_name, size_bytes, uploader),
                ).lastrowid
                self.log_action(actor, "add_attachment", "entry", entry_id, source.name)
                return att_id
        except BaseException:
            destination.unlink(missing_ok=True)
            raise

    def list_attachments(self, entry_id=None, supplier_id=None):
        if entry_id is not None:
            return self.rows("SELECT * FROM attachments WHERE entry=? ORDER BY id DESC", entry_id)
        if supplier_id is not None:
            return self.rows(
                """
                SELECT a.*, e.day entry_day, e.description entry_description, e.cash entry_cash
                FROM attachments a
                JOIN entries e ON e.id = a.entry
                WHERE e.supplier = ?
                ORDER BY e.day DESC, a.id DESC
                """,
                supplier_id,
            )
        return self.rows("SELECT * FROM attachments ORDER BY id DESC")

    def attachment_path(self, attachment_id):
        rows = self.rows("SELECT * FROM attachments WHERE id=?", attachment_id)
        if not rows:
            raise Problem("הקובץ המצורף לא נמצא")
        path = self.attachments_dir / rows[0]["stored_name"]
        if not path.is_file():
            raise Problem("הקובץ המצורף חסר בתיקיית הנתונים")
        return path, rows[0]

    def delete_attachment(self, attachment_id, actor=None):
        rows = self.rows("SELECT * FROM attachments WHERE id=?", attachment_id)
        if not rows:
            raise Problem("הקובץ המצורף לא נמצא")
        row = rows[0]
        with self.write():
            self.db.execute("DELETE FROM attachments WHERE id=?", (attachment_id,))
            self.log_action(actor, "delete_attachment", "entry", row["entry"], row["filename"])
        (self.attachments_dir / row["stored_name"]).unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Initial Setup (with default Shahrai 14/16/18 units & Bank/Cash split)
    # ------------------------------------------------------------------

    def setup(self, name, complex_name, start, initial, password, backup, rate, split,
              initial_bank=None, initial_cash=None, seed_shahrai_names=True):
        start = valid_day(start)
        if not name.strip() or not complex_name.strip() or not backup.strip() or not split.strip():
            raise Problem("יש למלא שם ועד, שם מתחם, תיקיית גיבוי ומספר דירה מחולקת")
        if start > date.today().isoformat() or rate <= 0:
            raise Problem("יש להזין מועד התחלה עד היום ותעריף חיובי")
        if initial_bank is None and initial_cash is None:
            bank_val = int(initial)
            cash_val = 0
        else:
            bank_val = int(initial_bank or 0)
            cash_val = int(initial_cash or 0)
            initial = bank_val + cash_val

        with self.write():
            if self.get("start"):
                raise Problem("המערכת כבר הוגדרה")
            self.set_password(password, username="admin")
            self.save(
                name=name.strip(),
                complex=complex_name.strip(),
                start=start,
                initial=initial,
                initial_bank=bank_val,
                initial_cash=cash_val,
                backup=backup.strip(),
                rate=rate,
                auto_backup="1",
                auto_backup_keep="10",
                auto_lock_minutes="15",
            )
            for building, count in ((14, 6), (16, 6), (18, 8)):
                self.db.execute("INSERT INTO buildings VALUES (?,?)", (building, count))

            for item in SHAHRAI_DATA:
                bldg, slot, apt_label, subunit, resident_name, prev_name, default_rate, *_ = item
                is_split = bool(subunit)
                unit_rate = (rate + (subunit == "א")) // 2 if is_split else rate
                if seed_shahrai_names:
                    apt = split.strip() if is_split else apt_label
                    owner_name = resident_name
                    notes = f"דייר קודם (2025): {prev_name}" if prev_name else ""
                else:
                    apt = split.strip() if is_split else f"@{slot // 2}"
                    owner_name = ""
                    notes = ""
                unit_id = self.db.execute(
                    "INSERT INTO units(building,slot,apartment,subunit,owner,notes) VALUES (?,?,?,?,?,?)",
                    (bldg, slot, apt, subunit, owner_name, notes),
                ).lastrowid
                self.db.execute("INSERT INTO unit_status VALUES (?,?,1)", (unit_id, start))
                self.db.execute("INSERT INTO fee_rates VALUES (?,?,?)", (unit_id, start, unit_rate))
                if seed_shahrai_names and prev_name:
                    self.db.execute(
                        "INSERT INTO occupants(unit,role,name,arrived,departed,notes) VALUES (?,'owner',?,'2025-01-01','2025-12-31','רישום מהאקסל 2025')",
                        (unit_id, prev_name),
                    )

            categories = {
                "expense": "חשמל|ניקיון|מעליות|גינון|תיקונים|תחזוקה|ביטוח|הוצאות כלליות|אחר",
                "income": "הכנסות כלליות|אחר",
            }
            for kind, names in categories.items():
                self.db.executemany(
                    "INSERT INTO categories(kind,name) VALUES (?,?)",
                    [(kind, cat_name) for cat_name in names.split("|")],
                )
            self.log_action({"username": "admin", "display_name": "מנהל ראשי"}, "setup", "system", "", complex_name.strip())

    # ------------------------------------------------------------------
    # Backup, Bundle (DB + Attachments), Auto-Backup & Restore
    # ------------------------------------------------------------------

    def backup(self, folder, kind="manual"):
        """Create a verified standalone SQLite backup snapshot."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / datetime.now().strftime("vaad-%Y%m%d-%H%M%S-%f.sqlite3")
        with closing(self.connect(target)) as destination:
            self.db.backup(destination)
            self.verify(destination)
        now_iso = datetime.now().isoformat(timespec="seconds")
        with self.write():
            self.save(last_backup=now_iso)
            self.db.execute(
                "INSERT INTO backup_history(path,kind,size_bytes,attachments_count,status) VALUES (?,?,?,?,?)",
                (str(target), kind, target.stat().st_size, 0, "ok"),
            )
        return target

    def backup_bundle(self, folder, kind="manual", actor=None):
        """Create a complete ZIP backup containing verified SQLite DB + all attachments + manifest."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        prefix = "vaad-auto" if kind == "auto" else "vaad-backup"
        target = folder / f"{prefix}-{stamp}.zip"
        attachments = list(self.rows("SELECT stored_name, filename FROM attachments"))
        with tempfile.TemporaryDirectory(dir=self.path.parent) as tmpdir:
            staged_db = Path(tmpdir) / "vaad.sqlite3"
            with closing(self.connect(staged_db)) as destination:
                self.db.backup(destination)
                self.verify(destination)
            bundled_files = []
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(staged_db, "vaad.sqlite3")
                for att in attachments:
                    src = self.attachments_dir / att["stored_name"]
                    if src.is_file():
                        zf.write(src, f"attachments/{att['stored_name']}")
                        bundled_files.append(att["stored_name"])
                manifest = {
                    "app": "VaadBayt",
                    "version": __version__,
                    "schema": self.SCHEMA,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "kind": kind,
                    "attachments_count": len(bundled_files),
                }
                zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        now_iso = datetime.now().isoformat(timespec="seconds")
        size_bytes = target.stat().st_size
        with self.write():
            self.save(last_backup=now_iso)
            self.db.execute(
                "INSERT INTO backup_history(path,kind,size_bytes,attachments_count,status) VALUES (?,?,?,?,?)",
                (str(target), kind, size_bytes, len(bundled_files), "ok"),
            )
            self.log_action(actor, "backup", "backup", target.name, f"{kind} · {len(bundled_files)} קבצים")
        if kind == "auto":
            self._prune_auto_backups(folder)
        return target

    def _prune_auto_backups(self, folder):
        try:
            keep = max(1, int(self.get("auto_backup_keep", "10")))
        except ValueError:
            keep = 10
        existing = sorted(Path(folder).glob("vaad-auto-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in existing[keep:]:
            old.unlink(missing_ok=True)

    def maybe_auto_backup(self, force=False, actor=None):
        if self.get("auto_backup", "1") != "1" or not self.get("start"):
            return None
        folder = self.get("backup", "").strip()
        if not folder:
            return None
        last = self.get("last_backup", "")
        if not force and last and last[:10] == date.today().isoformat():
            return None
        try:
            return self.backup_bundle(folder, kind="auto", actor=actor)
        except OSError as exc:
            logger.warning("Auto-backup failed: %s", exc)
            return None

    def backup_history(self, limit=50):
        return self.rows("SELECT * FROM backup_history ORDER BY id DESC LIMIT ?", limit)

    def inspect_backup(self, source):
        source = Path(source)
        if not source.is_file():
            raise Problem("קובץ הגיבוי לא נמצא")
        if zipfile.is_zipfile(source):
            with zipfile.ZipFile(source, "r") as zf:
                if "vaad.sqlite3" not in zf.namelist():
                    raise Problem("ארכיון הגיבוי אינו כולל מסד נתונים תקין")
                with tempfile.TemporaryDirectory(dir=self.path.parent) as tmpdir:
                    extracted = Path(tmpdir) / "vaad.sqlite3"
                    extracted.write_bytes(zf.read("vaad.sqlite3"))
                    self._inspect_sqlite(extracted)
            return
        self._inspect_sqlite(source)

    def _inspect_sqlite(self, source):
        with closing(self.connect(Path(source), readonly=True)) as candidate:
            version = candidate.execute("PRAGMA user_version").fetchone()[0]
            if (
                candidate.execute("PRAGMA application_id").fetchone()[0] != self.APP_ID
                or version not in (1, 2, 3, self.SCHEMA)
                or candidate.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                or candidate.execute("PRAGMA foreign_key_check").fetchone()
            ):
                raise Problem("הגיבוי פגום או אינו תואם לגרסה זו")
            settings = dict(candidate.execute("SELECT key,value FROM settings"))
            if not all(settings.get(key) for key in ("start", "name", "initial")):
                raise Problem("הגיבוי אינו כולל מערכת מוגדרת")
            has_legacy_pwd = bool(settings.get("password") and settings.get("salt"))
            has_users = False
            if version >= 3:
                has_users = candidate.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0] > 0
            if not (has_legacy_pwd or has_users):
                raise Problem("הגיבוי אינו כולל פרטי גישה תקינים")

    def restore(self, source, safety_folder):
        source = Path(source)
        self.inspect_backup(source)
        with tempfile.TemporaryDirectory(dir=self.path.parent) as directory:
            staged = Path(directory) / "restore.sqlite3"
            staged_attachments = Path(directory) / "attachments"
            has_attachment_bundle = False
            if zipfile.is_zipfile(source):
                with zipfile.ZipFile(source, "r") as zf:
                    staged.write_bytes(zf.read("vaad.sqlite3"))
                    staged_attachments.mkdir(exist_ok=True)
                    has_attachment_bundle = True
                    for member in zf.namelist():
                        if member.startswith("attachments/") and not member.endswith("/"):
                            name = Path(member).name
                            if name:
                                (staged_attachments / name).write_bytes(zf.read(member))
            else:
                with closing(self.connect(source, readonly=True)) as candidate, closing(self.connect(staged)) as copy:
                    candidate.backup(copy)
            with closing(Store(staged)):
                pass
            self._inspect_sqlite(staged)
            if self.get("start"):
                if zipfile.is_zipfile(source):
                    self.backup_bundle(safety_folder, kind="pre-restore")
                else:
                    self.backup(safety_folder, kind="pre-restore")
            self.db.close()
            try:
                os.replace(staged, self.path)
                if has_attachment_bundle:
                    att_dir = self.attachments_dir
                    for old in att_dir.iterdir():
                        if old.is_file():
                            old.unlink(missing_ok=True)
                    for item in staged_attachments.iterdir():
                        if item.is_file():
                            shutil.copy2(item, att_dir / item.name)
            finally:
                self.db = self.connect(self.path)

    def close(self):
        self.db.close()
