"""Financial ledger, Bank/Cash split, transfers, units, occupants, suppliers, recurring, and annual matrix."""

from calendar import monthrange
from datetime import date
from uuid import uuid4

from .seed_data import SHAHRAI_DATA
from .store import Problem, month_next, valid_day

METHODS = ("מזומן", "העברה בנקאית", "המחאה", "אחר")
ACCOUNTS = {"bank": "בנק", "cash": "מזומן"}
LABELS = dict(
    opening="יתרת פתיחה",
    charge="חיוב חודשי",
    adjustment="תיקון חיוב",
    payment="תשלום דייר",
    expense="הוצאה",
    income="הכנסה אחרת",
    reversal="ביטול פעולה",
)


def default_account(method):
    return "cash" if method == "מזומן" else "bank"


class Ledger:
    def __init__(self, store):
        self.store = store

    # ------------------------------------------------------------------
    # Units & Occupants
    # ------------------------------------------------------------------

    def units(self, day=None):
        day = day or date.today().isoformat()
        return self.store.rows(
            """
            SELECT u.*, COALESCE((SELECT active FROM unit_status WHERE unit=u.id AND effective<=?
               ORDER BY effective DESC LIMIT 1),0) active,
               (SELECT amount FROM fee_rates WHERE unit=u.id AND effective<=? ORDER BY effective DESC LIMIT 1) rate,
               (SELECT effective FROM fee_rates WHERE unit=u.id AND effective<=? ORDER BY effective DESC LIMIT 1) effective
            FROM units u ORDER BY building,slot
            """,
            day, day, day,
        )

    def add_unit(self, building, apartment, subunit, rate, owner="", tenant="",
                 phone="", email="", notes="", start=None, actor=None):
        building = int(building)
        apartment = apartment.strip()
        subunit = subunit.strip()
        if not apartment or apartment.startswith("@"):
            raise Problem("יש להזין מספר דירה תקין")
        if rate < 0:
            raise Problem("יש להזין תעריף שאינו שלילי")
        effective = valid_day(start or date.today().isoformat())
        with self.store.write():
            if not self.store.rows("SELECT id FROM buildings WHERE id=?", building):
                raise Problem("מספר הבניין אינו קיים במערכת")
            max_slot = self.store.rows("SELECT COALESCE(MAX(slot),0) s FROM units WHERE building=?", building)[0]["s"]
            unit_id = self.store.db.execute(
                "INSERT INTO units(building,slot,apartment,subunit,owner,tenant,phone,email,notes) VALUES (?,?,?,?,?,?,?,?,?)",
                (building, max_slot + 2, apartment, subunit, owner.strip(), tenant.strip(), phone.strip(), email.strip(), notes.strip()),
            ).lastrowid
            self.store.db.execute("INSERT INTO unit_status VALUES (?,?,1)", (unit_id, effective))
            self.store.db.execute("INSERT INTO fee_rates VALUES (?,?,?)", (unit_id, effective, rate))
            self.store.log_action(actor, "add_unit", "unit", unit_id, f"{building}/{apartment} {subunit}".strip())
            return unit_id

    def unit_update(self, unit, fields, active, actor=None):
        fields = tuple(value.strip() for value in fields)
        with self.store.write():
            original = self.store.rows("SELECT * FROM units WHERE id=?", unit)[0]
            if original["subunit"] and not fields[0]:
                raise Problem("יש להזין מספר לדירה המחולקת")
            if fields[0].startswith("@"):
                raise Problem("מספר הדירה אינו תקין")
            if original["subunit"] and fields[0] != original["apartment"]:
                self.store.db.execute(
                    "UPDATE units SET apartment=? WHERE building=? AND subunit<>''",
                    (fields[0], original["building"]),
                )
            apartment = fields[0] or f"@{original['slot'] // 2}"
            self.store.db.execute(
                "UPDATE units SET apartment=?,owner=?,tenant=?,phone=?,email=?,notes=? WHERE id=?",
                (apartment, *fields[1:], unit),
            )
            today_iso = date.today().isoformat()
            self.store.db.execute(
                "INSERT INTO unit_status VALUES (?,?,?) ON CONFLICT(unit,effective) "
                "DO UPDATE SET active=excluded.active",
                (unit, today_iso, int(active)),
            )
            self.store.log_action(actor, "update_unit", "unit", unit, f"דירה {apartment} · פעילה={int(active)}")

    def replace_resident(self, unit_id, role, name, phone, email, day, notes="", actor=None):
        day = valid_day(day)
        name = name.strip()
        if role not in ("owner", "tenant"):
            raise Problem("תפקיד אינו תקין")
        if day > date.today().isoformat() or not name:
            raise Problem("יש להזין שם ותאריך שאינו עתידי")
        with self.store.write():
            rows = self.store.rows("SELECT * FROM units WHERE id=?", unit_id)
            if not rows:
                raise Problem("היחידה לא נמצאה")
            row = rows[0]
            previous = row[role]
            if previous:
                prev_departed = self.store.rows(
                    "SELECT MAX(departed) d FROM occupants WHERE unit=? AND role=?", unit_id, role
                )[0]["d"]
                arrived = prev_departed or self.store.get("start") or day
                if arrived > day:
                    arrived = day
                self.store.db.execute(
                    "INSERT INTO occupants(unit,role,name,phone,email,arrived,departed,notes) VALUES (?,?,?,?,?,?,?,?)",
                    (unit_id, role, previous, row["phone"], row["email"], arrived, day, notes.strip()),
                )
            self.store.db.execute(
                f"UPDATE units SET {role}=?,phone=?,email=? WHERE id=?",
                (name, phone.strip(), email.strip(), unit_id),
            )
            self.store.log_action(actor, "replace_resident", "unit", unit_id, f"{role}: {previous or '—'} -> {name}")

    def unit_occupants(self, unit_id):
        return self.store.rows(
            "SELECT * FROM occupants WHERE unit=? ORDER BY departed DESC, arrived DESC, id DESC",
            unit_id,
        )

    def rate(self, unit, day, amount, split=False, actor=None):
        day = valid_day(day)
        if day < date.today().isoformat() or amount < 0:
            raise Problem("יש לבחור תאריך מהיום ואילך ותעריף שאינו שלילי")
        with self.store.write():
            if unit:
                rates = [(unit, day, amount)]
            else:
                rates = [
                    (u["id"], day, (amount + (u["subunit"] == "א")) // 2 if u["subunit"] else amount)
                    for u in self.units(day)
                ]
                self.store.save(rate=amount)
            self.store.db.executemany(
                "INSERT INTO fee_rates VALUES (?,?,?) ON CONFLICT(unit,effective) "
                "DO UPDATE SET amount=excluded.amount",
                rates,
            )
            self.store.log_action(actor, "change_rate", "unit" if unit else "system", unit or "all", f"{amount} אג׳ מתאריך {day}")

    # ------------------------------------------------------------------
    # Monthly Charges & Accounts (Targeted for_period + FIFO)
    # ------------------------------------------------------------------

    def generate(self, through=None):
        through = valid_day(through or date.today().isoformat())
        start = self.store.get("start")
        if not start:
            return
        with self.store.write():
            period = max(start[:7], self.store.get("generated_through", start[:7]))
            while period <= through[:7] and start <= through:
                day = max(period + "-01", start)
                for unit in self.units(day):
                    if unit["active"] and unit["rate"] is not None:
                        self.store.db.execute(
                            """
                            INSERT INTO entries(unit,day,kind,debit,period) VALUES (?,?,'charge',?,?)
                            ON CONFLICT(unit,period) WHERE kind='charge' DO NOTHING
                            """,
                            (unit["id"], day, unit["rate"], period),
                        )
                self.store.save(generated_through=period)
                period = month_next(period)

    def _day(self, day):
        day = valid_day(day)
        if not self.store.get("start") or not self.store.get("start") <= day <= date.today().isoformat():
            raise Problem("התאריך חייב להיות בין תחילת הניהול להיום")
        return day

    def history(self, unit):
        return self.store.rows("SELECT * FROM entries WHERE unit=? ORDER BY day,id", unit)

    def account(self, unit, through=None):
        through = through or date.today().isoformat()
        rows = [row for row in self.history(unit) if row["day"] <= through]
        adjustments = {}
        targeted = {}
        for row in rows:
            if row["kind"] == "adjustment":
                adjustments[row["charge"]] = adjustments.get(row["charge"], 0) + row["debit"]
            elif row["kind"] in ("payment", "reversal") and row["for_period"]:
                fp = row["for_period"]
                targeted[fp] = targeted.get(fp, 0) + (-row["debit"])

        through_balance = sum(row["debit"] for row in rows)
        # General credit: untargeted payments/reversals + opening credit
        credit = sum(
            -row["debit"]
            for row in rows
            if (row["kind"] in ("payment", "reversal") and not row["for_period"])
            or (row["kind"] == "opening" and row["debit"] < 0)
        )

        # Apply targeted credits to existing charges first; track future-period prepaid separately
        charged_periods = {row["period"] for row in rows if row["kind"] == "charge"}
        future_paid = {}
        applied_targeted = {}
        for fp, amt in targeted.items():
            if amt <= 0:
                continue
            if fp in charged_periods:
                applied_targeted[fp] = amt
            else:
                future_paid[fp] = amt

        charges = {}
        initial = next((row for row in rows if row["kind"] == "opening" and row["debit"] > 0), None)
        opening = max(0, initial["debit"] - credit) if initial else 0
        if initial:
            credit = max(0, credit - initial["debit"])

        # First pass: apply targeted credits directly to their period; overflow goes to general credit
        overflow = 0
        for row in rows:
            if row["kind"] == "charge":
                due = row["debit"] + adjustments.get(row["id"], 0)
                t_amt = applied_targeted.get(row["period"], 0)
                direct = min(t_amt, due)
                overflow += max(0, t_amt - due)
                charges[row["period"]] = dict(id=row["id"], day=row["day"], due=due, paid=direct, left=due - direct)
        credit += overflow

        # Second pass: allocate general credit FIFO across remaining unpaid charges
        oldest = initial["day"] if opening else ""
        for row in rows:
            if row["kind"] == "charge":
                c = charges[row["period"]]
                extra = min(credit, c["left"])
                credit -= extra
                c["paid"] += extra
                c["left"] -= extra
                if c["left"] > 0 and not oldest:
                    oldest = row["day"]

        total_credit = credit + sum(future_paid.values())
        unpaid_total = opening + sum(c["left"] for c in charges.values())
        return dict(
            balance=through_balance,
            credit=total_credit,
            charges=charges,
            opening=opening,
            oldest=oldest,
            future_paid=future_paid,
            unpaid_total=unpaid_total,
        )

    def opening(self, unit, amount, actor=None):
        with self.store.write():
            entry_id = self.store.db.execute(
                "INSERT INTO entries(unit,day,kind,debit) VALUES (?,?,'opening',?)",
                (unit, self.store.get("start"), amount),
            ).lastrowid
            self.store.log_action(actor, "opening_balance", "unit", unit, f"{amount} אג׳")
            return entry_id

    def adjust(self, unit, period, amount, reason, actor=None):
        if amount < 0 or not reason.strip():
            raise Problem("יש להזין סכום שאינו שלילי וסיבה")
        with self.store.write():
            charge = self.account(unit)["charges"].get(period)
            if not charge:
                raise Problem("אין חיוב בחודש זה")
            entry_id = self.store.db.execute(
                "INSERT INTO entries(unit,day,kind,debit,charge,notes) VALUES (?,?,'adjustment',?,?,?)",
                (unit, date.today().isoformat(), amount - charge["due"], charge["id"], reason.strip()),
            ).lastrowid
            self.store.log_action(actor, "adjust_charge", "unit", unit, f"{period} -> {amount} אג׳ ({reason.strip()})")
            return entry_id

    # ------------------------------------------------------------------
    # Posting, Quick Multi-Month Payment & Reversals
    # ------------------------------------------------------------------

    def post(self, kind, amount, day, method, token, unit=None, category=None, party="",
             description="", reference="", notes="", allow_duplicate=False, supplier=None,
             actor=None, account=None, for_period=None):
        day = self._day(day)
        if kind not in ("payment", "expense", "income") or not isinstance(amount, int) or amount <= 0 or method not in METHODS or not token:
            raise Problem("יש למלא סכום חיובי ואמצעי תשלום")
        acct = account or default_account(method)
        if acct not in ACCOUNTS:
            raise Problem("יש לבחור קופה תקינה (בנק או מזומן)")
        with self.store.write():
            existing = self.store.rows("SELECT id FROM entries WHERE token=?", token)
            if existing:
                return existing[0]["id"]
            if kind == "payment":
                if not unit or not self.store.rows("SELECT id FROM units WHERE id=?", unit):
                    raise Problem("יש לבחור יחידת תשלום")
                if not allow_duplicate and self.store.rows(
                    """
                    SELECT e.id FROM entries e LEFT JOIN entries r ON r.original=e.id
                    WHERE e.kind='payment' AND e.unit=? AND e.day=? AND e.cash=? AND e.method=? AND r.id IS NULL
                    """,
                    unit, day, amount, method,
                ):
                    raise Problem("נמצא תשלום דומה")
            else:
                if not (
                    party.strip()
                    and description.strip()
                    and self.store.rows("SELECT id FROM categories WHERE id=? AND kind=? AND active=1", category, kind)
                ):
                    raise Problem("יש להזין שם, תיאור וקטגוריה פעילה")
            entry_id = self.store.db.execute(
                """
                INSERT INTO entries(kind,day,unit,debit,cash,category,method,party,description,reference,notes,token,supplier,account,for_period)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    kind, day, unit,
                    -amount if kind == "payment" else 0,
                    -amount if kind == "expense" else amount,
                    category, method, party.strip(), description.strip(), reference.strip(),
                    notes.strip(), token, supplier, acct, for_period,
                ),
            ).lastrowid
            self.store.log_action(actor, f"post_{kind}", "entry", entry_id, f"{amount} אג׳ · {ACCOUNTS[acct]} · {party.strip() or f'יחידה {unit}'}")
            return entry_id

    def quick_pay_months(self, unit_id, periods, day, method, account=None, party="", reference="", notes="", actor=None):
        """Record payment for one or more specific monthly periods in a single transaction."""
        if not periods:
            raise Problem("יש לבחור לפחות חודש אחד לתשלום")
        day = self._day(day)
        acct = account or default_account(method)
        unit_rows = [u for u in self.units(day) if u["id"] == unit_id]
        if not unit_rows:
            raise Problem("היחידה לא נמצאה")
        unit = unit_rows[0]
        acc_info = self.account(unit_id)
        created = []
        with self.store.write():
            for period in sorted(periods):
                charge = acc_info["charges"].get(period)
                due_amt = charge["left"] if charge else (unit["rate"] or 10000)
                if due_amt <= 0:
                    continue
                note_txt = f"תשלום עבור {period[5:]}/{period[:4]}" + (f" · {notes.strip()}" if notes.strip() else "")
                eid = self.post(
                    "payment", due_amt, day, method, f"quick-{uuid4().hex}",
                    unit=unit_id, party=party or unit["tenant"] or unit["owner"],
                    reference=reference, notes=note_txt, allow_duplicate=True,
                    actor=actor, account=acct, for_period=period,
                )
                created.append(eid)
        if not created:
            raise Problem("החודשים שנבחרו כבר שולמו במלואם")
        return created

    def reverse(self, entry, reason, day=None, actor=None):
        day = self._day(day or date.today().isoformat())
        with self.store.write():
            rows = self.store.rows("SELECT * FROM entries WHERE id=? AND kind IN ('payment','expense','income')", entry)
            if (
                not rows
                or not reason.strip()
                or day < rows[0]["day"]
                or self.store.rows("SELECT id FROM entries WHERE original=?", entry)
            ):
                raise Problem("לא ניתן לבטל את הפעולה. יש לבדוק את הפעולה, התאריך והסיבה")
            row = rows[0]
            rev_id = self.store.db.execute(
                """
                INSERT INTO entries(kind,day,unit,debit,cash,original,category,method,party,description,notes,supplier,account,for_period)
                VALUES ('reversal',?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    day, row["unit"], -row["debit"], -row["cash"], entry, row["category"],
                    row["method"], row["party"], row["description"], reason.strip(),
                    row["supplier"], row["account"], row["for_period"],
                ),
            ).lastrowid
            self.store.log_action(actor, "reverse_entry", "entry", entry, f"בוטל ע״י #{rev_id}: {reason.strip()}")
            return rev_id

    # ------------------------------------------------------------------
    # Bank vs Cash Split & Internal Transfers
    # ------------------------------------------------------------------

    def balances(self, through=None):
        """Return exact split balances: {total, bank, cash}."""
        bank = int(self.store.get("initial_bank", self.store.get("initial", "0")) or "0")
        cash = int(self.store.get("initial_cash", "0") or "0")
        where = "WHERE cash<>0 AND day<=?" if through else "WHERE cash<>0"
        params = (through,) if through else ()
        for row in self.store.rows(f"SELECT account, COALESCE(SUM(cash),0) s FROM entries {where} GROUP BY account", *params):
            if row["account"] == "cash":
                cash += row["s"]
            else:
                bank += row["s"]
        t_where = "WHERE day<=?" if through else ""
        for t in self.store.rows(f"SELECT from_account, to_account, amount FROM cash_transfers {t_where}", *params):
            if t["from_account"] == "bank":
                bank -= t["amount"]
            else:
                cash -= t["amount"]
            if t["to_account"] == "bank":
                bank += t["amount"]
            else:
                cash += t["amount"]
        return {"total": bank + cash, "bank": bank, "cash": cash}

    def set_opening_cashbox(self, bank_amount, cash_amount, actor=None):
        with self.store.write():
            total = int(bank_amount) + int(cash_amount)
            self.store.save(initial_bank=int(bank_amount), initial_cash=int(cash_amount), initial=total)
            self.store.log_action(actor, "update_opening_cashbox", "system", "", f"בנק={bank_amount} · מזומן={cash_amount}")

    def transfer_cash(self, from_account, to_account, amount, day, reference="", notes="", actor=None):
        day = self._day(day)
        if from_account not in ACCOUNTS or to_account not in ACCOUNTS or from_account == to_account:
            raise Problem("יש לבחור העברה תקינה בין בנק למזומן")
        if not isinstance(amount, int) or amount <= 0:
            raise Problem("יש להזין סכום חיובי להעברה")
        with self.store.write():
            tid = self.store.db.execute(
                "INSERT INTO cash_transfers(day,from_account,to_account,amount,reference,notes) VALUES (?,?,?,?,?,?)",
                (day, from_account, to_account, amount, reference.strip(), notes.strip()),
            ).lastrowid
            self.store.log_action(
                actor, "cash_transfer", "transfer", tid,
                f"{ACCOUNTS[from_account]} -> {ACCOUNTS[to_account]} · {amount} אג׳",
            )
            return tid

    def list_transfers(self):
        return self.store.rows("SELECT * FROM cash_transfers ORDER BY day DESC, id DESC")

    # ------------------------------------------------------------------
    # Cash Journal & Categories
    # ------------------------------------------------------------------

    def cash(self):
        balance = int(self.store.get("initial", "0"))
        result = []
        for row in self.store.rows(
            """
            SELECT e.*, c.name category_name, COALESCE(o.kind, e.kind) base_kind,
                   s.name supplier_name,
                   (SELECT COUNT(*) FROM attachments a WHERE a.entry = e.id) attachment_count,
                   (SELECT r.id FROM entries r WHERE r.original = e.id LIMIT 1) reversed_by
            FROM entries e
            LEFT JOIN categories c ON c.id = e.category
            LEFT JOIN entries o ON o.id = e.original
            LEFT JOIN suppliers s ON s.id = COALESCE(e.supplier, o.supplier)
            WHERE e.cash <> 0
            ORDER BY e.day, e.id
            """
        ):
            balance += row["cash"]
            result.append(dict(row, balance=balance))
        return balance, result

    def category(self, kind, name, category=None, active=True, actor=None):
        if kind not in ("income", "expense") or not name.strip():
            raise Problem("יש להזין שם קטגוריה")
        with self.store.write():
            if category:
                self.store.db.execute("UPDATE categories SET name=?,active=? WHERE id=?", (name.strip(), int(active), category))
                self.store.log_action(actor, "update_category", "category", category, f"{name.strip()} · פעילה={int(active)}")
            else:
                cat_id = self.store.db.execute("INSERT INTO categories(kind,name) VALUES (?,?)", (kind, name.strip())).lastrowid
                self.store.log_action(actor, "add_category", "category", cat_id, name.strip())

    # ------------------------------------------------------------------
    # Shahrai Excel Data Seeding & Annual Collection Matrix (2025/2026/2027)
    # ------------------------------------------------------------------

    def load_shahrai_excel_data(self, target_bank=None, target_cash=None, actor=None):
        """Idempotently load all 21 Shahrai 14/16/18 residents + 2025/2026/2027 Excel history & compensation checks."""
        today_iso = date.today().isoformat()
        with self.store.write():
            # Fix complex spelling if needed
            for key in ("name", "complex", "address"):
                val = self.store.get(key)
                if "שחריי" in val:
                    self.store.save(**{key: val.replace("שחריי", "שחראי")})

            # Ensure management start covers 2026-01-01 so all 2026 charges are generated
            cur_start = self.store.get("start") or "2026-01-01"
            if cur_start > "2026-01-01":
                self.store.save(start="2026-01-01", generated_through="2026-01")
                self.store.db.execute("UPDATE unit_status SET effective='2026-01-01' WHERE effective=?", (cur_start,))
                self.store.db.execute("UPDATE fee_rates SET effective='2026-01-01' WHERE effective=?", (cur_start,))

            # Match existing 21 units by building order
            by_building = {14: [], 16: [], 18: []}
            for u in self.store.rows("SELECT * FROM units ORDER BY building, slot"):
                if u["building"] in by_building:
                    by_building[u["building"]].append(u)

            # Group SHAHRAI_DATA by building
            seed_by_bldg = {14: [], 16: [], 18: []}
            for item in SHAHRAI_DATA:
                seed_by_bldg[item[0]].append(item)

            matched_pairs = []
            for bldg in (14, 16, 18):
                db_units = by_building[bldg]
                seed_items = seed_by_bldg[bldg]
                # For building 16, pair split units with split seed items and regular with regular
                if bldg == 16:
                    reg_db = [u for u in db_units if not u["subunit"]]
                    spl_db = [u for u in db_units if u["subunit"]]
                    reg_sd = [s for s in seed_items if not s[3]]
                    spl_sd = [s for s in seed_items if s[3]]
                    matched_pairs.extend(zip(reg_db, reg_sd))
                    matched_pairs.extend(zip(spl_db, spl_sd))
                else:
                    matched_pairs.extend(zip(db_units, seed_items))

            # Update unit metadata, excel_history (2025/2026/2027), and compensation_checks (2025)
            for u, item in matched_pairs:
                bldg, _slot, apt_label, subunit, name_cur, prev_name, rate_ag, m2025, comp_amt, comp_status, m2026, m2027 = item
                uid = u["id"]
                new_apt = u["apartment"] if (subunit and not u["apartment"].startswith("@")) else (apt_label if not subunit else u["apartment"])
                owner = u["owner"] or name_cur
                notes = u["notes"]
                if prev_name and prev_name not in notes:
                    notes = f"דייר קודם (2025): {prev_name}" + (f" · {notes}" if notes else "")
                self.store.db.execute(
                    "UPDATE units SET apartment=?, owner=?, notes=? WHERE id=?",
                    (new_apt, owner, notes, uid),
                )
                if prev_name and not self.store.rows("SELECT id FROM occupants WHERE unit=? AND name=?", uid, prev_name):
                    self.store.db.execute(
                        "INSERT INTO occupants(unit,role,name,arrived,departed,notes) VALUES (?,'owner',?,'2025-01-01','2025-12-31','רישום מהאקסל 2025')",
                        (uid, prev_name),
                    )
                for yr, paid_set in ((2025, set(m2025)), (2026, set(m2026)), (2027, set(m2027))):
                    for mo in range(1, 13):
                        self.store.db.execute(
                            "INSERT INTO excel_history(unit,year,month,paid) VALUES (?,?,?,?) "
                            "ON CONFLICT(unit,year,month) DO UPDATE SET paid=excluded.paid",
                            (uid, yr, mo, 1 if mo in paid_set else 0),
                        )
                if comp_amt or comp_status:
                    self.store.db.execute(
                        "INSERT INTO compensation_checks(unit,year,amount_text,status) VALUES (?,2025,?,?) "
                        "ON CONFLICT(unit,year) DO UPDATE SET amount_text=excluded.amount_text, status=excluded.status",
                        (uid, comp_amt, comp_status),
                    )

            # Generate charges through today
            self.generate(today_iso)

            # Post idempotent payment entries for 2026 and 2027 Excel paid months
            imported_payments = 0
            for u, item in matched_pairs:
                uid = u["id"]
                _b, _s, _a, _su, name_cur, _prev, rate_ag, _m25, _ca, comp_status, m2026, m2027 = item
                for yr, months in ((2026, m2026), (2027, m2027)):
                    for mo in months:
                        period = f"{yr:04d}-{mo:02d}"
                        token = f"shahrai-excel-{period}-u{uid}"
                        if self.store.rows("SELECT id FROM entries WHERE token=?", token):
                            continue
                        pay_day = min(f"{period}-01", today_iso)
                        if pay_day < self.store.get("start"):
                            pay_day = self.store.get("start")
                        note = "קוזז משיק פיצויים 2025" if comp_status == "קוזז 2026" else f"קליטה מאקסל {yr}"
                        self.post(
                            "payment", rate_ag, pay_day, "העברה בנקאית", token,
                            unit=uid, party=name_cur, notes=note, allow_duplicate=True,
                            actor=actor, account="bank", for_period=period,
                        )
                        imported_payments += 1

            # Calibrate initial_bank / initial_cash so live balances match the treasurer's exact real balances
            if target_bank is not None or target_cash is not None:
                cur_bal = self.balances()
                init_bank = int(self.store.get("initial_bank", self.store.get("initial", "0")) or "0")
                init_cash = int(self.store.get("initial_cash", "0") or "0")
                if target_bank is not None:
                    init_bank += int(target_bank) - cur_bal["bank"]
                if target_cash is not None:
                    init_cash += int(target_cash) - cur_bal["cash"]
                self.store.save(initial_bank=init_bank, initial_cash=init_cash, initial=init_bank + init_cash)

            self.store.save(excel_seeded="1")
            self.store.log_action(actor, "load_excel_seed", "system", "", f"נטענו נתוני אקסל שחראי ({imported_payments} תשלומים)")
            return imported_payments

    def annual_matrix(self, year, building_filter=None):
        """Build the 12-month Excel-style collection matrix for `year` (2025 / 2026 / 2027...)."""
        year = int(year)
        today_iso = date.today().isoformat()
        cur_period = today_iso[:7]
        start_year = int((self.store.get("start") or "2026-01-01")[:4])

        hist_map = {
            (r["unit"], r["month"]): r["paid"]
            for r in self.store.rows("SELECT unit, month, paid FROM excel_history WHERE year=?", year)
        }
        comp_map = {
            r["unit"]: (r["amount_text"], r["status"])
            for r in self.store.rows("SELECT unit, amount_text, status FROM compensation_checks WHERE year=?", year)
        }
        prev_2025_names = {
            r["unit"]: r["name"]
            for r in self.store.rows("SELECT unit, name FROM occupants WHERE departed LIKE '2025-%'")
        }

        rows = []
        for u in self.units():
            if building_filter and str(u["building"]) != str(building_filter):
                continue
            uid = u["id"]
            rate = u["rate"] or 0
            acc = self.account(uid)
            display_name = (
                prev_2025_names[uid]
                if year == 2025 and uid in prev_2025_names
                else (u["tenant"] or u["owner"] or u["apartment"])
            )

            months_state = []
            paid_count = 0
            unpaid_due_count = 0
            for mo in range(1, 13):
                period = f"{year:04d}-{mo:02d}"
                if year < start_year:
                    # Pure historical Excel year (e.g. 2025)
                    is_paid = hist_map.get((uid, mo), 0)
                    st = "paid" if is_paid else "unpaid"
                    if is_paid:
                        paid_count += 1
                    else:
                        unpaid_due_count += 1
                else:
                    charge = acc["charges"].get(period)
                    if charge:
                        if charge["due"] == 0:
                            st = "exempt"
                            paid_count += 1
                        elif charge["left"] == 0:
                            st = "paid"
                            paid_count += 1
                        elif charge["paid"] > 0:
                            st = "partial"
                            unpaid_due_count += 1
                        else:
                            st = "unpaid"
                            unpaid_due_count += 1
                    else:
                        # Future month not yet charged
                        if acc["future_paid"].get(period, 0) >= rate > 0 or hist_map.get((uid, mo), 0) == 1:
                            st = "paid"
                            paid_count += 1
                        elif period <= cur_period:
                            st = "unpaid"
                            unpaid_due_count += 1
                        else:
                            st = "future"
                months_state.append(st)

            comp_amt, comp_status = comp_map.get(uid, ("", ""))
            rows.append({
                "unit": u,
                "display_name": display_name,
                "rate": rate,
                "months": months_state,
                "paid_count": paid_count,
                "unpaid_due_count": unpaid_due_count,
                "paid_amount": paid_count * rate,
                "debt_now": max(0, acc["unpaid_total"]) if year >= start_year else unpaid_due_count * rate,
                "comp_amount": comp_amt,
                "comp_status": comp_status,
            })
        return rows

    # ------------------------------------------------------------------
    # Suppliers
    # ------------------------------------------------------------------

    def save_supplier(self, name, service="", phone="", contact="", email="", notes="", active=True, supplier_id=None, actor=None):
        if not name.strip():
            raise Problem("יש להזין שם ספק")
        data = (name.strip(), service.strip(), phone.strip(), contact.strip(), email.strip(), notes.strip(), int(active))
        with self.store.write():
            if supplier_id:
                self.store.db.execute(
                    "UPDATE suppliers SET name=?,service=?,phone=?,contact=?,email=?,notes=?,active=? WHERE id=?",
                    (*data, supplier_id),
                )
                self.store.log_action(actor, "update_supplier", "supplier", supplier_id, name.strip())
                return supplier_id
            new_id = self.store.db.execute(
                "INSERT INTO suppliers(name,service,phone,contact,email,notes,active) VALUES (?,?,?,?,?,?,?)",
                data,
            ).lastrowid
            self.store.log_action(actor, "add_supplier", "supplier", new_id, name.strip())
            return new_id

    def suppliers_summary(self, start=None, end=None):
        """Return all suppliers with net totals (properly subtracting reversed expenses)."""
        suppliers = self.store.rows("SELECT * FROM suppliers ORDER BY name")
        rows = self.store.rows(
            """
            SELECT COALESCE(e.supplier, o.supplier) supplier_id, e.day, e.cash, e.kind,
                   (SELECT COUNT(*) FROM attachments a WHERE a.entry = e.id) att_count
            FROM entries e
            LEFT JOIN entries o ON o.id = e.original
            WHERE COALESCE(e.supplier, o.supplier) IS NOT NULL
              AND COALESCE(o.kind, e.kind) = 'expense'
            """
        )
        today_iso = date.today().isoformat()
        cur_month = today_iso[:7]
        cur_year = today_iso[:4]
        result = []
        for s in suppliers:
            sid = s["id"]
            paid = [r for r in rows if r["supplier_id"] == sid]
            month_total = -sum(r["cash"] for r in paid if r["day"][:7] == cur_month)
            year_total = -sum(r["cash"] for r in paid if r["day"][:4] == cur_year)
            period_total = -sum(
                r["cash"] for r in paid
                if (not start or r["day"] >= start) and (not end or r["day"] <= end)
            )
            active_days = [r["day"] for r in paid if r["kind"] == "expense"]
            last_day = max(active_days, default="")
            att_total = sum(r["att_count"] for r in paid)
            result.append(
                dict(
                    s,
                    month_total=month_total,
                    year_total=year_total,
                    period_total=period_total,
                    last_day=last_day,
                    attachments_count=att_total,
                )
            )
        return result

    def supplier_history(self, supplier_id, start=None, end=None):
        rows = self.store.rows(
            """
            SELECT e.*, c.name category_name, COALESCE(o.kind, e.kind) base_kind,
                   (SELECT COUNT(*) FROM attachments a WHERE a.entry = e.id) attachment_count,
                   (SELECT r.id FROM entries r WHERE r.original = e.id LIMIT 1) reversed_by
            FROM entries e
            LEFT JOIN categories c ON c.id = e.category
            LEFT JOIN entries o ON o.id = e.original
            WHERE COALESCE(e.supplier, o.supplier) = ?
              AND COALESCE(o.kind, e.kind) = 'expense'
            ORDER BY e.day DESC, e.id DESC
            """,
            supplier_id,
        )
        return [r for r in rows if (not start or r["day"] >= start) and (not end or r["day"] <= end)]

    # ------------------------------------------------------------------
    # Recurring Expenses
    # ------------------------------------------------------------------

    def list_recurring(self):
        return self.store.rows(
            """
            SELECT r.*, s.name supplier_name, c.name category_name
            FROM recurring_expenses r
            LEFT JOIN suppliers s ON s.id = r.supplier
            JOIN categories c ON c.id = r.category
            ORDER BY r.active DESC, r.due_day, r.id
            """
        )

    def save_recurring(self, category, usual_amount, frequency_months, due_day, starts,
                       supplier=None, variable=False, ends=None, notes="", active=True, rec_id=None, actor=None):
        start = valid_day(starts)
        end = valid_day(ends) if ends else None
        if frequency_months < 1 or not (1 <= due_day <= 31) or usual_amount <= 0 or (end and end < start):
            raise Problem("תדירות, סכום או תאריך אינם תקינים")
        with self.store.write():
            if rec_id:
                self.store.db.execute(
                    """
                    UPDATE recurring_expenses
                    SET supplier=?,category=?,usual_amount=?,variable=?,frequency_months=?,due_day=?,starts=?,ends=?,active=?,notes=?
                    WHERE id=?
                    """,
                    (supplier, category, usual_amount, int(variable), frequency_months, due_day, start, end, int(active), notes.strip(), rec_id),
                )
                self.store.log_action(actor, "update_recurring", "recurring", rec_id, notes.strip() or f"#{rec_id}")
                return rec_id
            new_id = self.store.db.execute(
                """
                INSERT INTO recurring_expenses(supplier,category,usual_amount,variable,frequency_months,due_day,starts,ends,active,notes)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (supplier, category, usual_amount, int(variable), frequency_months, due_day, start, end, int(active), notes.strip()),
            ).lastrowid
            self.store.log_action(actor, "add_recurring", "recurring", new_id, notes.strip() or f"#{new_id}")
            return new_id

    def recurring_due(self, through=None):
        """Return due occurrences without posting cash movements (ignoring reversed matches)."""
        through = valid_day(through or date.today().isoformat())
        result = []
        for row in self.store.rows(
            "SELECT r.*,s.name supplier_name,c.name category_name FROM recurring_expenses r "
            "LEFT JOIN suppliers s ON s.id=r.supplier "
            "JOIN categories c ON c.id=r.category WHERE r.active=1 ORDER BY r.starts,r.id"
        ):
            year, month = map(int, row["starts"][:7].split("-"))
            while f"{year:04d}-{month:02d}-01" <= through:
                period = f"{year:04d}-{month:02d}"
                day = f"{period}-{min(row['due_day'], monthrange(year, month)[1]):02d}"
                if day >= row["starts"] and day <= through and (not row["ends"] or day <= row["ends"]):
                    match = self.store.rows(
                        """
                        SELECT rm.expense FROM recurring_matches rm
                        WHERE rm.recurring=? AND rm.period=?
                          AND NOT EXISTS (SELECT 1 FROM entries rev WHERE rev.original = rm.expense)
                        """,
                        row["id"], period,
                    )
                    if not match:
                        result.append((row, period, day))
                next_month = month - 1 + row["frequency_months"]
                year += next_month // 12
                month = next_month % 12 + 1
        return result

    def match_recurring(self, recurring, period, expense, actor=None):
        with self.store.write():
            if not self.store.rows("SELECT id FROM recurring_expenses WHERE id=?", recurring):
                raise Problem("הוצאה קבועה אינה קיימת")
            if not self.store.rows(
                "SELECT id FROM entries WHERE id=? AND kind='expense' "
                "AND NOT EXISTS (SELECT 1 FROM entries rev WHERE rev.original=entries.id)",
                expense,
            ):
                raise Problem("יש לבחור הוצאה פעילה שנרשמה")
            self.store.db.execute(
                """
                DELETE FROM recurring_matches
                WHERE recurring=? AND period=?
                  AND EXISTS (SELECT 1 FROM entries rev WHERE rev.original = recurring_matches.expense)
                """,
                (recurring, period),
            )
            self.store.db.execute("INSERT INTO recurring_matches VALUES (?,?,?)", (recurring, period, expense))
            self.store.log_action(actor, "match_recurring", "recurring", recurring, f"{period} -> #{expense}")

    # ------------------------------------------------------------------
    # Collection, Reports, Charts & Receipts
    # ------------------------------------------------------------------

    def details(self, period):
        units = self.units()
        data = []
        for unit in units:
            account = self.account(unit["id"])
            charge = account["charges"].get(period)
            if charge:
                older = account["opening"] + sum(c["left"] for p, c in account["charges"].items() if p < period)
                status = (
                    "פטור" if not charge["due"]
                    else "שולם" if not charge["left"]
                    else "שולם חלקית" if charge["paid"]
                    else "לא שולם"
                )
                data.append((unit, charge, older, account["credit"], status))
        return data

    def report(self, period):
        initial = int(self.store.get("initial", "0"))
        totals = dict(payment=0, income=0, expense=0)
        for row in self.cash()[1]:
            if row["day"][:len(period)] < period:
                initial += row["cash"]
            elif row["day"].startswith(period):
                totals[row["base_kind"]] += row["cash"]
        charges = self.store.rows(
            """
            SELECT COALESCE(SUM(c.debit + COALESCE((SELECT SUM(a.debit)
            FROM entries a WHERE a.charge=c.id),0)),0) FROM entries c
            WHERE c.kind='charge' AND substr(c.period,1,?)=?
            """,
            len(period), period,
        )[0][0]
        return dict(totals, initial=initial, final=initial + sum(totals.values()), charges=charges)

    def monthly_series(self, months=12, through=None):
        ref = date.fromisoformat(valid_day(through or date.today().isoformat()))
        periods = []
        year, month = ref.year, ref.month
        for _ in range(months):
            periods.append(f"{year:04d}-{month:02d}")
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        periods.reverse()
        buckets = {p: {"period": p, "label": f"{p[5:]}/{p[2:4]}", "income": 0, "expense": 0} for p in periods}
        for row in self.cash()[1]:
            p = row["day"][:7]
            if p in buckets:
                if row["base_kind"] == "expense":
                    buckets[p]["expense"] -= row["cash"]
                else:
                    buckets[p]["income"] += row["cash"]
        series = []
        for p in periods:
            item = buckets[p]
            item["net"] = item["income"] - item["expense"]
            series.append(item)
        return series

    def expenses_by_supplier(self, start="", end="9999-12-31"):
        totals = {}
        for r in self.cash()[1]:
            if start <= r["day"] <= end and r["base_kind"] == "expense":
                label = r["supplier_name"] or r["party"] or "ללא ספק"
                totals[label] = totals.get(label, 0) - r["cash"]
        return sorted(((k, v) for k, v in totals.items() if v != 0), key=lambda item: -item[1])

    def receipt_data(self, entry_id):
        rows = self.store.rows("SELECT * FROM entries WHERE id=? AND kind='payment'", entry_id)
        if not rows:
            raise Problem("אישור תשלום זמין רק עבור תשלום דייר")
        entry = dict(rows[0])
        reversed_by = self.store.rows("SELECT id FROM entries WHERE original=?", entry_id)
        unit = self.store.rows("SELECT * FROM units WHERE id=?", entry["unit"])[0]
        account = self.account(entry["unit"], entry["day"])
        current_account = self.account(entry["unit"])
        return {
            "receipt_no": f"VB-{entry['id']:05d}",
            "entry": entry,
            "reversed": bool(reversed_by),
            "unit": dict(unit),
            "balance_at_date": account["balance"],
            "balance_now": current_account["balance"],
            "vaad_name": self.store.get("name", "ועד הבית"),
            "complex_name": self.store.get("complex", ""),
            "address": self.store.get("address", ""),
            "contact": self.store.get("contact", ""),
        }
