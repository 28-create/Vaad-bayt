"""Settings sub-pages: 2x2 SaaS Card Grid, Users & RBAC, Audit Log, Categories, Excel Loader, and Backups."""

from datetime import date
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .__version__ import __version__
from .ledger import LABELS
from .reports import export_full_archive, fmt_date, fmt_money
from .store import Problem, ROLES, money
from .theme import COLORS, FONT
from .ui_widgets import ActionButton, CardFrame, Dialog

ACTION_NAMES = {
    "setup": "הגדרת מערכת",
    "login": "כניסה למערכת",
    "create_user": "יצירת משתמש",
    "update_user": "עדכון משתמש",
    "reset_password": "איפוס סיסמה",
    "add_unit": "הוספת יחידה",
    "update_unit": "עדכון יחידה",
    "replace_resident": "החלפת דייר",
    "change_rate": "שינוי תעריף",
    "opening_balance": "יתרת פתיחה דייר",
    "update_opening_cashbox": "עדכון יתרות בנק/מזומן",
    "cash_transfer": "העברה פנימית בנק↔מזומן",
    "adjust_charge": "תיקון חיוב / פטור",
    "post_payment": "רישום תשלום דייר",
    "post_expense": "רישום הוצאה",
    "post_income": "רישום הכנסה",
    "reverse_entry": "ביטול פעולה",
    "add_category": "הוספת קטגוריה",
    "update_category": "עדכון קטגוריה",
    "add_supplier": "הוספת ספק",
    "update_supplier": "עדכון ספק",
    "add_recurring": "הוספת הוצאה קבועה",
    "update_recurring": "עדכון הוצאה קבועה",
    "match_recurring": "שיוך הוצאה קבועה",
    "add_attachment": "צירוף מסמך",
    "delete_attachment": "הסרת מסמך",
    "bank_import": "ייבוא בנק",
    "load_excel_seed": "טעינת נתוני אקסל שחראי",
    "backup": "יצירת גיבוי",
}


