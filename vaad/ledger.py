from datetime import date
from calendar import monthrange
from .store import Problem, valid_day, month_next

METHODS = ("מזומן", "העברה בנקאית", "המחאה", "אחר")
LABELS = dict(opening="יתרת פתיחה", charge="חיוב חודשי", adjustment="תיקון חיוב",
              payment="תשלום דייר", expense="הוצאה", income="הכנסה אחרת", reversal="ביטול פעולה")


class Ledger:
    def __init__(self, store):
        self.store = store

    def units(self, day=None):
        day = day or date.today().isoformat()
        return self.store.rows("""
            SELECT u.*, COALESCE((SELECT active FROM unit_status WHERE unit=u.id AND effective<=?
               ORDER BY effective DESC LIMIT 1),0) active,
               (SELECT amount FROM fee_rates WHERE unit=u.id AND effective<=? ORDER BY effective DESC LIMIT 1) rate,
               (SELECT effective FROM fee_rates WHERE unit=u.id AND effective<=? ORDER BY effective DESC LIMIT 1) effective
            FROM units u ORDER BY building,slot
        """, day, day, day)

    def unit_update(self, unit, fields, active):
        fields = tuple(value.strip() for value in fields)
        with self.store.write():
            original = self.store.rows("SELECT * FROM units WHERE id=?", unit)[0]
            if original["subunit"] and not fields[0]:
                raise Problem("יש להזין מספר לדירה המחולקת")
            if fields[0].startswith("@"):
                raise Problem("מספר הדירה אינו תקין")
            if original["subunit"] and fields[0] != original["apartment"]:
                self.store.db.execute("UPDATE units SET apartment=? WHERE building=? AND subunit<>''",
                                      (fields[0],original["building"]))
            apartment = fields[0] or f"@{original['slot']//2}"
            self.store.db.execute("UPDATE units SET apartment=?,owner=?,tenant=?,phone=?,email=?,notes=? WHERE id=?",
                                  (apartment,*fields[1:],unit))
            today = date.today().isoformat()
            self.store.db.execute("INSERT INTO unit_status VALUES (?,?,?) ON CONFLICT(unit,effective) "
                                  "DO UPDATE SET active=excluded.active", (unit,today,int(active)))

    def rate(self, unit, day, amount, split=False):
        day = valid_day(day)
        if day < date.today().isoformat() or amount < 0:
            raise Problem("יש לבחור תאריך מהיום ואילך ותעריף שאינו שלילי")
        with self.store.write():
            if unit:
                rates = [(unit,day,amount)]
            else:
                rates = [(u["id"],day,(amount+(u["subunit"]=="א"))//2 if u["subunit"] else amount)
                         for u in self.units(day)]
                self.store.save(rate=amount)
            self.store.db.executemany("INSERT INTO fee_rates VALUES (?,?,?) ON CONFLICT(unit,effective) "
                                      "DO UPDATE SET amount=excluded.amount", rates)

    def generate(self, through=None):
        through = valid_day(through or date.today().isoformat())
        start = self.store.get("start")
        if not start:
            return
        with self.store.write():
            period = max(start[:7], self.store.get("generated_through", start[:7]))
            while period <= through[:7] and start <= through:
                day = max(period+"-01",start)
                for unit in self.units(day):
                    if unit["active"] and unit["rate"] is not None:
                        self.store.db.execute("""
                            INSERT INTO entries(unit,day,kind,debit,period) VALUES (?,?,'charge',?,?)
                            ON CONFLICT(unit,period) WHERE kind='charge' DO NOTHING
                        """, (unit["id"],day,unit["rate"],period))
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
                adjustments[row["charge"]] = adjustments.get(row["charge"],0) + row["debit"]
        through_balance = sum(row["debit"] for row in rows)
        credit = sum(-row["debit"] for row in rows if row["kind"] in ("payment","reversal")
                     or row["kind"] == "opening" and row["debit"] < 0)
        charges = {}
        initial = next((row for row in rows if row["kind"] == "opening" and row["debit"] > 0), None)
        opening = max(0, initial["debit"] - credit) if initial else 0
        if initial:
            credit = max(0, credit - initial["debit"])
        oldest = initial["day"] if opening else ""
        for row in rows:
            if row["kind"] == "charge":
                due = row["debit"] + adjustments.get(row["id"],0)
                paid = min(credit,due)
                credit -= paid
                charges[row["period"]] = dict(id=row["id"],due=due,paid=paid,left=due-paid)
                if due > paid and not oldest:
                    oldest = row["day"]
        return dict(balance=through_balance,credit=credit,charges=charges,opening=opening,oldest=oldest)

    def opening(self, unit, amount):
        self.store.db.execute("INSERT INTO entries(unit,day,kind,debit) VALUES (?,?,'opening',?)",
                              (unit,self.store.get("start"),amount))

    def adjust(self, unit, period, amount, reason):
        if amount < 0 or not reason.strip():
            raise Problem("יש להזין סכום שאינו שלילי וסיבה")
        with self.store.write():
            charge = self.account(unit)["charges"].get(period)
            if not charge:
                raise Problem("אין חיוב בחודש זה")
            self.store.db.execute("INSERT INTO entries(unit,day,kind,debit,charge,notes) VALUES (?,?,'adjustment',?,?,?)",
                                  (unit,date.today().isoformat(),amount-charge["due"],charge["id"],reason))

    def post(self, kind, amount, day, method, token, unit=None, category=None, party="",
             description="", reference="", notes="", allow_duplicate=False, supplier=None):
        day = self._day(day)
        if kind not in ("payment","expense","income") or not isinstance(amount,int) or amount<=0 or method not in METHODS or not token:
            raise Problem("יש למלא סכום חיובי ואמצעי תשלום")
        with self.store.write():
            existing = self.store.rows("SELECT id FROM entries WHERE token=?",token)
            if existing:
                return existing[0]["id"]
            if kind == "payment":
                if not unit or not self.store.rows("SELECT id FROM units WHERE id=?",unit):
                    raise Problem("יש לבחור יחידת תשלום")
                if not allow_duplicate and self.store.rows("""
                    SELECT e.id FROM entries e LEFT JOIN entries r ON r.original=e.id
                    WHERE e.kind='payment' AND e.unit=? AND e.day=? AND e.cash=? AND e.method=? AND r.id IS NULL
                """,unit,day,amount,method):
                    raise Problem("נמצא תשלום דומה")
            else:
                if not (party.strip() and description.strip() and self.store.rows(
                    "SELECT id FROM categories WHERE id=? AND kind=? AND active=1",category,kind
                )):
                    raise Problem("יש להזין שם, תיאור וקטגוריה פעילה")
            return self.store.db.execute("""
              INSERT INTO entries(kind,day,unit,debit,cash,category,method,party,description,reference,notes,token,supplier)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (kind,day,unit,-amount if kind=="payment" else 0,-amount if kind=="expense" else amount,
                  category,method,party,description,reference,notes,token,supplier)).lastrowid

    def reverse(self, entry, reason, day=None):
        day = self._day(day or date.today().isoformat())
        with self.store.write():
            rows = self.store.rows("SELECT * FROM entries WHERE id=? AND kind IN ('payment','expense','income')",entry)
            if (not rows or not reason.strip() or day < rows[0]["day"]
                or self.store.rows("SELECT id FROM entries WHERE original=?",entry)):
                raise Problem("לא ניתן לבטל את הפעולה. יש לבדוק את הפעולה, התאריך והסיבה")
            row = rows[0]
            self.store.db.execute("""
              INSERT INTO entries(kind,day,unit,debit,cash,original,category,method,party,description,notes)
              VALUES ('reversal',?,?,?,?,?,?,?,?,?,?)
            """,(day,row["unit"],-row["debit"],-row["cash"],entry,row["category"],
                 row["method"],row["party"],row["description"],reason))

    def cash(self):
        balance = int(self.store.get("initial","0"))
        result = []
        for row in self.store.rows("""
            SELECT e.*,c.name category_name,COALESCE(o.kind,e.kind) base_kind
            FROM entries e LEFT JOIN categories c ON c.id=e.category
            LEFT JOIN entries o ON o.id=e.original WHERE e.cash<>0 ORDER BY e.day,e.id
        """):
            balance += row["cash"]
            result.append(dict(row,balance=balance))
        return balance,result

    def category(self, kind, name, category=None, active=True):
        if kind not in ("income","expense") or not name.strip():
            raise Problem("יש להזין שם קטגוריה")
        if category:
            self.store.db.execute("UPDATE categories SET name=?,active=? WHERE id=?", (name.strip(),int(active),category))
        else:
            self.store.db.execute("INSERT INTO categories(kind,name) VALUES (?,?)", (kind,name.strip()))

    def details(self, period):
        units = self.units()
        data = []
        for unit in units:
            account = self.account(unit["id"])
            charge = account["charges"].get(period)
            if charge:
                older = account["opening"] + sum(c["left"] for p,c in account["charges"].items() if p<period)
                status = "פטור" if not charge["due"] else "שולם" if not charge["left"] else "שולם חלקית" if charge["paid"] else "לא שולם"
                data.append((unit,charge,older,account["credit"],status))
        return data

    def report(self, period):
        initial = int(self.store.get("initial","0"))
        totals = dict(payment=0,income=0,expense=0)
        for row in self.cash()[1]:
            if row["day"][:len(period)] < period:
                initial += row["cash"]
            elif row["day"].startswith(period):
                totals[row["base_kind"]] += row["cash"]
        charges = self.store.rows("""
            SELECT COALESCE(SUM(c.debit + COALESCE((SELECT SUM(a.debit)
            FROM entries a WHERE a.charge=c.id),0)),0) FROM entries c
            WHERE c.kind='charge' AND substr(c.period,1,?)=?
        """,len(period),period)[0][0]
        return dict(totals,initial=initial,final=initial+sum(totals.values()),charges=charges)

    def recurring_due(self, through=None):
        """Return due occurrences without posting cash movements."""
        through = valid_day(through or date.today().isoformat())
        result = []
        for row in self.store.rows("SELECT r.*,s.name supplier_name,c.name category_name FROM recurring_expenses r "
                                   "LEFT JOIN suppliers s ON s.id=r.supplier "
                                   "JOIN categories c ON c.id=r.category WHERE r.active=1 ORDER BY r.starts,r.id"):
            year, month = map(int,row["starts"][:7].split("-"))
            while f"{year:04d}-{month:02d}-01" <= through:
                period = f"{year:04d}-{month:02d}"
                day = f"{period}-{min(row['due_day'],monthrange(year,month)[1]):02d}"
                if day >= row["starts"] and day <= through and (not row["ends"] or day <= row["ends"]):
                    match = self.store.rows("SELECT expense FROM recurring_matches WHERE recurring=? AND period=?",row["id"],period)
                    if not match:
                        result.append((row,period,day))
                next_month = month - 1 + row["frequency_months"]
                year += next_month // 12
                month = next_month % 12 + 1
        return result

    def match_recurring(self, recurring, period, expense):
        with self.store.write():
            if not self.store.rows("SELECT id FROM recurring_expenses WHERE id=?",recurring):
                raise Problem("הוצאה קבועה אינה קיימת")
            if not self.store.rows("SELECT id FROM entries WHERE id=? AND kind='expense'",expense):
                raise Problem("יש לבחור הוצאה שנרשמה")
            self.store.db.execute("INSERT INTO recurring_matches VALUES (?,?,?)",(recurring,period,expense))

