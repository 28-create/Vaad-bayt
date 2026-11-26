"""Financial ledger, units, occupants, suppliers, recurring expenses, and reporting queries."""

from calendar import monthrange
from datetime import date

from .store import Problem, month_next, valid_day

METHODS = ("מזומן", "העברה בנקאית", "המחאה", "אחר")
LABELS = dict(
    opening="יתרת פתיחה",
    charge="חיוב חודשי",
    adjustment="תיקון חיוב",
    payment="תשלום דייר",
    expense="הוצאה",
    income="הכנסה אחרת",
    reversal="ביטול פעולה",
)


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
    # Monthly Charges & Accounts
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
        for row in rows:
            if row["kind"] == "adjustment":
                adjustments[row["charge"]] = adjustments.get(row["charge"], 0) + row["debit"]
        through_balance = sum(row["debit"] for row in rows)
        credit = sum(
            -row["debit"]
            for row in rows
            if row["kind"] in ("payment", "reversal") or (row["kind"] == "opening" and row["debit"] < 0)
        )
        charges = {}
        initial = next((row for row in rows if row["kind"] == "opening" and row["debit"] > 0), None)
        opening = max(0, initial["debit"] - credit) if initial else 0
        if initial:
            credit = max(0, credit - initial["debit"])
        oldest = initial["day"] if opening else ""
        for row in rows:
            if row["kind"] == "charge":
                due = row["debit"] + adjustments.get(row["id"], 0)
                paid = min(credit, due)
                credit -= paid
                charges[row["period"]] = dict(id=row["id"], due=due, paid=paid, left=due - paid)
                if due > paid and not oldest:
                    oldest = row["day"]
        return dict(balance=through_balance, credit=credit, charges=charges, opening=opening, oldest=oldest)

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
    # Posting & Reversals
    # ------------------------------------------------------------------

    def post(self, kind, amount, day, method, token, unit=None, category=None, party="",
             description="", reference="", notes="", allow_duplicate=False, supplier=None, actor=None):
        day = self._day(day)
        if kind not in ("payment", "expense", "income") or not isinstance(amount, int) or amount <= 0 or method not in METHODS or not token:
            raise Problem("יש למלא סכום חיובי ואמצעי תשלום")
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
                INSERT INTO entries(kind,day,unit,debit,cash,category,method,party,description,reference,notes,token,supplier)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    kind, day, unit,
                    -amount if kind == "payment" else 0,
                    -amount if kind == "expense" else amount,
                    category, method, party.strip(), description.strip(), reference.strip(), notes.strip(), token, supplier,
                ),
            ).lastrowid
            self.store.log_action(actor, f"post_{kind}", "entry", entry_id, f"{amount} אג׳ · {party.strip() or f'יחידה {unit}'}")
            return entry_id

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
                INSERT INTO entries(kind,day,unit,debit,cash,original,category,method,party,description,notes,supplier)
                VALUES ('reversal',?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    day, row["unit"], -row["debit"], -row["cash"], entry, row["category"],
                    row["method"], row["party"], row["description"], reason.strip(), row["supplier"],
                ),
            ).lastrowid
            self.store.log_action(actor, "reverse_entry", "entry", entry, f"בוטל ע״י #{rev_id}: {reason.strip()}")
            return rev_id

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
            # Remove any stale match pointing to a reversed expense
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
        """Return monthly income vs expense totals for the last `months` months."""
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