def render_settings_home(app):
    is_admin = app.can("manage_settings")

    sections = [
        ("🏢 פרטי ועד הבית וקופה (בנק / מזומן)", "הגדרות המתחם, יתרות פתיחה, תעריפים וקטגוריות", COLORS["action"], [
            ("עריכת פרטים כלליים", app.general, is_admin, "soft"),
            ("עדכון יתרות פתיחה (בנק / מזומן)", lambda: edit_opening_cashbox(app), is_admin, "soft"),
            ("תעריף ברירת מחדל", app.default_rate, app.can("manage_rates"), "secondary"),
            ("ניהול קטגוריות", lambda: app.show(7, "categories"), is_admin, "secondary"),
        ]),
        ("📋 נתוני אקסל שחראי 14, 16 ו-18", "טעינה בטוחה של 21 הדירות, 2025–2027 ושיק פיצויים", COLORS["success"], [
            ("טעינת 21 הדירות ונתוני האקסל (2025–2027)", lambda: load_excel_dialog(app), is_admin, "primary"),
            ("ייצוא רשימת דיירים ל-Excel", app.export_data, True, "secondary"),
        ]),
        ("🔐 משתמשים, הרשאות ואבטחה", "ניהול מנהלים, חברי ועד, צופים, יומן פעולות ונעילה", COLORS["info"], [
            ("ניהול משתמשים והרשאות", lambda: app.show(7, "users"), app.can("manage_users"), "soft"),
            ("יומן פעולות (Audit Log)", lambda: app.show(7, "audit"), app.can("view_audit"), "soft"),
            ("שינוי סיסמה אישית", app.password, True, "secondary"),
            ("נעילה אוטומטית", lambda: edit_auto_lock(app), is_admin, "secondary"),
            ("נעילה והתנתקות", app.lock, True, "danger"),
        ]),
        ("💾 גיבוי, שחזור והעברה למחשב חדש", "גיבוי ZIP מלא הכולל מסד נתונים וכל המסמכים המצורפים", COLORS["warning"], [
            ("יצירת גיבוי מלא (כולל מסמכים)", app.backup, app.can("backup"), "primary"),
            ("שחזור מגיבוי", app.restore, app.can("restore"), "secondary"),
            ("הגדרות גיבוי אוטומטי ותיקייה", lambda: edit_backup_settings(app), is_admin, "secondary"),
            ("היסטוריית גיבויים", lambda: app.show(7, "backups"), app.can("backup"), "soft"),
            ("ייצוא מלא למעבר לתוכנה אחרת (ZIP)", lambda: full_export(app), app.can("backup"), "secondary"),
        ]),
    ]

    grid = tk.Frame(app.main, bg=COLORS["background"])
    grid.pack(fill="x", pady=(0, 12))
    grid.columnconfigure(0, weight=1, uniform="setcol")
    grid.columnconfigure(1, weight=1, uniform="setcol")

    for idx, (title, subtitle, accent, actions) in enumerate(sections):
        r, c = idx // 2, 1 - (idx % 2)
        card = CardFrame(grid, padx=16, pady=14)
        card.grid(row=r, column=c, sticky="nsew", padx=5, pady=5)
        body = card.inner

        top = tk.Frame(body, bg=COLORS["surface"])
        top.pack(fill="x", pady=(0, 8))
        tk.Frame(top, bg=accent, width=4, height=30).pack(side="right", fill="y", padx=(10, 0))
        hdr_txt = tk.Frame(top, bg=COLORS["surface"])
        hdr_txt.pack(side="right", fill="x", expand=True)
        tk.Label(hdr_txt, text=title, bg=COLORS["surface"], fg=COLORS["text"], font=(FONT, 11, "bold"), anchor="e").pack(fill="x")
        tk.Label(hdr_txt, text=subtitle, bg=COLORS["surface"], fg=COLORS["muted"], font=(FONT, 8), anchor="e").pack(fill="x")

        btn_wrap = tk.Frame(body, bg=COLORS["surface"])
        btn_wrap.pack(fill="x", pady=(4, 0))
        for i, (label, action, allowed, variant) in enumerate(actions):
            btn_row = i // 2
            btn_col = 1 - (i % 2)
            btn_wrap.columnconfigure(btn_col, weight=1)
            ActionButton(
                btn_wrap, label, action, variant=variant, disabled=not allowed, padx=10, pady=6,
            ).grid(row=btn_row, column=btn_col, sticky="ew", padx=3, pady=3)

    # Clean system health footer card
    info_card = CardFrame(app.main, padx=16, pady=12)
    info_card.pack(fill="x")
    ib = info_card.inner

    last = app.store.get("last_backup")
    stale = not last or (date.today() - date.fromisoformat(last[:10])).days >= 7
    auto_on = app.store.get("auto_backup", "1") == "1"
    auto_txt = f"גיבוי אוטומטי פעיל (שומר {app.store.get('auto_backup_keep', '10')} אחרונים)" if auto_on else "גיבוי אוטומטי כבוי"
    msg = f"גיבוי אחרון: {fmt_date(last[:10])}" if last else "טרם נוצר גיבוי"
    tk.Label(
        ib,
        text=f"{msg}{' · מומלץ ליצור גיבוי כעת' if stale else ''}   •   {auto_txt}",
        bg=COLORS["surface"], fg=COLORS["warning"] if stale else COLORS["success"],
        anchor="e", font=(FONT, 10, "bold"),
    ).pack(fill="x", pady=(0, 4))

    bals = app.ledger.balances()
    lock_mins = app.store.get("auto_lock_minutes", "15")
    tk.Label(
        ib,
        text=f"יתרה בבנק: {fmt_money(bals['bank'])}   •   יתרה במזומן: {fmt_money(bals['cash'])}   •   נעילה אוטומטית: {lock_mins} דקות",
        bg=COLORS["surface"], fg=COLORS["text_secondary"], anchor="e", font=(FONT, 9),
    ).pack(fill="x")
    tk.Label(
        ib,
        text=f"גרסה {__version__} · {app.store.path} · משתמש: {app.user['display_name']} ({ROLES.get(app.user['role'], '')})",
        bg=COLORS["surface"], fg=COLORS["muted"], anchor="e", font=(FONT, 8),
    ).pack(fill="x", pady=(2, 0))


