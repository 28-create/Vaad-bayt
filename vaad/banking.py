"""Offline bank statement importer (CSV / XLSX) with smart unit matching & deduplication."""

from datetime import date
import hashlib
import re
from uuid import uuid4

from .excel import read_tabular
from .store import Problem, money

HEADER_KEYWORDS = {
    "date": ("תאריך", "תאריך ערך", "תאריך פעולה", "date", "value date"),
    "desc": ("תיאור", "פרטים", "פעולה", "שם המעביר", "תיאור פעולה", "הפעולה", "description", "details", "memo"),
    "credit": ("זכות", "הכנסה", "זכות בש\"ח", "זכות בש״ח", "credit"),
    "debit": ("חובה", "הוצאה", "חובה בש\"ח", "חובה בש״ח", "debit"),
    "amount": ("סכום", "סכום פעולה", "סכום בש\"ח", "amount"),
    "ref": ("אסמכתא", "מספר אסמכתא", "מס' אסמכתא", "reference", "ref"),
}


def parse_bank_date(raw):
    text = str(raw or "").strip().split(" ")[0]
    if not text:
        return None
    # ISO YYYY-MM-DD
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            return None
    # DD/MM/YYYY or DD.MM.YYYY or DD-MM-YYYY or DD/MM/YY
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None
    return None


