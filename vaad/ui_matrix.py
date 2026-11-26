"""Excel-style 12-month Annual Collection Matrix (2025 / 2026 / 2027) with 1-click Quick Pay."""

from datetime import date
import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk

from .ledger import ACCOUNTS, METHODS, default_account
from .reports import fmt_date, fmt_money, fmt_unit
from .seed_data import HEBREW_MONTHS, HEBREW_MONTHS_SHORT
from .store import Problem
from .theme import COLORS, FONT
from .ui_widgets import MetricCard

CELL_SYMBOLS = {
    "paid": "✓",
    "unpaid": "✗",
    "partial": "◐",
    "exempt": "פטור",
    "future": "·",
}


def render_annual_matrix(app):
    """Render the interactive 12-month Excel-style collection grid for Shahrai 14, 16, 18."""
    state = app.mode if isinstance(app.mode, dict) else {}
    year = int(state.get("year", date.today().year))
    building = state.get("building", "הכול")

    def reload_view(new_year=None, new_building=None):
        app.show(1, {
            "year": new_year if new_year is not None else year,
            "building": new_building if new_building is not None else building,
        })

    # Top bar: Year switcher + Building filter pills + Search
    top = app.bar()
    ttk.Label(top, text="שנה:", font=(FONT, 10, "bold")).pack(side="right", padx=(6, 4))
    for yr in (2025, 2026, 2027):
        app.button(top, str(yr), lambda y=yr: reload_view(new_year=y), primary=(year == yr))

    ttk.Label(top, text="  |  בניין:", font=(FONT, 10, "bold")).pack(side="right", padx=(6, 4))
    for b_lbl, b_val in (("הכול", "הכול"), ("בניין 14", "14"), ("בניין 16", "16"), ("בניין 18", "18")):
        app.button(top, b_lbl, lambda bv=b_val: reload_view(new_building=bv), primary=(building == b_val))

    query = app.input(top, "חיפוש דייר", width=16)

    # Data
    b_filter = None if building == "הכול" else building
    matrix = app.ledger.annual_matrix(year, building_filter=b_filter)

    # Mini KPI summary strip
    total_paid_amt = sum(r["paid_amount"] for r in matrix)
    total_debt_amt = sum(r["debt_now"] for r in matrix)
    fully_paid_units = sum(1 for r in matrix if r["unpaid_due_count"] == 0)
    total_paid_months = sum(r["paid_count"] for r in matrix)

    kpi_frame = ttk.Frame(app.main)
    kpi_frame.pack(fill="x", pady=(0, 8))
    for col in range(4):
        kpi_frame.columnconfigure(col, weight=1, uniform="mkpi")
    cards = [
        (f"יחידות מעודכנות ({year})", f"{fully_paid_units} / {len(matrix)}", "ללא פיגור לתקופה", COLORS["success"]),
        (f"סך גבייה ({year})", fmt_money(total_paid_amt), f"{total_paid_months} חודשי תשלום", COLORS["action"]),
        ("חוב פתוח נוכחי" if year >= 2026 else f"לא שולם ({year})", fmt_money(total_debt_amt), "לתשלום מיידי" if year >= 2026 else "שנת 2025 היסטורית", COLORS["danger"] if total_debt_amt > 0 else COLORS["success"]),
        ("מקרא טבלה", "✓ שולם   ✗ לא שולם", "לחיצה כפולה על שורה לסימון תשלום", COLORS["info"]),
    ]
    for i, (t, v, s, c) in enumerate(cards):
        MetricCard(kpi_frame, t, v, s, c).grid(row=0, column=3 - i, sticky="nsew", padx=4)

    # Actions bar
    actions = app.bar()
    if year >= 2026:
        app.button(actions, "✓ סימון תשלום מהיר (חודשים)", lambda: quick_pay_dialog(app, tree, year, matrix), primary=True, perm="record_payment")
    app.button(actions, "פתיחת כרטסת דייר", lambda: app.unit_detail(app.selection(tree)))
    app.button(actions, "ייצוא Excel (.xlsx)", lambda: export_matrix(app, year, headers, current_rows, "xlsx"))
    app.button(actions, "ייצוא PDF", lambda: export_matrix(app, year, headers, current_rows, "pdf"))
    app.button(actions, "הדפסה", lambda: export_matrix(app, year, headers, current_rows, "print"))

    # Table headers
    if year == 2025:
        headers = ("בניין", "דייר", "תעריף", *HEBREW_MONTHS_SHORT, "שולם", "שיק פיצויים", "ביצוע")
    else:
        headers = ("בניין", "דייר", "תעריף", *HEBREW_MONTHS_SHORT, "חודשים", "שולם", "חוב")

    tree = app.table(headers, height=16)
    # Tighten month column widths so all 12 months fit comfortably on screen without scrolling!
    num_cols = len(headers)
    for col_idx, label in enumerate(reversed(headers)):
        if label in HEBREW_MONTHS_SHORT:
            tree.column(col_idx, width=42, minwidth=36, anchor="center")
        elif label == "בניין":
            tree.column(col_idx, width=62, minwidth=54, anchor="center")
        elif label == "תעריף":
            tree.column(col_idx, width=68, minwidth=58, anchor="e")
        elif label == "דייר":
            tree.column(col_idx, width=135, minwidth=100, anchor="e")
        elif label == "חודשים":
            tree.column(col_idx, width=58, minwidth=50, anchor="center")
        elif label in ("שיק פיצויים", "ביצוע"):
            tree.column(col_idx, width=82, minwidth=68, anchor="center")
        else:
            tree.column(col_idx, width=86, minwidth=72, anchor="e")

    current_rows = []

    def load(*_):
        nonlocal current_rows
        needle = query.get().strip().casefold()
        tagged = []
        plain = []
        for item in matrix:
            u = item["unit"]
            bldg_txt = f"בניין {u['building']}"
            sub_suffix = f" ({u['subunit']})" if u["subunit"] else ""
            name_txt = f"{item['display_name']}{sub_suffix}"
            if needle and needle not in f"{bldg_txt} {name_txt} {u['apartment']} {u['owner']} {u['tenant']}".casefold():
                continue

            symbols = [CELL_SYMBOLS[s] for s in item["months"]]
            if year == 2025:
                vals = (
                    bldg_txt, name_txt, f"{item['rate'] // 100} ₪",
                    *symbols, fmt_money(item["paid_amount"]),
                    item["comp_amount"] or "—", item["comp_status"] or "—",
                )
            else:
                vals = (
                    bldg_txt, name_txt, f"{item['rate'] // 100} ₪",
                    *symbols, f"{item['paid_count']}/12",
                    fmt_money(item["paid_amount"]), fmt_money(item["debt_now"]),
                )

            if item["unpaid_due_count"] == 0:
                tag = "paid"
            elif item["paid_count"] > 0:
                tag = "partial"
            else:
                tag = "debt"
            plain.append((u["id"], vals))
            tagged.append((u["id"], vals, tag))

        current_rows = plain
        app.fill_tagged(tree, tagged)

    query.trace_add("write", load)
    if year >= 2026 and app.can("record_payment"):
        tree.bind("<Double-1>", lambda e: quick_pay_dialog(app, tree, year, matrix, forced_uid=int(tree.identify_row(e.y)))
                  if tree.identify_row(e.y).isdigit() else None)
    else:
        tree.bind("<Double-1>", lambda e: app.unit_detail(int(tree.identify_row(e.y)))
                  if tree.identify_row(e.y).isdigit() else None)
    load()