def edit_opening_cashbox(app):
    cur_bank = int(app.store.get("initial_bank", app.store.get("initial", "0")) or "0")
    cur_cash = int(app.store.get("initial_cash", "0") or "0")
    fmt_num = lambda v: f"{v / 100:.2f}"
    fields = [
        ("bank", "יתרת פתיחה בבנק (₪)", fmt_num(cur_bank), None),
        ("cash", "יתרת פתיחה במזומן (₪)", fmt_num(cur_cash), None),
    ]

    def save(v):
        app.ledger.set_opening_cashbox(money(v["bank"]), money(v["cash"]), actor=app.user)
        app.refresh("יתרות הפתיחה (בנק ומזומן) עודכנו")

    Dialog(app, "עדכון יתרות פתיחה לקופה", fields, save)


def load_excel_dialog(app):
    bals = app.ledger.balances()
    fmt_num = lambda v: f"{v / 100:.2f}"
    fields = [
        ("bank", "יתרה נוכחית אמיתית בבנק (₪)", fmt_num(bals["bank"]), None),
        ("cash", "יתרה נוכחית אמיתית במזומן (₪)", fmt_num(bals["cash"]), None),
    ]

    def save(v):
        count = app.ledger.load_shahrai_excel_data(
            target_bank=money(v["bank"]),
            target_cash=money(v["cash"]),
            actor=app.user,
        )
        app.refresh(f"נתוני האקסל נטענו ({count} תשלומי חודשים נוספו) ויתרות הבנק/מזומן נשמרו")
        messagebox.showinfo(
            "טעינת נתוני אקסל הושלמה",
            f"כל 21 הדירות של שחראי 14, 16 ו-18 ונתוני השנים 2025–2027 (כולל שיק פיצויים) נטענו בהצלחה.\nתשלומים חדשים שנקלטו: {count}.",
            parent=app,
        )

    Dialog(
        app,
        "טעינת נתוני האקסל (שחראי 14, 16, 18)",
        fields,
        save,
        footer=lambda _, bar: tk.Label(
            bar,
            text="הפעולה בטוחה ואינה יוצרת כפילויות. הזינו את היתרות האמיתיות בבנק ובמזומן.",
            bg=COLORS["surface_alt"], fg=COLORS["muted"], anchor="e", font=(FONT, 8),
        ).pack(side="bottom", fill="x", pady=(0, 8)),
    )


def edit_backup_settings(app):
    auto_val = "פעיל" if app.store.get("auto_backup", "1") == "1" else "כבוי"
    fields = [
        ("folder", "תיקיית גיבוי (מקומית או USB)", app.store.get("backup"), "folder"),
        ("auto", "גיבוי אוטומטי יומי ובסגירה", auto_val, ("פעיל", "כבוי")),
        ("keep", "מספר גיבויים אוטומטיים לשמירה", app.store.get("auto_backup_keep", "10"), None),
    ]

    def save(v):
        if not v["folder"].strip():
            raise Problem("יש לבחור תיקיית גיבוי")
        try:
            keep = int(v["keep"])
            if keep < 1 or keep > 100:
                raise ValueError
        except ValueError:
            raise Problem("מספר הגיבויים לשמירה חייב להיות בין 1 ל-100")
        app.store.save(
            backup=v["folder"].strip(),
            auto_backup="1" if v["auto"] == "פעיל" else "0",
            auto_backup_keep=str(keep),
        )
        app.refresh("הגדרות הגיבוי נשמרו")

    Dialog(app, "הגדרות גיבוי אוטומטי ותיקייה", fields, save)