def parse_bank_amount(raw):
    text = str(raw or "").strip()
    if not text or text in ("-", "—", "0", "0.00"):
        return 0
    cleaned = text.replace(",", "").replace("₪", "").replace("\u200e", "").replace("−", "-").replace(" ", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    try:
        return money(cleaned)
    except Problem:
        return 0


def _match_header_row(rows):
    for row_idx, row in enumerate(rows[:25]):
        mapping = {}
        for col_idx, cell in enumerate(row):
            norm = cell.strip().casefold()
            if not norm:
                continue
            for field, keywords in HEADER_KEYWORDS.items():
                if field in mapping:
                    continue
                if any(norm == kw.casefold() or kw.casefold() in norm for kw in keywords):
                    mapping[field] = col_idx
                    break
        if "date" in mapping and ("credit" in mapping or "debit" in mapping or "amount" in mapping):
            return row_idx, mapping
    raise Problem("לא זוהו עמודות תאריך וסכום בקובץ הבנק. יש לוודא שהקובץ כולל כותרות כגון תאריך, תיאור, זכות/חובה או סכום.")


def _fingerprint(day, amount, direction, desc, ref, occurrence):
    payload = f"{day}|{amount}|{direction}|{desc.strip().casefold()}|{ref.strip()}|{occurrence}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _tokenize(text):
    cleaned = re.sub(r"[^\w\u0590-\u05ff]+", " ", str(text or "").casefold())
    return {tok for tok in cleaned.split() if len(tok) >= 2}


def suggest_unit(description, amount, units, accounts):
    """Suggest the best matching unit for a bank credit row."""
    desc_cf = description.casefold()
    desc_tokens = _tokenize(description)
    best_unit = None
    best_score = 0
    best_reason = ""

    for u in units:
        score = 0
        reasons = []
        apt = "" if u["apartment"].startswith("@") else u["apartment"]
        bldg = str(u["building"])
        tenant_tokens = _tokenize(u["tenant"])
        owner_tokens = _tokenize(u["owner"])

        t_hits = tenant_tokens & desc_tokens
        o_hits = owner_tokens & desc_tokens
        if t_hits:
            score += 45 * len(t_hits)
            reasons.append(f"התאמת שם שוכר ({' '.join(sorted(t_hits))})")
        if o_hits:
            score += 40 * len(o_hits)
            reasons.append(f"התאמת שם בעלים ({' '.join(sorted(o_hits))})")

        if apt and (f"{bldg}/{apt}" in desc_cf or f"{bldg} {apt}" in desc_cf or f"דירה {apt}" in desc_cf or f"ד'{apt}" in desc_cf):
            score += 50
            reasons.append(f"אזכור דירה {bldg}/{apt}")

        rate = u["rate"] or 0
        bal = accounts.get(u["id"], {}).get("balance", 0)
        if bal > 0 and amount == bal:
            score += 25
            reasons.append("סכום תואם ליתרת החוב")
        elif rate > 0 and amount == rate:
            score += 15
            reasons.append("סכום תואם לתעריף החודשי")
        elif rate > 0 and amount % rate == 0 and 1 <= amount // rate <= 12:
            score += 10
            reasons.append(f"כפולת תעריף ({amount // rate} חודשים)")

        if score > best_score:
            best_score = score
            best_unit = u["id"]
            best_reason = " · ".join(reasons)

    if best_score >= 55:
        return best_unit, "גבוהה", best_reason
    if best_score >= 35:
        return best_unit, "בינונית", best_reason
    return None, "ידני", ""


def parse_bank_file(path, store, ledger):
    """Parse a CSV/XLSX bank statement, deduplicate against bank_imports, and suggest unit matches."""
    raw_rows = read_tabular(path)
    if not raw_rows:
        raise Problem("הקובץ ריק או לא ניתן לקריאה")
    header_idx, mapping = _match_header_row(raw_rows)
    units = ledger.units()
    accounts = {u["id"]: ledger.account(u["id"]) for u in units}
    existing_fps = {r["fingerprint"]: r["status"] for r in store.rows("SELECT fingerprint, status FROM bank_imports")}

    occurrences = {}
    parsed = []
    for row in raw_rows[header_idx + 1:]:
        def col(key):
            idx = mapping.get(key)
            return row[idx].strip() if idx is not None and idx < len(row) else ""

        day = parse_bank_date(col("date"))
        if not day:
            continue
        desc = col("desc")
        ref = col("ref")

        credit = parse_bank_amount(col("credit")) if "credit" in mapping else 0
        debit = parse_bank_amount(col("debit")) if "debit" in mapping else 0
        if "amount" in mapping and credit == 0 and debit == 0:
            signed = parse_bank_amount(col("amount"))
            if signed > 0:
                credit = signed
            elif signed < 0:
                debit = abs(signed)

        if credit > 0:
            direction, amount = "credit", credit
        elif debit > 0:
            direction, amount = "debit", debit
        else:
            continue

        base_key = (day, amount, direction, desc.casefold(), ref)
        occurrences[base_key] = occurrences.get(base_key, 0) + 1
        fp = _fingerprint(day, amount, direction, desc, ref, occurrences[base_key])
        prev_status = existing_fps.get(fp)

        suggested_unit, confidence, reason = (None, "ידני", "")
        if direction == "credit":
            suggested_unit, confidence, reason = suggest_unit(desc, amount, units, accounts)

        default_action = "skip" if prev_status else ("payment" if suggested_unit else "skip")
        parsed.append(
            {
                "fingerprint": fp,
                "day": day,
                "description": desc,
                "reference": ref,
                "amount": amount,
                "direction": direction,
                "already_status": prev_status,  # None | 'matched' | 'ignored'
                "suggested_unit": suggested_unit,
                "unit_id": suggested_unit,
                "confidence": confidence,
                "reason": reason,
                "action": default_action,  # 'payment' | 'income' | 'expense' | 'ignore' | 'skip'
                "category_id": None,
                "notes": "",
            }
        )
    if not parsed:
        raise Problem("לא נמצאו תנועות בנק תקינות בקובץ")
    return parsed


def commit_bank_rows(store, ledger, items, actor=None):
    """Commit approved bank rows atomically into entries + bank_imports."""
    imported_count = 0
    ignored_count = 0
    default_income_cat = store.rows("SELECT id FROM categories WHERE kind='income' AND active=1 ORDER BY id LIMIT 1")
    default_expense_cat = store.rows("SELECT id FROM categories WHERE kind='expense' AND active=1 ORDER BY id LIMIT 1")

    with store.write():
        for item in items:
            action = item.get("action", "skip")
            if action == "skip" or item.get("already_status"):
                continue
            fp = item["fingerprint"]
            if store.rows("SELECT id FROM bank_imports WHERE fingerprint=?", fp):
                continue

            if action == "ignore":
                store.db.execute(
                    """
                    INSERT INTO bank_imports(fingerprint,row_date,description,amount,direction,reference,status,entry,notes)
                    VALUES (?,?,?,?,?,?,'ignored',NULL,?)
                    """,
                    (fp, item["day"], item["description"], item["amount"], item["direction"], item["reference"], item.get("notes", "אינו קשור לוועד")),
                )
                ignored_count += 1
                continue

            token = f"bank-{fp[:24]}-{uuid4().hex[:8]}"
            if action == "payment":
                unit_id = item.get("unit_id")
                if not unit_id:
                    raise Problem(f"יש לבחור יחידה עבור התנועה מתאריך {item['day']} ({item['description']})")
                entry_id = ledger.post(
                    "payment",
                    item["amount"],
                    item["day"],
                    "העברה בנקאית",
                    token,
                    unit=unit_id,
                    party=item["description"][:80],
                    reference=item["reference"],
                    notes=item.get("notes") or f"יובא מהבנק: {item['description']}",
                    allow_duplicate=True,
                    actor=actor,
                )
            elif action == "income":
                cat_id = item.get("category_id") or (default_income_cat[0]["id"] if default_income_cat else None)
                entry_id = ledger.post(
                    "income",
                    item["amount"],
                    item["day"],
                    "העברה בנקאית",
                    token,
                    category=cat_id,
                    party=item["description"][:80] or "העברה בנקאית",
                    description=item["description"] or "הכנסה מהבנק",
                    reference=item["reference"],
                    notes=item.get("notes", ""),
                    actor=actor,
                )
            elif action == "expense":
                cat_id = item.get("category_id") or (default_expense_cat[0]["id"] if default_expense_cat else None)
                entry_id = ledger.post(
                    "expense",
                    item["amount"],
                    item["day"],
                    "העברה בנקאית",
                    token,
                    category=cat_id,
                    party=item["description"][:80] or "תשלום בנקאי",
                    description=item["description"] or "הוצאה מהבנק",
                    reference=item["reference"],
                    notes=item.get("notes", ""),
                    actor=actor,
                )
            else:
                continue

            store.db.execute(
                """
                INSERT INTO bank_imports(fingerprint,row_date,description,amount,direction,reference,status,entry,notes)
                VALUES (?,?,?,?,?,?,'matched',?,?)
                """,
                (fp, item["day"], item["description"], item["amount"], item["direction"], item["reference"], entry_id, item.get("notes", "")),
            )
            imported_count += 1

        if imported_count or ignored_count:
            store.log_action(actor, "bank_import", "bank", "", f"נקלטו {imported_count} תנועות, סומנו כלא קשורות {ignored_count}")
    return imported_count, ignored_count