def export_matrix(app, year, headers, rows, fmt):
    title = f"לוח גבייה שנתי · {year}"
    if fmt == "xlsx":
        app.export_xlsx_report(title, headers, rows)
    elif fmt == "pdf":
        app.export_pdf_report(title, headers, rows, subtitle=f"שנת {year}")
    else:
        app.print_report(title, headers, rows, subtitle=f"שנת {year}")


def quick_pay_dialog(app, tree, year, matrix, forced_uid=None):
    """Dead-simple 1-click multi-month payment dialog directly from the Annual Matrix."""
    app.require("record_payment")
    uid = forced_uid if forced_uid is not None else app.selection(tree)
    item = next((m for m in matrix if m["unit"]["id"] == uid), None)
    if not item:
        raise Problem("יש לבחור דייר בטבלה")

    u = item["unit"]
    rate = item["rate"] or 10000

    win = tk.Toplevel(app)
    win.title(f"תשלום מהיר · {item['display_name']} ({fmt_unit(u)})")
    win.transient(app)
    win.grab_set()
    win.resizable(False, False)
    win.configure(bg=COLORS["background"])

    panel = ttk.Frame(win, padding=20)
    panel.pack(fill="both", expand=True)

    ttk.Label(
        panel,
        text=f"בניין {u['building']} · {item['display_name']}   (תעריף: {fmt_money(rate)} לחודש)",
        font=(FONT, 13, "bold"),
        anchor="e",
    ).pack(fill="x", pady=(0, 6))
    ttk.Label(
        panel,
        text=f"סמנו את החודשים ששולמו לשנת {year}:",
        foreground=COLORS["muted"],
        anchor="e",
    ).pack(fill="x", pady=(0, 8))

    grid = tk.Frame(panel, bg=COLORS["surface"], highlightbackground=COLORS["border"], highlightthickness=1, padx=14, pady=12)
    grid.pack(fill="x", pady=(0, 12))

    month_vars = {}
    total_var = tk.StringVar()

    def update_total(*_):
        selected = [m for m, var in month_vars.items() if var.get()]
        total_var.set(f"נבחרו {len(selected)} חודשים   ·   סך לתשלום: {fmt_money(len(selected) * rate)}")

    for idx in range(12):
        mo = idx + 1
        st = item["months"][idx]
        already_paid = st in ("paid", "exempt")
        var = tk.BooleanVar(value=False)
        row_i = idx // 4
        col_i = 3 - (idx % 4)
        grid.columnconfigure(col_i, weight=1)

        if already_paid:
            lbl = tk.Label(
                grid,
                text=f"✓ {HEBREW_MONTHS[idx]}",
                bg=COLORS["success_bg"],
                fg=COLORS["success"],
                font=(FONT, 9, "bold"),
                padx=8,
                pady=5,
            )
            lbl.grid(row=row_i, column=col_i, sticky="ew", padx=4, pady=4)
        else:
            month_vars[mo] = var
            var.trace_add("write", update_total)
            cb = tk.Checkbutton(
                grid,
                text=HEBREW_MONTHS[idx],
                variable=var,
                bg=COLORS["surface"],
                activebackground=COLORS["surface_alt"],
                fg=COLORS["danger"] if st == "unpaid" else COLORS["text"],
                font=(FONT, 9, "bold" if st == "unpaid" else "normal"),
                anchor="e",
                padx=6,
                pady=4,
            )
            cb.grid(row=row_i, column=col_i, sticky="ew", padx=4, pady=4)

    # Quick select unpaid button
    def select_all_unpaid():
        for mo, var in month_vars.items():
            if item["months"][mo - 1] in ("unpaid", "partial"):
                var.set(True)

    sel_bar = ttk.Frame(panel)
    sel_bar.pack(fill="x", pady=(0, 8))
    ttk.Label(sel_bar, textvariable=total_var, font=(FONT, 11, "bold"), foreground=COLORS["action"]).pack(side="right")
    ttk.Button(sel_bar, text="בחר את כל החודשים שבפיגור", command=select_all_unpaid).pack(side="left")
    update_total()

    # Payment details
    form = ttk.Frame(panel)
    form.pack(fill="x", pady=(4, 12))

    day_var = tk.StringVar(value=fmt_date(date.today().isoformat()))
    method_var = tk.StringVar(value="העברה בנקאית")
    account_var = tk.StringVar(value="בנק")
    ref_var = tk.StringVar()
    notes_var = tk.StringVar()

    def sync_account(*_):
        account_var.set(ACCOUNTS[default_account(method_var.get())])

    method_var.trace_add("write", sync_account)

    form_rows = [
        ("תאריך תשלום", ttk.Entry(form, textvariable=day_var, justify="right", width=26)),
        ("אמצעי תשלום", ttk.Combobox(form, textvariable=method_var, values=METHODS, state="readonly", justify="right", width=24)),
        ("קופה (בנק / מזומן)", ttk.Combobox(form, textvariable=account_var, values=("בנק", "מזומן"), state="readonly", justify="right", width=24)),
        ("אסמכתא", ttk.Entry(form, textvariable=ref_var, justify="right", width=26)),
        ("הערה", ttk.Entry(form, textvariable=notes_var, justify="right", width=26)),
    ]
    for r_idx, (lbl, widget) in enumerate(form_rows):
        ttk.Label(form, text=lbl, anchor="e").grid(row=r_idx, column=1, sticky="e", padx=(12, 0), pady=4)
        widget.grid(row=r_idx, column=0, sticky="ew", pady=4)
    form.columnconfigure(0, weight=1)

    def commit():
        periods = [f"{year:04d}-{mo:02d}" for mo, var in month_vars.items() if var.get()]
        if not periods:
            raise Problem("יש לסמן לפחות חודש אחד לתשלום")
        rev_acct = {"בנק": "bank", "מזומן": "cash"}
        day_iso = "-".join(reversed(day_var.get().strip().split("/"))) if "/" in day_var.get() else day_var.get().strip()
        try:
            ids = app.ledger.quick_pay_months(
                uid, periods, day_iso, method_var.get(),
                account=rev_acct[account_var.get()],
                party=item["display_name"],
                reference=ref_var.get(),
                notes=notes_var.get(),
                actor=app.user,
            )
            win.destroy()
            app.refresh(f"נרשמו {len(ids)} חודשי תשלום עבור {item['display_name']} ({account_var.get()})")
            if ids and messagebox.askyesno("אישור תשלום", "התשלום נרשם בהצלחה! להפיק אישור תשלום (קבלה)?", parent=app):
                app.show_receipt(ids[-1])
        except (Problem, sqlite3.Error, ValueError) as exc:
            app.error(exc, win)

    tail = ttk.Frame(panel)
    tail.pack(fill="x")
    ttk.Button(tail, text="שמירת תשלום", style="Primary.TButton", command=commit).pack(side="right", padx=4)
    ttk.Button(tail, text="ביטול", command=win.destroy).pack(side="right", padx=4)
    win.bind("<Escape>", lambda _: win.destroy())