def edit_auto_lock(app):
    fields = [
        ("minutes", "דקות חוסר פעילות לפני נעילה (0 לביטול)", app.store.get("auto_lock_minutes", "15"), None),
    ]

    def save(v):
        try:
            mins = int(v["minutes"])
            if mins < 0 or mins > 240:
                raise ValueError
        except ValueError:
            raise Problem("יש להזין מספר דקות בין 0 ל-240")
        app.store.save(auto_lock_minutes=str(mins))
        app.refresh("הגדרת הנעילה האוטומטית נשמרה")

    Dialog(app, "נעילה אוטומטית", fields, save)


def full_export(app):
    path = filedialog.asksaveasfilename(
        parent=app,
        title="ייצוא מלא של כל נתוני המערכת",
        initialfile=f"vaad-full-export-{date.today().isoformat()}.zip",
        defaultextension=".zip",
        filetypes=[("ארכיון ZIP מלא", "*.zip")],
    )
    if not path:
        return
    export_full_archive(app.store, app.ledger, path)
    app.status.set("הייצוא המלא נשמר בהצלחה")
    messagebox.showinfo("ייצוא מלא הושלם", f"כל הנתונים והקבצים המצורפים יוצאו אל:\n{path}", parent=app)


def render_users_page(app):
    bar = app.bar()
    app.button(bar, "+ משתמש חדש", lambda: edit_user(None), primary=True)
    app.button(bar, "עריכת משתמש", lambda: edit_user(app.selection(tree)), variant="soft")
    app.button(bar, "איפוס סיסמה", lambda: reset_pwd(app.selection(tree)))
    app.button(bar, "חזרה להגדרות", lambda: app.show(7))

    users = {u["id"]: u for u in app.store.list_users()}
    tree = app.table(("שם משתמש", "שם תצוגה", "הרשאה", "מצב", "נוצר בתאריך"))
    app.fill(tree, [
        (u["id"], (u["username"], u["display_name"], ROLES[u["role"]], "פעיל" if u["active"] else "מושבת", fmt_date(u["created_at"][:10])))
        for u in users.values()
    ])

    role_labels = tuple(ROLES.values())
    rev_roles = {v: k for k, v in ROLES.items()}

    def edit_user(uid):
        row = users.get(uid)
        if row:
            fields = [
                ("display_name", "שם תצוגה", row["display_name"], None),
                ("role", "רמת הרשאה", ROLES[row["role"]], role_labels),
                ("active", "מצב", "פעיל" if row["active"] else "מושבת", ("פעיל", "מושבת")),
            ]

            def save(v):
                app.store.update_user(uid, v["display_name"], rev_roles[v["role"]], v["active"] == "פעיל", actor=app.user)
                app.refresh("פרטי המשתמש עודכנו")

            Dialog(app, f"עריכת משתמש · {row['username']}", fields, save)
        else:
            fields = [
                ("username", "שם משתמש (באנגלית או ספרות)", "", None),
                ("display_name", "שם מלא לתצוגה", "", None),
                ("role", "רמת הרשאה", ROLES["member"], role_labels),
                ("password", "סיסמה (לפחות 8 תווים)", "", "password"),
                ("confirm", "אימות סיסמה", "", "password"),
            ]

            def save(v):
                if v["password"] != v["confirm"]:
                    raise Problem("הסיסמאות אינן זהות")
                app.store.create_user(v["username"], v["display_name"], rev_roles[v["role"]], v["password"], actor=app.user)
                app.refresh("המשתמש נוצר בהצלחה")

            Dialog(app, "משתמש חדש", fields, save)

    def reset_pwd(uid):
        row = users[uid]
        fields = [
            ("new", "סיסמה חדשה (לפחות 8 תווים)", "", "password"),
            ("confirm", "אימות סיסמה חדשה", "", "password"),
        ]

        def save(v):
            if v["new"] != v["confirm"]:
                raise Problem("הסיסמאות אינן זהות")
            app.store.reset_user_password(uid, v["new"], actor=app.user)
            app.refresh("הסיסמה אופסה בהצלחה")

        Dialog(app, f"איפוס סיסמה · {row['display_name']}", fields, save)


