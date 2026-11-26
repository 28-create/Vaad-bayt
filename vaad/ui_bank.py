"""Bank statement import UI (CSV / Excel) with smart unit matching & approval workflow."""

import sqlite3
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .banking import commit_bank_rows, parse_bank_file
from .reports import fmt_date, fmt_money, fmt_unit
from .store import Problem
from .theme import COLORS, FONT
from .ui_widgets import Dialog

ACTION_LABELS = {
    "payment": "תשלום דייר",
    "income": "הכנסה אחרת",
    "expense": "הוצאה",
    "ignore": "אינו קשור לוועד",
    "skip": "דילוג",
}


def render_bank_import(app, parent):
    """Render the interactive bank statement reconciliation screen inside `parent`."""
    state = {"rows": [], "file": ""}
    units = app.ledger.units()
    unit_by_id = {u["id"]: fmt_unit(u) for u in units}
    unit_choices = {f"{fmt_unit(u)} · {u['tenant'] or u['owner'] or '—'} (#{u['id']})": u["id"] for u in units}
    id_to_unit_choice = {uid: lbl for lbl, uid in unit_choices.items()}

    income_cats = {
        r["name"]: r["id"]
        for r in app.store.rows("SELECT id, name FROM categories WHERE kind='income' AND active=1 ORDER BY name")
    }
    expense_cats = {
        r["name"]: r["id"]
        for r in app.store.rows("SELECT id, name FROM categories WHERE kind='expense' AND active=1 ORDER BY name")
    }

    info = ttk.Label(
        parent,
        text="ייבוא תנועות מקובץ Excel (.xlsx) או CSV שהורד מהבנק. המערכת מזהה דיירים אוטומטית ומונעת קליטה כפולה — כל שורה נבדקת לפני אישור.",
        anchor="e",
        foreground=COLORS["muted"],
    )
    info.pack(fill="x", pady=(0, 8))

    bar = app.bar(parent)
    summary_var = tk.StringVar(value="טרם נטען קובץ בנק")

    def load_file():
        path = filedialog.askopenfilename(
            parent=app,
            title="בחירת קובץ תנועות מהבנק",
            filetypes=[("קבצי Excel ו-CSV", "*.xlsx;*.csv"), ("Excel", "*.xlsx"), ("CSV", "*.csv"), ("כל הקבצים", "*.*")],
        )
        if not path:
            return
        try:
            state["rows"] = parse_bank_file(path, app.store, app.ledger)
            state["file"] = path
            refresh_table()
        except (Problem, OSError, sqlite3.Error, ValueError) as exc:
            app.error(exc)

    def selected_idx():
        sel = tree.selection()
        if not sel or sel[0] == "empty":
            raise Problem("יש לבחור תנועה בטבלה")
        return int(sel[0])

    def edit_row(_event=None):
        try:
            idx = selected_idx()
        except Problem as exc:
            app.error(exc)
            return
        item = state["rows"][idx]
        if item["already_status"]:
            messagebox.showinfo("כבר נקלט", "תנועה זו כבר נקלטה או סומנה בעבר ולא תיקלט שוב.", parent=app)
            return

        action_opts = (
            ("תשלום דייר", "הכנסה אחרת", "אינו קשור לוועד", "דילוג")
            if item["direction"] == "credit"
            else ("הוצאה", "אינו קשור לוועד", "דילוג")
        )
        cur_action_lbl = ACTION_LABELS.get(item["action"], "דילוג")
        if cur_action_lbl not in action_opts:
            cur_action_lbl = action_opts[0]

        cat_map = income_cats if item["direction"] == "credit" else expense_cats
        cat_names = tuple(cat_map.keys()) or ("אחר",)
        cur_cat = next((k for k, v in cat_map.items() if v == item.get("category_id")), cat_names[0])

        fields = [("action", "פעולה", cur_action_lbl, action_opts)]
        if item["direction"] == "credit":
            fields.append((
                "unit",
                "יחידת מגורים (לתשלום דייר)",
                id_to_unit_choice.get(item.get("unit_id"), "ללא בחירה"),
                ("ללא בחירה", *unit_choices.keys()),
            ))
        fields.append(("category", "קטגוריה (להכנסה אחרת / הוצאה)", cur_cat, cat_names))
        fields.append(("notes", "הערה", item.get("notes", ""), None))

        rev_action = {v: k for k, v in ACTION_LABELS.items()}

        def save(v):
            act = rev_action[v["action"]]
            item["action"] = act
            if item["direction"] == "credit":
                item["unit_id"] = unit_choices.get(v.get("unit"))
                if act == "payment" and not item["unit_id"]:
                    raise Problem("יש לבחור יחידת מגורים עבור תשלום דייר")
            item["category_id"] = cat_map.get(v["category"])
            item["notes"] = v["notes"].strip()
            refresh_table()

        Dialog(app, f"עריכת שיוך · {fmt_date(item['day'])} · {fmt_money(item['amount'])}", fields, save)

    def mark_ignored():
        try:
            idx = selected_idx()
            item = state["rows"][idx]
            if item["already_status"]:
                return
            item["action"] = "ignore"
            refresh_table()
        except Problem as exc:
            app.error(exc)

    def mark_skip():
        try:
            idx = selected_idx()
            item = state["rows"][idx]
            if item["already_status"]:
                return
            item["action"] = "skip"
            refresh_table()
        except Problem as exc:
            app.error(exc)

    def approve_all_high():
        count = 0
        for item in state["rows"]:
            if not item["already_status"] and item["direction"] == "credit" and item["suggested_unit"] and item["confidence"] == "גבוהה":
                item["action"] = "payment"
                item["unit_id"] = item["suggested_unit"]
                count += 1
        refresh_table()
        app.status.set(f"סומנו לאישור {count} התאמות בביטחון גבוה")

    def commit():
        ready = [r for r in state["rows"] if not r["already_status"] and r["action"] != "skip"]
        if not ready:
            raise Problem("אין שורות מסומנות לקליטה או לסימון כלא קשורות")
        to_post = sum(1 for r in ready if r["action"] in ("payment", "income", "expense"))
        to_ignore = sum(1 for r in ready if r["action"] == "ignore")
        if not messagebox.askyesno(
            "אישור קליטת תנועות בנק",
            f"לקלוט {to_post} תנועות לקופה ולסמן {to_ignore} תנועות כלא קשורות לוועד?",
            parent=app,
        ):
            return
        imported, ignored = commit_bank_rows(app.store, app.ledger, state["rows"], actor=app.user)
        # Re-parse file to reflect imported status
        if state["file"]:
            state["rows"] = parse_bank_file(state["file"], app.store, app.ledger)
            refresh_table()
        app.status.set(f"ייבוא הושלם: נקלטו {imported} תנועות, סומנו כלא קשורות {ignored}")
        messagebox.showinfo(
            "ייבוא בנק הושלם",
            f"נקלטו בהצלחה {imported} תנועות כספיות.\nסומנו כלא קשורות לוועד: {ignored}.",
            parent=app,
        )

    app.button(bar, "טעינת קובץ בנק (Excel / CSV)", load_file, primary=True)
    app.button(bar, "עריכת שיוך", edit_row)
    app.button(bar, "סמן כלא קשור לוועד", mark_ignored)
    app.button(bar, "דלג", mark_skip)
    app.button(bar, "אשר התאמות גבוהות", approve_all_high)
    app.button(bar, "קליטת שורות מאושרות", commit, primary=True)

    ttk.Label(parent, textvariable=summary_var, anchor="e", font=(FONT, 10, "bold")).pack(fill="x", pady=(0, 6))

    tree = app.table(
        ("תאריך", "כיוון", "תיאור מהבנק", "סכום", "אסמכתא", "יחידה מוצעת / שיוך", "ביטחון", "פעולה מתוכננת", "סטטוס"),
        height=14,
        parent=parent,
    )
    tree.bind("<Double-1>", edit_row)

    def refresh_table():
        rows_data = []
        ready_count = 0
        dup_count = 0
        for idx, item in enumerate(state["rows"]):
            dir_lbl = "זכות (כניסה)" if item["direction"] == "credit" else "חובה (יציאה)"
            unit_lbl = unit_by_id.get(item["unit_id"], "—") if item["action"] == "payment" else (item["reason"] or "—")
            if item["already_status"] == "matched":
                status_lbl = "נקלט בעבר"
                act_lbl = "כפילות נמנעה"
                tag = "reversed"
                dup_count += 1
            elif item["already_status"] == "ignored":
                status_lbl = "סומן בעבר כלא קשור"
                act_lbl = "כפילות נמנעה"
                tag = "reversed"
                dup_count += 1
            else:
                act_lbl = ACTION_LABELS.get(item["action"], "דילוג")
                if item["action"] in ("payment", "income", "expense"):
                    status_lbl = "מוכן לקליטה"
                    tag = "paid"
                    ready_count += 1
                elif item["action"] == "ignore":
                    status_lbl = "יסומן כלא קשור"
                    tag = "partial"
                else:
                    status_lbl = "ממתין לבדיקה"
                    tag = ""
            rows_data.append((
                idx,
                (
                    fmt_date(item["day"]),
                    dir_lbl,
                    item["description"][:46],
                    fmt_money(item["amount"]),
                    item["reference"],
                    unit_lbl,
                    item["confidence"],
                    act_lbl,
                    status_lbl,
                ),
                tag,
            ))
        app.fill_tagged(tree, rows_data)
        summary_var.set(
            f"סה״כ שורות בקובץ: {len(state['rows'])}   ·   מוכנות לקליטה: {ready_count}   ·   כפילויות שזוהו ונמנעו: {dup_count}"
        )