def render_audit_page(app):
    bar = app.bar()
    query = app.input(bar, "חיפוש ביומן", width=24)
    app.button(bar, "ייצוא Excel", lambda: app.export_xlsx_report("יומן פעולות", headers, current_rows()), variant="soft")
    app.button(bar, "חזרה להגדרות", lambda: app.show(7))

    headers = ("מועד", "משתמש", "פעולה", "ישות", "פרטים")
    tree = app.table(headers, height=16)

    def current_rows():
        return [
            (
                r["id"],
                (
                    f"{fmt_date(r['ts'][:10])} {r['ts'][11:19]}",
                    r["username"] or "מערכת",
                    ACTION_NAMES.get(r["action"], r["action"]),
                    f"{r['entity_type']} #{r['entity_id']}".strip(" #") if r["entity_id"] else r["entity_type"],
                    r["details"],
                ),
            )
            for r in app.store.audit_entries(limit=500, query=query.get())
        ]

    def load(*_):
        app.fill(tree, current_rows())

    query.trace_add("write", load)
    load()


def render_backups_page(app):
    bar = app.bar()
    app.button(bar, "יצירת גיבוי מלא כעת", app.backup, primary=True)
    app.button(bar, "שחזור מגיבוי", app.restore, variant="soft")
    app.button(bar, "חזרה להגדרות", lambda: app.show(7))

    kind_labels = {"manual": "ידני", "auto": "אוטומטי", "pre-restore": "לפני שחזור"}
    rows = []
    for r in app.store.backup_history(100):
        kb = max(1, (r["size_bytes"] + 1023) // 1024)
        exists = "קיים" if Path(r["path"]).is_file() else "הועבר / נמחק"
        rows.append((
            r["id"],
            (
                f"{fmt_date(r['ts'][:10])} {r['ts'][11:19]}",
                kind_labels.get(r["kind"], r["kind"]),
                f"{kb:,} KB",
                str(r["attachments_count"]),
                exists,
                r["path"],
            ),
        ))
    app.table(("מועד", "סוג", "גודל", "מסמכים", "מצב קובץ", "נתיב"), rows, height=15)


def render_categories_page(app):
    bar = app.bar()
    app.button(bar, "+ קטגוריה חדשה", lambda: edit(None), primary=True)
    app.button(bar, "עריכת קטגוריה", lambda: edit(app.selection(tree)), variant="soft")
    app.button(bar, "חזרה להגדרות", lambda: app.show(7))
    items = {r["id"]: r for r in app.store.rows("SELECT * FROM categories ORDER BY kind,name")}
    tree = app.table(
        ("שם", "סוג", "מצב"),
        [(r["id"], (r["name"], LABELS[r["kind"]], "פעילה" if r["active"] else "לא פעילה")) for r in items.values()],
    )

    def edit(id_):
        row = items[id_] if id_ else None
        kind_lookup = {LABELS[k]: k for k in ("expense", "income")}

        def save(v):
            app.ledger.category(
                row["kind"] if row else kind_lookup[v["kind"]],
                v["name"],
                id_,
                v.get("active") != "לא פעילה",
                actor=app.user,
            )
            app.refresh("הקטגוריה נשמרה")

        fields = [("name", "שם", row["name"] if row else "", None)]
        if row:
            fields.append(("active", "מצב", "פעילה" if row["active"] else "לא פעילה", ("פעילה", "לא פעילה")))
        else:
            fields.append(("kind", "סוג", LABELS["expense"], tuple(kind_lookup)))
        Dialog(app, "קטגוריה", fields, save)
