"""Main Hebrew RTL Tkinter desktop application with modern Fintech/SaaS design (Shahrai 14, 16, 18)."""

from calendar import monthrange
from datetime import date
import logging
import os
from pathlib import Path
import sqlite3
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from uuid import uuid4

from .__version__ import APP_TITLE, __version__
from .excel import write_xlsx
from .ledger import ACCOUNTS, LABELS, Ledger, METHODS, default_account
from .reports import (
    build_receipt_html,
    build_report_html,
    export_csv,
    export_pdf,
    fmt_date,
    fmt_money,
    fmt_unit,
    monthly_chart_svg,
    open_printable_html,
)
from .store import Problem, ROLES, Store, configure_logging, has_permission, money, valid_day
from .theme import COLORS, FONT, ROW_HEIGHT
from .ui_bank import render_bank_import
from .ui_matrix import render_annual_matrix
from .ui_settings import (
    render_audit_page,
    render_backups_page,
    render_categories_page,
    render_settings_home,
    render_users_page,
)
from .ui_widgets import (
    ActionButton,
    AttachmentsDialog,
    BrandLogo,
    CardFrame,
    Dialog,
    IncomeExpenseChart,
    MetricCard,
    PillBadge,
    enable_hidpi,
    sort_key,
)

logger = logging.getLogger("vaad.ui")


def today():
    return date.today().isoformat()


def date_text(value):
    return fmt_date(value)


def iso(value):
    return "-".join(reversed(value.strip().split("/"))) if "/" in value else value.strip()


def amount(value):
    return fmt_money(value)


def number(value):
    sign = "-" if value < 0 else ""
    whole, remainder = divmod(abs(value), 100)
    return f"{sign}{whole}.{remainder:02d}"


def unit_name(unit):
    return fmt_unit(unit)


def _cell_to_excel(value):
    if isinstance(value, (int, float)):
        return value
    text = str(value or "").replace("\u200e", "").strip()
    if text.endswith("₪"):
        cleaned = text.replace("₪", "").replace(",", "").replace("−", "-").strip()
        try:
            return round(float(cleaned), 2)
        except ValueError:
            pass
    return text


class App(tk.Tk):
    NAV_GROUPS = (
        ("סקירה וגבייה", (
            (0, "🏠", "לוח בקרה"),
            (1, "📅", "לוח גבייה שנתי"),
            (2, "💳", "תשלומים ובנק"),
        )),
        ("ניהול שוטף", (
            (3, "🏢", "דיירים ודירות"),
            (4, "💰", "קופה ותנועות"),
            (5, "🔧", "ספקים"),
        )),
        ("דוחות ומערכת", (
            (6, "📊", "דוחות וניתוחים"),
            (7, "⚙️", "הגדרות וניהול"),
        )),
    )

    PAGES = (
        "לוח בקרה",
        "לוח גבייה שנתי",
        "תשלומים ובנק",
        "דיירים ודירות",
        "קופה ותנועות",
        "ספקים",
        "דוחות וניתוחים",
        "הגדרות וניהול",
    )

    PAGE_SUBTITLES = (
        "תמונת מצב עדכנית · שחראי 14, 16 ו-18",
        "מעקב חודשי מרוכז לכל 21 היחידות",
        "גבייה שוטפת, חובות פתוחים וייבוא דפי בנק",
        "ניהול יחידות מגורים וכרטסות אישיות",
        "ניהול קופה משותפת עם הפרדת בנק ומזומן",
        "ניהול ספקים, היסטוריית תשלומים וחשבוניות",
        "הפקת דוחות מקצועיים ל-Excel, PDF והדפסה",
        "הגדרות מערכת, הרשאות, יומן פעולות וגיבויים",
    )

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.ledger = Ledger(store)
        self.user = None
        self.logged = False
        self.last_activity = time.monotonic()
        self.page = 0
        self.mode = None

        self.title(APP_TITLE)
        self.geometry("1360x840")
        self.minsize(1040, 680)
        self.configure(bg=COLORS["background"])
        self._apply_icon()
        self._configure_styles()

        self.status = tk.StringVar()
        self.period = today()[:7]

        self.bind_all("<Key>", self._touch_activity, add="+")
        self.bind_all("<Button>", self._touch_activity, add="+")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.after(100, self.lock)
        self.after(60000, self.tick)

    def _apply_icon(self):
        icon_path = Path(__file__).with_name("icon.ico")
        if icon_path.is_file():
            try:
                self.iconbitmap(default=str(icon_path))
            except tk.TclError:
                pass

    def _configure_styles(self):
        self.option_add("*font", (FONT, 10))
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=COLORS["background"])
        style.configure("TLabel", background=COLORS["background"], foreground=COLORS["text"], padding=2)
        style.configure(
            "TEntry",
            fieldbackground=COLORS["surface"],
            foreground=COLORS["text"],
            bordercolor=COLORS["border_strong"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border_strong"],
            padding=(8, 5),
        )
        style.map("TEntry", bordercolor=[("focus", COLORS["action"])])
        style.configure(
            "TCombobox",
            fieldbackground=COLORS["surface"],
            background=COLORS["surface"],
            foreground=COLORS["text"],
            bordercolor=COLORS["border_strong"],
            arrowcolor=COLORS["muted"],
            padding=(8, 5),
        )
        style.map("TCombobox", fieldbackground=[("readonly", COLORS["surface"])], bordercolor=[("focus", COLORS["action"])])
        style.configure(
            "Treeview",
            rowheight=ROW_HEIGHT,
            background=COLORS["surface"],
            fieldbackground=COLORS["surface"],
            foreground=COLORS["text"],
            borderwidth=0,
            relief="flat",
        )
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure(
            "Treeview.Heading",
            background=COLORS["surface_alt"],
            foreground=COLORS["muted"],
            bordercolor=COLORS["border"],
            relief="flat",
            padding=(8, 10),
            font=(FONT, 9, "bold"),
        )
        style.map("Treeview.Heading", background=[("active", COLORS["surface_hover"])])
        style.map(
            "Treeview",
            background=[("selected", COLORS["select_bg"])],
            foreground=[("selected", COLORS["select_fg"])],
        )
        style.configure(
            "Vertical.TScrollbar",
            background=COLORS["border"],
            troughcolor=COLORS["surface_alt"],
            bordercolor=COLORS["surface_alt"],
            arrowcolor=COLORS["muted"],
            relief="flat",
        )
        style.configure(
            "Horizontal.TScrollbar",
            background=COLORS["border"],
            troughcolor=COLORS["surface_alt"],
            bordercolor=COLORS["surface_alt"],
            arrowcolor=COLORS["muted"],
            relief="flat",
        )

    def _touch_activity(self, _event=None):
        self.last_activity = time.monotonic()

    def _on_close(self):
        try:
            if self.logged and self.store.get("start"):
                self.store.maybe_auto_backup(force=False, actor=self.user)
        except Exception:
            logger.exception("Error during exit auto-backup")
        self.destroy()

    def can(self, perm):
        return bool(self.user and has_permission(self.user["role"], perm))

    def require(self, perm):
        if not self.can(perm):
            raise Problem("אין לך הרשאה לביצוע פעולה זו")

    def tick(self):
        try:
            if self.logged:
                self.ledger.generate()
                try:
                    lock_mins = int(self.store.get("auto_lock_minutes", "15"))
                except ValueError:
                    lock_mins = 15
                if lock_mins > 0 and (time.monotonic() - self.last_activity) >= lock_mins * 60:
                    self.lock(notice="המערכת ננעלה אוטומטית עקב חוסר פעילות")
        except (Problem, sqlite3.Error) as exc:
            self.error(exc)
        finally:
            self.after(60000, self.tick)

    def error(self, exc, parent=None):
        if isinstance(exc, Problem):
            msg = str(exc)
        elif isinstance(exc, sqlite3.IntegrityError):
            logger.warning("Integrity error: %s", exc)
            msg = "הפרטים כפולים או אינם עומדים בכללי הנתונים"
        else:
            logger.exception("Unhandled UI error: %s", exc)
            msg = "לא ניתן להשלים את הפעולה. יש לבדוק את הערכים או את קובץ הנתונים (פרטים נשמרו ביומן השגיאות)"
        messagebox.showerror("הפעולה נכשלה", msg, parent=parent or self)

    def report_callback_exception(self, typ, value, tb):
        logger.error("Tk callback exception", exc_info=(typ, value, tb))
        self.error(value)

    def reset(self):
        for child in self.winfo_children():
            child.destroy()

    # ------------------------------------------------------------------
    # Executive Login Screen & Setup Wizard
    # ------------------------------------------------------------------

    def lock(self, notice=""):
        self.logged = False
        self.user = None
        self.reset()

        # Sleek midnight top hero backdrop
        hero_bg = tk.Frame(self, bg=COLORS["nav"], height=260)
        hero_bg.pack(fill="x", side="top")
        hero_bg.pack_propagate(False)
        tk.Frame(hero_bg, bg=COLORS["action"], height=4).pack(fill="x", side="bottom")

        # Elevated centered login card overlapping the hero band
        card = CardFrame(self, padx=40, pady=34)
        card.place(relx=0.5, rely=0.47, anchor="center", width=440)
        outer = card.inner

        BrandLogo(outer, size=58, bg=COLORS["surface"]).pack(pady=(0, 12))
        tk.Label(outer, text="ניהול ועד הבית", bg=COLORS["surface"], fg=COLORS["text"], font=(FONT, 22, "bold")).pack()
        tk.Label(
            outer,
            text=self.store.get("complex", "שחראי 14 · 16 · 18"),
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=(FONT, 11),
        ).pack(pady=(2, 20))

        if notice:
            tk.Label(
                outer, text=notice, bg=COLORS["warning_bg"], fg=COLORS["warning_dark"],
                highlightbackground=COLORS["warning_border"], highlightthickness=1,
                padx=12, pady=7, font=(FONT, 9, "bold"),
            ).pack(fill="x", pady=(0, 14))

        if self.store.get("start"):
            users = self.store.list_users(active_only=True)
            user_map = {f"{u['display_name']} ({u['username']})": u["username"] for u in users}
            user_var = tk.StringVar(value=next(iter(user_map), "admin"))
            if len(users) > 1:
                tk.Label(outer, text="משתמש", bg=COLORS["surface"], fg=COLORS["text_secondary"], font=(FONT, 9, "bold"), anchor="e").pack(fill="x")
                ttk.Combobox(outer, textvariable=user_var, values=tuple(user_map.keys()), state="readonly", justify="right").pack(fill="x", pady=(3, 10))

            tk.Label(outer, text="סיסמה", bg=COLORS["surface"], fg=COLORS["text_secondary"], font=(FONT, 9, "bold"), anchor="e").pack(fill="x")
            pwd_var = tk.StringVar()
            field = ttk.Entry(outer, textvariable=pwd_var, show="●", justify="right")
            field.pack(fill="x", pady=(3, 18))

            def login():
                uname = user_map.get(user_var.get(), "admin")
                authenticated = self.store.authenticate_user(uname, pwd_var.get())
                if not authenticated:
                    pwd_var.set("")
                    raise Problem("שם המשתמש או הסיסמה אינם נכונים")
                self.user = authenticated
                self._touch_activity()
                self.enter()

            ActionButton(outer, "כניסה למערכת", login, variant="primary", pady=9, font_size=10).pack(fill="x")
            field.bind("<Return>", lambda _: login())
            field.focus_set()
        else:
            ActionButton(outer, "הגדרת מערכת חדשה (שחראי 14, 16, 18)", self.setup, variant="primary", pady=10, font_size=10).pack(fill="x")
            ActionButton(outer, "שחזור מגיבוי ממחשב קודם", self.restore, variant="soft", pady=8, font_size=9).pack(fill="x", pady=(10, 0))

        tk.Frame(outer, bg=COLORS["border"], height=1).pack(fill="x", pady=(22, 12))
        tk.Label(
            outer,
            text=f"גרסה {__version__}  •  עבודה מקומית ומאובטחת (OFFLINE)",
            bg=COLORS["surface"], fg=COLORS["muted"], font=(FONT, 8),
        ).pack()

    def setup(self):
        defaults = str(self.store.path.parent / "backups")
        fields = [
            ("name", "שם ועד הבית", "ועד הבית", None),
            ("complex", "שם המתחם", "שחראי 14, 16, 18", None),
            ("start", "תאריך תחילת ניהול", "01/01/2026", None),
            ("bank", "יתרה נוכחית בבנק (₪)", "0", None),
            ("cash", "יתרה נוכחית במזומן (₪)", "0", None),
            ("password", "סיסמת מנהל ראשי (8+ תווים)", "", "password"),
            ("backup", "תיקיית גיבוי", defaults, "folder"),
            ("rate", "תעריף חודשי רגיל (₪)", "100", None),
            ("split", "מספר/תיאור הדירה המחולקת בבניין 16", "מחולקת", None),
            ("load_excel", "טעינת 21 הדירות ונתוני האקסל (2025–2027)", "כן (מומלץ)", ("כן (מומלץ)", "דירות בלבד ללא היסטוריית תשלומים")),
        ]

        def save(v):
            bank_ag = money(v["bank"])
            cash_ag = money(v["cash"])
            self.store.setup(
                v["name"], v["complex"], iso(v["start"]), bank_ag + cash_ag,
                v["password"], v["backup"], money(v["rate"]), v["split"],
                initial_bank=bank_ag, initial_cash=cash_ag, seed_shahrai_names=True,
            )
            users = self.store.list_users(active_only=True)
            self.user = dict(users[0]) if users else {"id": None, "username": "admin", "display_name": "מנהל ראשי", "role": "admin"}
            if v["load_excel"].startswith("כן"):
                self.ledger.load_shahrai_excel_data(target_bank=bank_ag, target_cash=cash_ag, actor=self.user)
            else:
                self.store.save(excel_seeded="skip")
            self.after_idle(self.enter)

        Dialog(self, "הגדרת מערכת · שחראי 14, 16, 18", fields, save)

    # ------------------------------------------------------------------
    # Midnight Sidebar + White Topbar Shell
    # ------------------------------------------------------------------

    def enter(self):
        if self.store.get("excel_seeded") == "":
            bals = self.ledger.balances()
            self.ledger.load_shahrai_excel_data(target_bank=bals["bank"], target_cash=bals["cash"], actor=self.user)
        self.ledger.generate()
        self.logged = True
        self._touch_activity()
        self.reset()

        # Midnight Slate Sidebar (RTL right side)
        sidebar = tk.Frame(self, bg=COLORS["nav"], width=236)
        sidebar.pack(side="right", fill="y")
        sidebar.pack_propagate(False)

        # Brand block with vector emblem
        brand = tk.Frame(sidebar, bg=COLORS["nav"], padx=16, pady=18)
        brand.pack(fill="x")
        BrandLogo(brand, size=38, bg=COLORS["nav"]).pack(side="right")
        brand_txt = tk.Frame(brand, bg=COLORS["nav"])
        brand_txt.pack(side="right", padx=(0, 10))
        tk.Label(brand_txt, text="ועד הבית", bg=COLORS["nav"], fg="#FFFFFF", font=(FONT, 15, "bold"), anchor="e").pack(fill="x")
        tk.Label(brand_txt, text=self.store.get("complex"), bg=COLORS["nav"], fg=COLORS["nav_muted"], font=(FONT, 8), anchor="e").pack(fill="x")

        # Sleek user profile pill card
        prof = tk.Frame(sidebar, bg=COLORS["nav_surface"], highlightbackground="#1E293B", highlightthickness=1, padx=10, pady=8)
        prof.pack(fill="x", padx=14, pady=(0, 10))
        initial_ch = (self.user["display_name"] or self.user["username"] or "A")[0]
        avatar = tk.Label(prof, text=initial_ch, bg=COLORS["action"], fg="#FFFFFF", font=(FONT, 10, "bold"), width=3, pady=3)
        avatar.pack(side="right")
        ptxt = tk.Frame(prof, bg=COLORS["nav_surface"])
        ptxt.pack(side="right", padx=(0, 9), fill="x", expand=True)
        tk.Label(ptxt, text=self.user["display_name"], bg=COLORS["nav_surface"], fg="#F8FAFC", font=(FONT, 9, "bold"), anchor="e").pack(fill="x")
        tk.Label(ptxt, text=ROLES.get(self.user["role"], ""), bg=COLORS["nav_surface"], fg=COLORS["nav_indicator"], font=(FONT, 8), anchor="e").pack(fill="x")

        self.sidebar = sidebar
        self.nav = {}

        for grp_title, items in self.NAV_GROUPS:
            tk.Label(
                sidebar, text=grp_title, bg=COLORS["nav"], fg=COLORS["nav_section"],
                font=(FONT, 8, "bold"), anchor="e", padx=18,
            ).pack(fill="x", pady=(12, 3))
            for idx, icon, name in items:
                row = tk.Frame(sidebar, bg=COLORS["nav"])
                row.pack(fill="x", padx=10, pady=1)
                ind = tk.Frame(row, bg=COLORS["nav"], width=4)
                ind.pack(side="right", fill="y")
                btn = tk.Button(
                    row, text=f"{name}   {icon}", anchor="e", padx=12, pady=9, relief="flat", borderwidth=0,
                    bg=COLORS["nav"], fg="#E2E8F0", activebackground=COLORS["nav_hover"], activeforeground="#FFFFFF",
                    font=(FONT, 10), cursor="hand2", command=lambda i=idx: self.show(i),
                )
                btn.pack(side="right", fill="x", expand=True)
                btn.bind("<Enter>", lambda _e, i=idx, b=btn: b.configure(bg=COLORS["nav_hover"]) if self.page != i else None)
                btn.bind("<Leave>", lambda _e, i=idx, b=btn: b.configure(bg=COLORS["nav"]) if self.page != i else None)
                self.nav[idx] = (btn, ind)

        # Bottom lock button
        tk.Frame(sidebar, bg="#1E293B", height=1).pack(side="bottom", fill="x", padx=14, pady=(0, 8))
        lock_btn = tk.Button(
            sidebar, text="נעילת המערכת   🔒", anchor="e", padx=16, pady=9, relief="flat",
            bg=COLORS["nav"], fg="#FDA4AF", activebackground=COLORS["nav_hover"], activeforeground="#FFE4E6",
            font=(FONT, 9, "bold"), command=self.lock, cursor="hand2",
        )
        lock_btn.pack(side="bottom", fill="x", padx=10, pady=(0, 8))

        # Content shell (Topbar + Main Canvas)
        content = tk.Frame(self, bg=COLORS["background"])
        content.pack(side="right", fill="both", expand=True)

        self.topbar = tk.Frame(content, bg=COLORS["topbar"], height=64)
        self.topbar.pack(fill="x", side="top")
        self.topbar.pack_propagate(False)
        tk.Frame(content, bg=COLORS["border"], height=1).pack(fill="x", side="top")

        self.main = tk.Frame(content, bg=COLORS["background"], padx=22, pady=14)
        self.main.pack(fill="both", expand=True)

        # Clean status footer bar
        status_bar = tk.Frame(content, bg=COLORS["surface"], highlightbackground=COLORS["border"], highlightthickness=1, padx=22, pady=4)
        status_bar.pack(fill="x", side="bottom")
        tk.Label(status_bar, textvariable=self.status, bg=COLORS["surface"], fg=COLORS["success"], font=(FONT, 9, "bold"), anchor="e").pack(side="right")
        tk.Label(status_bar, text=f"שחראי 14 · 16 · 18   |   {date_text(today())}", bg=COLORS["surface"], fg=COLORS["muted"], font=(FONT, 8)).pack(side="left")

        self.show(0)

    def _render_topbar(self, index):
        for child in self.topbar.winfo_children():
            child.destroy()

        right = tk.Frame(self.topbar, bg=COLORS["topbar"], padx=22)
        right.pack(side="right", fill="y")
        tk.Label(right, text=self.PAGES[index], bg=COLORS["topbar"], fg=COLORS["text"], font=(FONT, 16, "bold"), anchor="e").pack(anchor="e", pady=(10, 0))
        tk.Label(right, text=self.PAGE_SUBTITLES[index], bg=COLORS["topbar"], fg=COLORS["muted"], font=(FONT, 8), anchor="e").pack(anchor="e")

        # Clickable live balance pill badges on the left!
        bals = self.ledger.balances()
        left = tk.Frame(self.topbar, bg=COLORS["topbar"], padx=18)
        left.pack(side="left", fill="y")
        pills_row = tk.Frame(left, bg=COLORS["topbar"])
        pills_row.pack(expand=True)

        PillBadge(
            pills_row, "סה״כ בקופה", amount(bals["total"]),
            bg=COLORS["nav"], fg="#FFFFFF", border=COLORS["nav"],
            command=lambda: self.show(4),
        ).pack(side="left", padx=4)
        PillBadge(
            pills_row, "🏦 בנק", amount(bals["bank"]),
            bg=COLORS["action_soft"], fg=COLORS["action"], border=COLORS["action_border"],
            command=lambda: self.show(4, "bank"),
        ).pack(side="left", padx=4)
        PillBadge(
            pills_row, "💵 מזומן", amount(bals["cash"]),
            bg=COLORS["success_bg"], fg=COLORS["success_dark"], border=COLORS["success_border"],
            command=lambda: self.show(4, "cash"),
        ).pack(side="left", padx=4)

    def show(self, index, mode=None):
        self.page, self.mode = index, mode
        for i, (btn, ind) in self.nav.items():
            if i == index:
                btn.configure(bg=COLORS["nav_surface"], fg="#FFFFFF", font=(FONT, 10, "bold"))
                ind.configure(bg=COLORS["nav_indicator"])
            else:
                btn.configure(bg=COLORS["nav"], fg="#CBD5E1", font=(FONT, 10, "normal"))
                ind.configure(bg=COLORS["nav"])

        self._render_topbar(index)
        for child in self.main.winfo_children():
            child.destroy()

        pages = (
            self.dashboard,                      # 0
            lambda: render_annual_matrix(self),  # 1
            self.collection,                     # 2
            self.units,                          # 3
            self.movements,                      # 4
            self.suppliers,                      # 5
            self.reports,                        # 6
            self.settings,                       # 7
        )
        pages[index]()

    def refresh(self, message="הפעולה נשמרה"):
        self.status.set(message)
        self.show(self.page, self.mode)

    # ------------------------------------------------------------------
    # Shared Modern UI Primitives
    # ------------------------------------------------------------------

    def bar(self, parent=None, card=False):
        if card:
            c = CardFrame(parent or self.main, padx=12, pady=8)
            c.pack(fill="x", pady=(0, 8))
            return c.inner
        bar = tk.Frame(parent or self.main, bg=COLORS["background"])
        bar.pack(fill="x", pady=(2, 8))
        return bar

    def button(self, bar, text, command, primary=False, perm=None, variant=None):
        disabled = bool(perm and not self.can(perm))
        v = variant or ("primary" if primary else "secondary")
        btn = ActionButton(bar, text, command, variant=v, disabled=disabled)
        btn.pack(side="right", padx=(5, 0))
        return btn

    def input(self, bar, label, value="", options=None, width=14):
        bg = bar.cget("bg") if isinstance(bar, tk.Frame) else COLORS["background"]
        tk.Label(bar, text=label, bg=bg, fg=COLORS["text_secondary"], font=(FONT, 9, "bold")).pack(side="right", padx=(6, 6))
        var = tk.StringVar(value=value)
        if options:
            field = ttk.Combobox(bar, textvariable=var, values=options, state="readonly", justify="right", width=width)
        else:
            field = ttk.Entry(bar, textvariable=var, justify="right", width=width)
        field.pack(side="right")
        return var

    def table(self, headers, rows=(), height=12, parent=None, title=None):
        parent = parent or self.main
        card = CardFrame(parent, padx=0, pady=0)
        card.pack(fill="both", expand=True, pady=(0, 6))
        box = card.inner

        if title:
            th = tk.Frame(box, bg=COLORS["surface"], padx=14, pady=9)
            th.pack(fill="x")
            tk.Label(th, text=title, bg=COLORS["surface"], fg=COLORS["text"], font=(FONT, 10, "bold"), anchor="e").pack(side="right")
            tk.Frame(box, bg=COLORS["border"], height=1).pack(fill="x")

        body = tk.Frame(box, bg=COLORS["surface"])
        body.pack(fill="both", expand=True)

        tree = ttk.Treeview(body, columns=list(range(len(headers))), show="headings", height=height)
        scroll = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        horiz = ttk.Scrollbar(body, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=scroll.set, xscrollcommand=horiz.set)
        horiz.pack(side="bottom", fill="x")
        scroll.pack(side="left", fill="y")
        tree.pack(side="right", fill="both", expand=True)

        tree.tag_configure("alternate", background=COLORS["surface_alt"])
        tree.tag_configure("paid", background=COLORS["success_bg"], foreground=COLORS["success_dark"])
        tree.tag_configure("partial", background=COLORS["warning_bg"], foreground=COLORS["warning_dark"])
        tree.tag_configure("debt", background=COLORS["danger_bg"], foreground=COLORS["danger_dark"])
        tree.tag_configure("credit", background=COLORS["info_bg"], foreground=COLORS["info_dark"])
        tree.tag_configure("reversed", foreground=COLORS["reversed_fg"])

        for index, label in enumerate(reversed(headers)):
            tree.heading(index, text=label, anchor="e", command=lambda col=index: self.sort_table(tree, col))
            tree.column(index, width=max(90, len(label) * 9 + 18), minwidth=60, anchor="e")
        self.fill(tree, rows)
        return tree

    def sort_table(self, tree, column):
        reverse = getattr(tree, "sort_state", None) == (column, False)
        rows = list(tree.get_children())
        if rows == ["empty"]:
            return
        for index, item in enumerate(sorted(rows, key=lambda iid: sort_key(tree.set(iid, column)), reverse=reverse)):
            tree.move(item, "", index)
        tree.sort_state = (column, reverse)

    def fill(self, tree, rows):
        self.fill_tagged(tree, [(k, v, "") for k, v in rows])

    def fill_tagged(self, tree, rows):
        tree.delete(*tree.get_children())
        for i, (key, values, tag) in enumerate(rows):
            tags = (tag,) if tag else (("alternate",) if i % 2 else ())
            tree.insert("", "end", iid=str(key), values=list(reversed(values)), tags=tags)
        if not tree.get_children():
            cols = len(tree["columns"])
            empty_vals = [""] * max(0, cols - 1) + ["אין נתונים להצגה"]
            tree.insert("", "end", iid="empty", values=empty_vals)

    def selection(self, tree):
        selected = tree.selection()
        if not selected or selected[0] == "empty":
            raise Problem("יש לבחור שורה בטבלה")
        return int(selected[0])

    # ------------------------------------------------------------------
    # Export & Receipt Helpers
    # ------------------------------------------------------------------

    def export_xlsx_report(self, title, headers, rows, totals=None):
        path = filedialog.asksaveasfilename(
            parent=self, title="שמירת דוח Excel", initialfile=f"{title}-{today()}.xlsx",
            defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
        )
        if not path:
            return
        excel_rows = [[_cell_to_excel(v) for v in vals] for _, vals in rows]
        excel_totals = [_cell_to_excel(v) for v in totals] if totals else None
        write_xlsx(path, [{"title": title, "headers": headers, "rows": excel_rows, "totals": excel_totals}])
        self.status.set("קובץ ה-Excel נשמר בהצלחה")

    def export_pdf_report(self, title, headers, rows, subtitle="", kpis=None, totals=None, chart_svg=""):
        path = filedialog.asksaveasfilename(
            parent=self, title="שמירת דוח PDF", initialfile=f"{title}-{today()}.pdf",
            defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
        )
        if not path:
            return
        html_doc = build_report_html(self.store, title, headers, rows, subtitle=subtitle, kpis=kpis, totals=totals, chart_svg=chart_svg)
        export_pdf(html_doc, path)
        self.status.set("קובץ ה-PDF נשמר בהצלחה")
        if messagebox.askyesno("PDF נשמר", "הדוח נשמר בהצלחה כ-PDF. לפתוח אותו כעת?", parent=self):
            os.startfile(path)

    def print_report(self, title, headers, rows, subtitle="", kpis=None, totals=None, chart_svg=""):
        html_doc = build_report_html(self.store, title, headers, rows, subtitle=subtitle, kpis=kpis, totals=totals, chart_svg=chart_svg)
        open_printable_html(self.store.path.parent, html_doc, slug="report")

    def export(self, headers, rows):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        export_csv(path, headers, rows)
        self.status.set("קובץ ה-CSV נשמר")

    def show_receipt(self, entry_id, as_pdf=False):
        data = self.ledger.receipt_data(entry_id)
        html_doc = build_receipt_html(data)
        if as_pdf:
            path = filedialog.asksaveasfilename(
                parent=self, title="שמירת אישור תשלום (PDF)", initialfile=f"receipt-{data['receipt_no']}.pdf",
                defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            )
            if not path:
                return
            export_pdf(html_doc, path)
            self.status.set(f"אישור תשלום {data['receipt_no']} נשמר כ-PDF")
            os.startfile(path)
        else:
            open_printable_html(self.store.path.parent, html_doc, slug=f"receipt-{data['receipt_no']}")
            self.status.set(f"נפתח אישור תשלום {data['receipt_no']} להדפסה")

    # ------------------------------------------------------------------
    # Transaction Forms
    # ------------------------------------------------------------------

    def payment(self, unit_id=None):
        self.require("record_payment")
        units = self.ledger.units()
        choices = {f"בניין {u['building']} · {u['tenant'] or u['owner'] or unit_name(u)} (#{u['id']})": u["id"] for u in units}
        selected = next((label for label, id_ in choices.items() if id_ == unit_id), next(iter(choices), ""))
        due = lambda label: max(0, self.ledger.account(choices[label])["unpaid_total"])
        fields = [
            ("unit", "יחידת מגורים", selected, list(choices)),
            ("party", "שם המשלם", "", None),
            ("amount", "סכום בשקלים", number(due(selected)), None),
            ("day", "תאריך", date_text(today()), None),
            ("method", "אמצעי תשלום", METHODS[1], METHODS),
            ("account", "קופה (בנק / מזומן)", "בנק", ("בנק", "מזומן")),
            ("reference", "אסמכתא", "", None),
            ("notes", "הערות", "", None),
            ("attachment", "צירוף אסמכתא / קבלה (אופציונלי)", "", "file"),
        ]
        token = uuid4().hex

        def footer(dialog, bar):
            result = tk.StringVar()
            tk.Label(bar, textvariable=result, bg=COLORS["surface_alt"], fg=COLORS["info_dark"], font=(FONT, 9, "bold"), anchor="e", justify="right").pack(side="bottom", fill="x", pady=(0, 8))

            def preview(*_):
                v = dialog.get()
                bal = self.ledger.account(choices[v["unit"]])["balance"]
                try:
                    pay_val = money(v["amount"])
                except Problem:
                    result.set("")
                    return
                after = bal - pay_val
                result.set(
                    f"חוב לפני: {amount(max(bal, 0))}   •   תשלום: {amount(pay_val)}\n"
                    f"חוב אחרי: {amount(max(after, 0))}   •   זכות אחרי: {amount(max(-after, 0))}"
                )

            def update_unit(*_):
                dialog.values["amount"].set(number(due(dialog.values["unit"].get())))

            def sync_acct(*_):
                dialog.values["account"].set(ACCOUNTS[default_account(dialog.values["method"].get())])

            dialog.values["unit"].trace_add("write", update_unit)
            dialog.values["method"].trace_add("write", sync_acct)
            dialog.values["amount"].trace_add("write", preview)
            preview()

        def post(v):
            unit = choices[v["unit"]]
            rev_acct = {"בנק": "bank", "מזומן": "cash"}
            args = ("payment", money(v["amount"]), iso(v["day"]), v["method"], token)
            kw = dict(unit=unit, party=v["party"], reference=v["reference"], notes=v["notes"], account=rev_acct[v["account"]], actor=self.user)
            try:
                entry = self.ledger.post(*args, **kw)
            except Problem as exc:
                if str(exc) != "נמצא תשלום דומה":
                    raise
                if not messagebox.askyesno("תשלום דומה", "נמצא תשלום דומה. האם זהו תשלום נוסף?", parent=self):
                    return False
                entry = self.ledger.post(*args, **kw, allow_duplicate=True)
            if v["attachment"].strip():
                self.store.add_attachment(entry, v["attachment"].strip(), actor=self.user)
            self.refresh(f"תשלום #{entry} נשמר ({v['account']}) · יתרה {amount(self.ledger.account(unit)['balance'])}")
            if messagebox.askyesno("אישור תשלום", f"תשלום #{entry} נרשם בהצלחה.\nלהפיק אישור תשלום (קבלה) כעת?", parent=self):
                self.show_receipt(entry)

        Dialog(self, "רישום תשלום דייר", fields, post, footer)

    def movement_form(self, kind, prefill=None):
        self.require("record_expense")
        prefill = prefill or {}
        label = LABELS[kind]
        categories = {r["name"]: r["id"] for r in self.store.rows("SELECT * FROM categories WHERE kind=? AND active=1 ORDER BY name", kind)}
        suppliers = {r["name"]: r["id"] for r in self.store.rows("SELECT id,name FROM suppliers WHERE active=1 ORDER BY name")} if kind == "expense" else {}
        fields = [
            ("day", "תאריך", prefill.get("day", date_text(today())), None),
            ("amount", "סכום בשקלים", prefill.get("amount", ""), None),
            ("party", "ספק או מקור", prefill.get("party", ""), None),
            ("category", "קטגוריה", prefill.get("category", next(iter(categories), "")), list(categories)),
            ("description", "תיאור מפורט", prefill.get("description", ""), None),
            ("method", "אמצעי תשלום", METHODS[1], METHODS),
            ("account", "קופה (בנק / מזומן)", "בנק", ("בנק", "מזומן")),
            ("reference", "מספר חשבונית או אסמכתא", "", None),
            ("notes", "הערות", "", None),
            ("attachment", "צירוף חשבונית / קבלה (אופציונלי)", "", "file"),
        ]
        if suppliers:
            fields.insert(3, ("supplier", "כרטיס ספק", prefill.get("supplier", "ללא שיוך"), ("ללא שיוך", *suppliers)))
        token = uuid4().hex

        def footer(dialog, _bar):
            dialog.values["method"].trace_add(
                "write", lambda *_: dialog.values["account"].set(ACCOUNTS[default_account(dialog.values["method"].get())])
            )

        def save(v):
            value = money(v["amount"])
            rev_acct = {"בנק": "bank", "מזומן": "cash"}
            acct_key = rev_acct[v["account"]]
            bals = self.ledger.balances()
            if kind == "expense" and bals[acct_key] - value < 0 and not messagebox.askyesno(
                "יתרה שלילית", f"ההוצאה תיצור יתרה שלילית בקופת ה{v['account']}. לשמור בכל זאת?", parent=self
            ):
                return False
            sup_name = v.get("supplier", "ללא שיוך")
            party_val = v["party"].strip() or (sup_name if sup_name != "ללא שיוך" else "")
            entry = self.ledger.post(
                kind, value, iso(v["day"]), v["method"], token,
                category=categories.get(v["category"]),
                supplier=suppliers.get(sup_name),
                party=party_val,
                description=v["description"],
                reference=v["reference"],
                notes=v["notes"],
                account=acct_key,
                actor=self.user,
            )
            if v["attachment"].strip():
                self.store.add_attachment(entry, v["attachment"].strip(), actor=self.user)
            if prefill.get("recurring"):
                self.ledger.match_recurring(prefill["recurring"], prefill["period"], entry, actor=self.user)
            self.refresh(f"הפעולה נשמרה ({v['account']}) · #{entry}")

        Dialog(self, label, fields, save, footer)

    def transfer_dialog(self):
        self.require("record_expense")
        bals = self.ledger.balances()
        directions = ("הפקדת מזומן לבנק (מזומן ⟵ בנק)", "משיכת מזומן מהבנק (בנק ⟵ מזומן)")
        fields = [
            ("direction", "סוג העברה", directions[0], directions),
            ("amount", "סכום בשקלים", "", None),
            ("day", "תאריך", date_text(today()), None),
            ("reference", "אסמכתא", "", None),
            ("notes", "הערות", "", None),
        ]

        def save(v):
            from_a, to_a = ("cash", "bank") if v["direction"] == directions[0] else ("bank", "cash")
            self.ledger.transfer_cash(from_a, to_a, money(v["amount"]), iso(v["day"]), v["reference"], v["notes"], actor=self.user)
            self.refresh("ההעברה הפנימית בין הבנק למזומן נשמרה")

        Dialog(
            self, "העברה פנימית בין בנק למזומן", fields, save,
            footer=lambda _, bar: tk.Label(
                bar,
                text=f"יתרה נוכחית: בנק {amount(bals['bank'])}   •   מזומן {amount(bals['cash'])}   (סה״כ הקופה אינו משתנה)",
                bg=COLORS["surface_alt"], fg=COLORS["info_dark"], font=(FONT, 8, "bold"), anchor="e",
            ).pack(side="bottom", fill="x", pady=(0, 8)),
        )

    def reversal(self, entry):
        self.require("reverse")

        def save(v):
            if not messagebox.askyesno("ביטול פעולה", f"ליצור תנועה הפוכה (ביטול) לפעולה #{entry}?", parent=self):
                return False
            self.ledger.reverse(entry, v["reason"], iso(v["day"]), actor=self.user)
            self.refresh("הפעולה בוטלה בתנועה הפוכה")

        Dialog(self, "ביטול פעולה", [("reason", "סיבת הביטול", "", None), ("day", "תאריך חשבונאי", date_text(today()), None)], save)

    # ------------------------------------------------------------------
    # Page 0: Executive Fintech Dashboard
    # ------------------------------------------------------------------

    def dashboard(self):
        period = today()[:7]
        report = self.ledger.report(period)
        details = self.ledger.details(period)
        bals = self.ledger.balances()
        expected = sum(c["due"] for _, c, *_ in details)
        received = sum(c["paid"] for _, c, *_ in details)
        debtors = self.debt_rows()

        paid_count = sum(1 for item in details if item[4] in ("שולם", "פטור"))
        partial_count = sum(1 for item in details if item[4] == "שולם חלקית")
        unpaid_count = sum(1 for item in details if item[4] == "לא שולם")
        rate_pct = f"{received / expected:.0%}" if expected else "—"

        # Row 1: Hero Cashbox Split (Featured Dark Total + Light Bank & Cash)
        hero = tk.Frame(self.main, bg=COLORS["background"])
        hero.pack(fill="x", pady=(0, 8))
        for col in range(3):
            hero.columnconfigure(col, weight=1, uniform="hero")

        MetricCard(
            hero, "סך הכול בקופה המשותפת", amount(bals["total"]),
            "בנק + מזומן  •  שחראי 14, 16 ו-18",
            accent=COLORS["nav_indicator"], command=lambda: self.show(4), icon="💼", dark=True,
        ).grid(row=0, column=2, sticky="nsew", padx=4)
        MetricCard(
            hero, "יתרה בחשבון הבנק", amount(bals["bank"]),
            "העברות בנקאיות, המחאות והפקדות",
            accent=COLORS["action"], command=lambda: self.show(4, "bank"), icon="🏦",
        ).grid(row=0, column=1, sticky="nsew", padx=4)
        MetricCard(
            hero, "יתרה במזומן בקופה", amount(bals["cash"]),
            "מזומן ביד נציג ועד הבית",
            accent=COLORS["success"], command=lambda: self.show(4, "cash"), icon="💵",
        ).grid(row=0, column=0, sticky="nsew", padx=4)

        # Row 2: Operational KPIs (4 clean cards)
        ops = tk.Frame(self.main, bg=COLORS["background"])
        ops.pack(fill="x", pady=(0, 10))
        for col in range(4):
            ops.columnconfigure(col, weight=1, uniform="ops")
        ops_cards = [
            ("גבייה החודש", f"{amount(received)} ({rate_pct})", f"מתוך {amount(expected)} · נותר {amount(expected - received)}", COLORS["info"], "📈", lambda: self.show(1)),
            ("יחידות ששילמו", f"{paid_count} / {len(details)}", f"חלקי: {partial_count} · טרם שילמו: {unpaid_count}", COLORS["success"], "✓", lambda: self.show(1)),
            ("חובות פתוחים", amount(sum(a["unpaid_total"] for _, a in debtors)), f"{len(debtors)} יחידות בפיגור", COLORS["danger"] if debtors else COLORS["success"], "!", lambda: self.show(2, "debt")),
            ("תזרים החודש", amount(report["payment"] + report["income"] + report["expense"]), f"הכנסות {amount(report['payment'] + report['income'])} · הוצאות {amount(-report['expense'])}", COLORS["warning"], "⇄", lambda: self.show(4)),
        ]
        for idx, (title, val, sub, accent, icon, cmd) in enumerate(ops_cards):
            MetricCard(ops, title, val, sub, accent, cmd, icon=icon).grid(row=0, column=3 - idx, sticky="nsew", padx=4)

        # Quick Action Strip inside crisp white card
        act_card = CardFrame(self.main, padx=12, pady=8)
        act_card.pack(fill="x", pady=(0, 10))
        bar = act_card.inner
        self.button(bar, "+ רישום תשלום", self.payment, primary=True, perm="record_payment")
        self.button(bar, "📅 לוח גבייה שנתי", lambda: self.show(1), variant="soft")
        self.button(bar, "+ רישום הוצאה", lambda: self.movement_form("expense"), variant="soft", perm="record_expense")
        self.button(bar, "⇄ העברה בנק ↔ מזומן", self.transfer_dialog, perm="record_expense")
        self.button(bar, "📥 ייבוא תנועות בנק", lambda: self.show(2, "bank"), perm="bank_import")

        due = self.ledger.recurring_due(today())
        if due:
            ActionButton(bar, f"⚠ {len(due)} הוצאות קבועות ממתינות", lambda: self.show(4, "recurring"), variant="danger").pack(side="left")

        # Interactive 12-Month Chart inside crisp white CardFrame
        chart_card = CardFrame(self.main, padx=10, pady=8)
        chart_card.pack(fill="x", pady=(0, 10))
        IncomeExpenseChart(chart_card.inner, self.ledger.monthly_series(12), height=175).pack(fill="x")

        # Bottom split: Recent Movements card (right) + Top Debtors card (left)
        bottom = tk.Frame(self.main, bg=COLORS["background"])
        bottom.pack(fill="both", expand=True)
        bottom.columnconfigure(0, weight=2)
        bottom.columnconfigure(1, weight=3)
        bottom.rowconfigure(0, weight=1)

        right_box = tk.Frame(bottom, bg=COLORS["background"])
        right_box.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.table(
            ("תאריך", "קופה", "פעולה", "תיאור", "סכום"),
            [
                (r["id"], (date_text(r["day"]), ACCOUNTS.get(r.get("account", "bank"), "בנק"), LABELS[r["kind"]], r["description"] or r["party"], amount(r["cash"])))
                for r in reversed(self.ledger.cash()[1][-6:])
            ],
            height=5,
            parent=right_box,
            title="תנועות אחרונות בקופה",
        )

        left_box = tk.Frame(bottom, bg=COLORS["background"])
        left_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        debt_tree = self.table(
            ("בניין", "דייר", "חוב"),
            [(u["id"], (f"בניין {u['building']}", u["tenant"] or u["owner"] or unit_name(u), amount(a["unpaid_total"]))) for u, a in debtors[:6]],
            height=5,
            parent=left_box,
            title="דיירים בפיגור (לחיצה כפולה לכרטסת)",
        )
        debt_tree.bind("<Double-1>", lambda e: self.unit_detail(int(debt_tree.identify_row(e.y))) if debt_tree.identify_row(e.y).isdigit() else None)

    # ------------------------------------------------------------------
    # Page 2: Monthly Collection, Open Debts & Bank Import
    # ------------------------------------------------------------------

    def debt_rows(self):
        data = [(u, self.ledger.account(u["id"])) for u in self.ledger.units()]
        return sorted(((u, a) for u, a in data if a["unpaid_total"] > 0), key=lambda item: -item[1]["unpaid_total"])

    def debtor_table(self, parent=None):
        parent = parent or self.main
        bar = self.bar(parent, card=True)
        sort = self.input(bar, "מיון", "סכום", ("סכום", "שם", "בניין", "דירה"), 10)
        self.button(bar, "+ רישום תשלום", lambda: self.payment(self.selection(tree)), primary=True, perm="record_payment")
        self.button(bar, "כרטסת דייר", lambda: self.unit_detail(self.selection(tree)), variant="soft")
        self.button(bar, "ייצוא Excel", lambda: self.export_xlsx_report("דוח חובות פתוחים", headers, current_rows))
        self.button(bar, "ייצוא PDF", lambda: self.export_pdf_report("דוח חובות פתוחים", headers, current_rows))

        debt_sum = sum(a["unpaid_total"] for _, a in self.debt_rows())
        tk.Label(bar, text=f"סך חובות: {amount(debt_sum)}", bg=COLORS["surface"], fg=COLORS["danger"], font=(FONT, 10, "bold")).pack(side="left")

        headers = ("בניין", "דייר / יחידה", "טלפון", "חוב כולל", "חוב החודש", "חוב קודם", "וותק בימים")
        tree = self.table(headers, parent=parent)
        current_rows = []

        def load(*_):
            nonlocal current_rows
            data = self.debt_rows()
            keys = {
                "שם": lambda x: x[0]["tenant"] or x[0]["owner"],
                "בניין": lambda x: (x[0]["building"], x[0]["slot"]),
                "דירה": lambda x: x[0]["apartment"],
            }
            if sort.get() in keys:
                data.sort(key=keys[sort.get()])
            rows = []
            for u, a in data:
                current = a["charges"].get(today()[:7], {}).get("left", 0)
                age = (date.today() - date.fromisoformat(a["oldest"])).days if a["oldest"] else 0
                rows.append((u["id"], (f"בניין {u['building']}", u["tenant"] or u["owner"] or unit_name(u), u["phone"], amount(a["unpaid_total"]), amount(current), amount(a["unpaid_total"] - current), age)))
            current_rows = rows
            self.fill_tagged(tree, [(k, v, "debt") for k, v in rows])

        sort.trace_add("write", load)
        tree.bind("<Double-1>", lambda e: self.unit_detail(int(tree.identify_row(e.y))) if tree.identify_row(e.y).isdigit() else None)
        load()

    def collection(self):
        if self.mode == "current":
            self.period = today()[:7]
        bar = self.bar(card=True)
        self.button(bar, "מעקב חודשי", lambda: self.show(2), variant="primary" if self.mode in (None, "current") else "secondary")
        self.button(bar, "חובות פתוחים", lambda: self.show(2, "debt"), variant="primary" if self.mode == "debt" else "secondary")
        self.button(bar, "📥 ייבוא תנועות בנק", lambda: self.show(2, "bank"), variant="primary" if self.mode == "bank" else "soft", perm="bank_import")
        self.button(bar, "+ רישום תשלום ידני", self.payment, variant="success", perm="record_payment")

        if self.mode == "debt":
            self.debtor_table()
            return
        if self.mode == "bank":
            render_bank_import(self, self.main)
            return

        filters = self.bar(card=True)
        month = self.input(filters, "חודש", self.period[5:], tuple(f"{m:02d}" for m in range(1, 13)), 5)
        year = self.input(filters, "שנה", self.period[:4], width=7)
        self.button(filters, "הצגה", lambda: load(), variant="soft")
        self.button(filters, "תשלום ליחידה", lambda: self.payment(self.selection(tree)), primary=True, perm="record_payment")
        self.button(filters, "תיקון / פטור", lambda: adjust(), perm="adjust")
        self.button(filters, "Excel", lambda: self.export_xlsx_report(f"גבייה {self.period}", headers, current_rows))
        self.button(filters, "PDF", lambda: self.export_pdf_report(f"דוח גבייה חודשי · {self.period}", headers, current_rows))

        summary_var = tk.StringVar()
        tk.Label(self.main, textvariable=summary_var, bg=COLORS["background"], fg=COLORS["text_secondary"], anchor="e", font=(FONT, 10, "bold")).pack(fill="x", pady=(0, 6))

        headers = ("בניין", "דייר / דירה", "חיוב", "שולם", "נותר", "חוב קודם", "זכות", "מצב")
        tree = self.table(headers)
        current_rows = []

        def load():
            nonlocal current_rows
            try:
                y_val = int(year.get().strip())
                m_val = int(month.get().strip())
                self.period = date(y_val, m_val, 1).isoformat()[:7]
            except ValueError:
                raise Problem("יש להזין שנה וחודש תקינים")
            details = self.ledger.details(self.period)
            tag_map = {"שולם": "paid", "פטור": "paid", "שולם חלקית": "partial", "לא שולם": "debt"}
            tagged = []
            plain = []
            for u, c, older, credit, status in details:
                vals = (f"בניין {u['building']}", u["tenant"] or u["owner"] or unit_name(u), amount(c["due"]), amount(c["paid"]), amount(c["left"]), amount(older), amount(credit), status)
                plain.append((u["id"], vals))
                tagged.append((u["id"], vals, tag_map.get(status, "")))
            current_rows = plain
            self.fill_tagged(tree, tagged)
            exp = sum(c["due"] for _, c, *_ in details)
            rec = sum(c["paid"] for _, c, *_ in details)
            pct = f"{rec / exp:.0%}" if exp else "—"
            summary_var.set(f"צפי גבייה: {amount(exp)}   •   נגבה: {amount(rec)} ({pct})   •   נותר לגבות: {amount(exp - rec)}")

        def adjust():
            self.require("adjust")
            unit = self.selection(tree)
            charge = self.ledger.account(unit)["charges"][self.period]

            def save(v):
                self.ledger.adjust(unit, self.period, money(v["amount"]), v["reason"], actor=self.user)
                self.refresh("החיוב עודכן")

            Dialog(self, "תיקון חיוב או פטור", [("amount", "סכום חדש בשקלים (0 לפטור)", number(charge["due"]), None), ("reason", "סיבה", "", None)], save)

        tree.bind("<Double-1>", lambda e: self.unit_detail(int(tree.identify_row(e.y))) if tree.identify_row(e.y).isdigit() else None)
        load()

    # ------------------------------------------------------------------
    # Page 3: Units & Personal Unit Ledger (כרטסת אישית)
    # ------------------------------------------------------------------

    def units(self):
        if isinstance(self.mode, tuple) and self.mode[0] == "unit":
            self.unit_sheet(self.mode[1])
            return
        bar = self.bar(card=True)
        query = self.input(bar, "חיפוש", width=22)
        building = self.input(bar, "בניין", "הכול", ("הכול", "14", "16", "18"), 8)
        states = ("הכול", "חוב", "זכות", "מאוזן", "פעילה", "לא פעילה")
        state = self.input(bar, "מצב", "הכול", states, 10)

        actions = self.bar()
        self.button(actions, "פתיחת כרטסת אישית", lambda: self.unit_detail(self.selection(tree)), primary=True)
        self.button(actions, "+ רישום תשלום", lambda: self.payment(self.selection(tree)), variant="soft", perm="record_payment")
        self.button(actions, "+ הוספת יחידה", self.add_unit_dialog, perm="manage_units")
        self.button(actions, "ייצוא Excel", self.export_data)

        tree = self.table(("בניין", "דירה", "יחידה", "בעלים", "שוכר", "טלפון", "תעריף", "חוב / יתרה", "מצב"))

        def load(*_):
            result = []
            for u in self.ledger.units():
                acc = self.ledger.account(u["id"])
                balance = acc["balance"]
                flag = state.get()
                flags = (
                    "הכול",
                    "חוב" if acc["unpaid_total"] > 0 else "זכות" if balance < 0 else "מאוזן",
                    "פעילה" if u["active"] else "לא פעילה",
                )
                apartment = u["apartment"] if not u["apartment"].startswith("@") else ""
                searchable = " ".join((str(u["building"]), apartment, u["owner"], u["tenant"], u["phone"], u["email"], u["notes"])).casefold()
                if flag in flags and building.get() in ("הכול", str(u["building"])) and query.get().strip().casefold() in searchable:
                    tag = "debt" if acc["unpaid_total"] > 0 else ("credit" if balance < 0 else "paid")
                    result.append((
                        u["id"],
                        (f"בניין {u['building']}", apartment or "טרם זוהתה", u["subunit"], u["owner"], u["tenant"], u["phone"], amount(u["rate"] or 0), amount(balance), flags[2]),
                        tag,
                    ))
            self.fill_tagged(tree, result)

        for variable in (query, building, state):
            variable.trace_add("write", load)
        tree.bind("<Double-1>", lambda e: self.unit_detail(int(tree.identify_row(e.y))) if tree.identify_row(e.y).isdigit() else None)
        load()

    def add_unit_dialog(self):
        self.require("manage_units")
        fields = [
            ("building", "בניין", "14", ("14", "16", "18")),
            ("apartment", "מספר / שם דירה", "", None),
            ("subunit", "יחידת משנה (אופציונלי, לדוג׳ א/ב)", "", None),
            ("rate", "תעריף חודשי בשקלים", number(int(self.store.get("rate", "10000"))), None),
            ("owner", "שם בעלים", "", None),
            ("tenant", "שם שוכר", "", None),
            ("phone", "טלפון", "", None),
            ("email", "דואר אלקטרוני", "", None),
            ("notes", "הערות", "", None),
        ]

        def save(v):
            self.ledger.add_unit(
                v["building"], v["apartment"], v["subunit"], money(v["rate"]),
                owner=v["owner"], tenant=v["tenant"], phone=v["phone"], email=v["email"],
                notes=v["notes"], start=today(), actor=self.user,
            )
            self.refresh("יחידת המגורים נוספה בהצלחה")

        Dialog(self, "הוספת יחידת מגורים", fields, save)

    def unit_detail(self, unit):
        self.show(3, ("unit", unit))

    def unit_sheet(self, unit):
        row = next(u for u in self.ledger.units() if u["id"] == unit)
        account = self.ledger.account(unit)
        bal = account["balance"]
        bal_color = COLORS["danger"] if account["unpaid_total"] > 0 else (COLORS["info"] if bal < 0 else COLORS["success"])

        # Sleek resident header card
        hcard = CardFrame(self.main, padx=16, pady=12)
        hcard.pack(fill="x", pady=(0, 8))
        hb = hcard.inner
        tk.Label(
            hb,
            text=f"בניין {row['building']}  •  {row['tenant'] or row['owner'] or unit_name(row)}",
            bg=COLORS["surface"], fg=COLORS["text"], font=(FONT, 15, "bold"), anchor="e",
        ).pack(side="right")
        tk.Label(
            hb,
            text=f"חוב פתוח: {amount(account['unpaid_total'])}   |   יתרה כוללת: {amount(bal)}",
            bg=COLORS["surface"], fg=bal_color, font=(FONT, 12, "bold"),
        ).pack(side="left")

        sub_row = tk.Frame(self.main, bg=COLORS["background"])
        sub_row.pack(fill="x", pady=(0, 6))
        tk.Label(
            sub_row,
            text=f"בעלים: {row['owner'] or '—'}   •   שוכר: {row['tenant'] or '—'}   •   טלפון: {row['phone'] or '—'}   •   דוא״ל: {row['email'] or '—'}   •   תעריף: {amount(row['rate'] or 0)}",
            bg=COLORS["background"], fg=COLORS["muted"], anchor="e", font=(FONT, 9),
        ).pack(fill="x")

        bar = self.bar()
        self.button(bar, "+ רישום תשלום", lambda: self.payment(unit), primary=True, perm="record_payment")
        self.button(bar, "אישור תשלום (קבלה)", lambda: self.show_receipt(self.selection(tree)), variant="soft")
        self.button(bar, "פרטי היחידה", lambda: self.edit_unit(row), perm="manage_units")
        self.button(bar, "החלפת דייר", lambda: self.replace_resident(row), perm="manage_units")
        self.button(bar, "שינוי תעריף", lambda: self.change_rate(unit, row["rate"] or 0), perm="manage_rates")
        if not any(entry["kind"] == "opening" for entry in self.ledger.history(unit)):
            def opening(v):
                self.ledger.opening(unit, money(v["amount"]), actor=self.user)
                self.refresh("יתרת הפתיחה נשמרה")
            self.button(bar, "יתרת פתיחה", lambda: Dialog(self, "יתרת פתיחה", [("amount", "חוב חיובי או זכות שלילית בשקלים", "0", None)], opening), perm="manage_units")
        self.button(bar, "← חזרה לרשימה", lambda: self.show(3))

        filters = self.bar(card=True)
        start = self.input(filters, "מתאריך", width=12)
        end = self.input(filters, "עד תאריך", width=12)
        self.button(filters, "סינון", lambda: load(), variant="soft")
        self.button(filters, "השנה", lambda: year())
        self.button(filters, "Excel", lambda: export_card("xlsx"))
        self.button(filters, "PDF", lambda: export_card("pdf"))
        self.button(filters, "הדפסה", lambda: export_card("print"))

        headers = ("תאריך", "תיאור", "קופה", "אמצעי תשלום", "חיוב", "זיכוי", "יתרה", "הערות")
        tree = self.table(headers, height=10)
        current_data = []

        def year():
            start.set(f"01/01/{date.today().year}")
            end.set(f"31/12/{date.today().year}")
            load()

        def load():
            nonlocal current_data
            lo, hi = self.bounds(start.get(), end.get())
            running = 0
            data = []
            for r in self.ledger.history(unit):
                running += r["debit"]
                if r["day"] < lo:
                    continue
                if not data and lo:
                    data.append((0, ("", "יתרה קודמת", "", "", "", "", amount(running - r["debit"]), "")))
                if r["day"] <= hi:
                    period_ref = r["period"] or r["for_period"]
                    desc = LABELS[r["kind"]] + (f" · {period_ref}" if period_ref else "")
                    if r["original"]:
                        desc += f" · ביטול #{r['original']}"
                    acct_lbl = ACCOUNTS.get(r["account"], "—") if r["cash"] != 0 else "—"
                    data.append((
                        r["id"],
                        (
                            date_text(r["day"]), desc, acct_lbl, r["method"] or "—",
                            amount(r["debit"]) if r["debit"] > 0 else "",
                            amount(-r["debit"]) if r["debit"] < 0 else "",
                            amount(running), r["notes"],
                        ),
                    ))
            if lo and not data:
                data.append((0, ("", "יתרה קודמת", "", "", "", "", amount(running), "")))
            current_data = data
            self.fill(tree, data)

        def export_card(fmt):
            title = f"כרטסת יחידה · {unit_name(row)}"
            sub = f"בעלים: {row['owner'] or '—'} · שוכר: {row['tenant'] or '—'}"
            kpis = [("חוב פתוח", amount(account["unpaid_total"])), ("יתרה כוללת", amount(bal)), ("תעריף חודשי", amount(row["rate"] or 0))]
            if fmt == "xlsx":
                self.export_xlsx_report(title, headers, current_data)
            elif fmt == "pdf":
                self.export_pdf_report(title, headers, current_data, subtitle=sub, kpis=kpis)
            else:
                self.print_report(title, headers, current_data, subtitle=sub, kpis=kpis)

        load()

        occupants = self.ledger.unit_occupants(unit)
        if occupants:
            self.table(
                ("תפקיד", "שם", "טלפון", "דוא״ל", "מתאריך", "עד תאריך", "הערות"),
                [
                    (o["id"], ("בעלים" if o["role"] == "owner" else "שוכר", o["name"], o["phone"], o["email"], date_text(o["arrived"]), date_text(o["departed"] or ""), o["notes"]))
                    for o in occupants
                ],
                height=3,
                title="היסטוריית דיירים ובעלים קודמים",
            )

    def replace_resident(self, row):
        self.require("manage_units")
        balance = self.ledger.account(row["id"])["balance"]
        fields = [
            ("role", "תפקיד", "שוכר", ("שוכר", "בעלים")),
            ("name", "שם חדש", "", None),
            ("phone", "טלפון חדש", "", None),
            ("email", "דואר אלקטרוני חדש", "", None),
            ("day", "תאריך שינוי", date_text(today()), None),
            ("notes", "הערות / אחריות לחובות קודמים", "", None),
        ]

        def save(values):
            role = "tenant" if values["role"] == "שוכר" else "owner"
            if not messagebox.askyesno("החלפת דייר", f"יתרת היחידה {amount(balance)}. הרישום הכספי יישאר בכרטיס היחידה. להמשיך?", parent=self):
                return False
            self.ledger.replace_resident(row["id"], role, values["name"], values["phone"], values["email"], iso(values["day"]), values["notes"], actor=self.user)
            self.refresh("הדייר הוחלף והיסטוריית הדיירים עודכנה")

        Dialog(self, "החלפת דייר", fields, save)

    def edit_unit(self, row):
        self.require("manage_units")
        keys = ("apartment", "owner", "tenant", "phone", "email", "notes")
        labels = ("מספר / שם דירה", "שם בעלים", "שם שוכר", "טלפון", "דואר אלקטרוני", "הערות")
        fields = [(k, label, "" if k == "apartment" and row[k].startswith("@") else row[k], None) for k, label in zip(keys, labels)]
        fields.append(("active", "מצב", "פעילה" if row["active"] else "לא פעילה", ("פעילה", "לא פעילה")))

        def save(v):
            if v["tenant"].strip() != row["tenant"] and self.ledger.account(row["id"])["balance"] > 0:
                if not messagebox.askyesno("החלפת דייר", "החוב נשאר בכרטיס היחידה. שינוי השם אינו משנה אחריות לתשלום. להמשיך?", parent=self):
                    return False
            self.ledger.unit_update(row["id"], [v[k] for k in keys], v["active"] == "פעילה", actor=self.user)
            self.refresh("פרטי היחידה עודכנו")

        Dialog(self, "פרטי היחידה", fields, save)

    def change_rate(self, unit, current):
        self.require("manage_rates")

        def save(v):
            self.ledger.rate(unit, iso(v["day"]), money(v["amount"]), actor=self.user)
            self.refresh("התעריף עודכן")

        Dialog(self, "שינוי תעריף", [("amount", "תעריף בשקלים", number(current), None), ("day", "מועד תחולה", date_text(today()), None)], save)

    # ------------------------------------------------------------------
    # Page 4: Cashbox (Bank vs Cash) + Movements + Transfers + Recurring
    # ------------------------------------------------------------------

    def bounds(self, start, end):
        lo = valid_day(iso(start)) if start.strip() else ""
        hi = valid_day(iso(end)) if end.strip() else "9999-12-31"
        if lo > hi:
            raise Problem("תאריך ההתחלה מאוחר מתאריך הסיום")
        return lo, hi

    def movements(self):
        if self.mode == "recurring":
            self.recurring_page()
            return
        if self.mode == "transfers":
            self.transfers_page()
            return

        bals = self.ledger.balances()
        strip = tk.Frame(self.main, bg=COLORS["background"])
        strip.pack(fill="x", pady=(0, 8))
        for col in range(3):
            strip.columnconfigure(col, weight=1, uniform="mstrip")
        MetricCard(strip, "סך הכול בקופה", amount(bals["total"]), "בנק + מזומן", COLORS["nav_indicator"], icon="💼", dark=True).grid(row=0, column=2, sticky="nsew", padx=4)
        MetricCard(strip, "יתרה בבנק", amount(bals["bank"]), "תנועות בנק והפקדות", COLORS["action"], icon="🏦").grid(row=0, column=1, sticky="nsew", padx=4)
        MetricCard(strip, "יתרה במזומן", amount(bals["cash"]), "מזומן ביד", COLORS["success"], icon="💵").grid(row=0, column=0, sticky="nsew", padx=4)

        bar = self.bar()
        self.button(bar, "+ רישום הוצאה", lambda: self.movement_form("expense"), primary=True, perm="record_expense")
        self.button(bar, "+ רישום הכנסה", lambda: self.movement_form("income"), variant="soft", perm="record_expense")
        self.button(bar, "⇄ בנק ↔ מזומן", self.transfer_dialog, variant="soft", perm="record_expense")
        self.button(bar, "העברות פנימיות", lambda: self.show(4, "transfers"))
        self.button(bar, "הוצאות קבועות", lambda: self.show(4, "recurring"))
        self.button(bar, "חשבוניות 📎", lambda: AttachmentsDialog(self, self.selection(tree), can_edit=self.can("attachments")))
        self.button(bar, "אישור תשלום", lambda: self.show_receipt(self.selection(tree)))
        self.button(bar, "ביטול פעולה", lambda: self.reversal(self.selection(tree)), variant="danger", perm="reverse")

        fcard = CardFrame(self.main, padx=12, pady=8)
        fcard.pack(fill="x", pady=(0, 8))
        filters = tk.Frame(fcard.inner, bg=COLORS["surface"])
        filters.pack(fill="x", pady=(0, 6))
        start = self.input(filters, "מתאריך", f"01/{today()[5:7]}/{today()[:4]}" if self.mode in ("income", "expense") else "", width=11)
        end = self.input(filters, "עד תאריך", date_text(today()) if self.mode in ("income", "expense") else "", width=11)
        acct_default = {"bank": "בנק", "cash": "מזומן"}.get(self.mode, "הכול")
        acct_filter = self.input(filters, "קופה", acct_default, ("הכול", "בנק", "מזומן"), 8)
        kinds = {"הכול": None, "הכנסות": ("payment", "income"), "הוצאות": ("expense",), "תשלומי דיירים": ("payment",)}
        kind = self.input(filters, "סוג", {"income": "הכנסות", "expense": "הוצאות"}.get(self.mode, "הכול"), tuple(kinds), 12)
        self.button(filters, "חודש נוכחי", lambda: preset(False))
        self.button(filters, "שנה נוכחית", lambda: preset(True))

        filters2 = tk.Frame(fcard.inner, bg=COLORS["surface"])
        filters2.pack(fill="x")
        method = self.input(filters2, "אמצעי", "הכול", ("הכול",) + METHODS, 12)
        names = sorted({r["name"] for r in self.store.rows("SELECT name FROM categories")})
        category = self.input(filters2, "קטגוריה", "הכול", ("הכול", *names), 12)
        query = self.input(filters2, "חיפוש", width=18)
        self.button(filters2, "סינון", lambda: load(), variant="soft")

        tree = self.table(("תאריך", "מספר", "קופה", "סוג", "תיאור", "קטגוריה", "יחידה או צד", "אמצעי", "הכנסה", "הוצאה", "יתרה", "קבצים"))
        tree.bind("<Double-1>", lambda e: self.movement_info(int(tree.identify_row(e.y))) if tree.identify_row(e.y).isdigit() else None)

        def preset(yr):
            start.set(f"01/{'01' if yr else today()[5:7]}/{today()[:4]}")
            end.set(date_text(today()))
            load()

        def load():
            lo, hi = self.bounds(start.get(), end.get())
            units = {u["id"]: f"בניין {u['building']} · {u['tenant'] or u['owner'] or unit_name(u)}" for u in self.ledger.units()}
            rev_acct = {"בנק": "bank", "מזומן": "cash"}
            want_acct = rev_acct.get(acct_filter.get())
            entries = []
            for r in reversed(self.ledger.cash()[1]):
                if not lo <= r["day"] <= hi or (kinds[kind.get()] and r["base_kind"] not in kinds[kind.get()]):
                    continue
                if want_acct and r.get("account", "bank") != want_acct:
                    continue
                if method.get() not in ("הכול", r["method"]) or category.get() not in ("הכול", r["category_name"]):
                    continue
                hay = " ".join(str(r[k] or "") for k in ("description", "party", "reference", "notes", "id", "category_name", "supplier_name")).casefold()
                if query.get().casefold().strip() not in hay + " " + units.get(r["unit"], "").casefold():
                    continue
                eid, vals = self.cash_row(r, units, include_attachments=True)
                tag = "reversed" if (r["reversed_by"] or r["kind"] == "reversal") else ""
                entries.append((eid, vals, tag))
            self.fill_tagged(tree, entries)

        acct_filter.trace_add("write", lambda *_: load())
        load()

    def transfers_page(self):
        bar = self.bar()
        self.button(bar, "⇄ העברה חדשה (בנק ↔ מזומן)", self.transfer_dialog, primary=True, perm="record_expense")
        self.button(bar, "← חזרה לתנועות", lambda: self.show(4))
        rows = [
            (t["id"], (date_text(t["day"]), ACCOUNTS[t["from_account"]], ACCOUNTS[t["to_account"]], amount(t["amount"]), t["reference"], t["notes"]))
            for t in self.ledger.list_transfers()
        ]
        self.table(("תאריך", "מקופה", "לקופה", "סכום", "אסמכתא", "הערות"), rows, height=14, title="היסטוריית העברות פנימיות בין בנק למזומן")

    def movement_info(self, entry):
        row = next(r for r in self.ledger.cash()[1] if r["id"] == entry)
        win = tk.Toplevel(self)
        win.title(f"פרטי תנועה #{entry}")
        win.geometry("540x480")
        win.transient(self)
        win.grab_set()
        win.configure(bg=COLORS["surface"])

        hdr = tk.Frame(win, bg=COLORS["nav"], padx=20, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"תנועה #{entry} · {LABELS[row['kind']]}", bg=COLORS["nav"], fg="#FFFFFF", font=(FONT, 13, "bold"), anchor="e").pack(fill="x")
        tk.Label(hdr, text=f"{date_text(row['day'])}  •  {ACCOUNTS.get(row.get('account', 'bank'), 'בנק')}  •  {amount(row['cash'])}", bg=COLORS["nav"], fg=COLORS["nav_indicator"], font=(FONT, 9), anchor="e").pack(fill="x", pady=(2, 0))

        details = [
            ("תאריך חשבונאי", date_text(row["day"])),
            ("קופה", ACCOUNTS.get(row.get("account", "bank"), "בנק")),
            ("סכום", amount(row["cash"])),
            ("אמצעי תשלום", row["method"] or "—"),
            ("קטגוריה", row["category_name"] or "—"),
            ("ספק / צד", row["supplier_name"] or row["party"] or "—"),
            ("תיאור", row["description"] or "—"),
            ("אסמכתא", row["reference"] or "—"),
            ("הערות", row["notes"] or "—"),
            ("קבצים מצורפים", str(row["attachment_count"])),
        ]
        if row.get("for_period"):
            details.append(("עבור חודש", row["for_period"]))
        if row["original"]:
            details.append(("ביטול של פעולה", f"#{row['original']}"))
        if row["reversed_by"]:
            details.append(("בוטלה ע״י פעולה", f"#{row['reversed_by']}"))

        box = tk.Frame(win, bg=COLORS["surface"], padx=22, pady=14)
        box.pack(fill="both", expand=True)
        for idx, (k, v) in enumerate(details):
            tk.Label(box, text=f":{k}", bg=COLORS["surface"], fg=COLORS["muted"], font=(FONT, 9, "bold"), anchor="e").grid(row=idx, column=1, sticky="e", padx=(14, 0), pady=3)
            tk.Label(box, text=v, bg=COLORS["surface"], fg=COLORS["text"], font=(FONT, 10), anchor="e").grid(row=idx, column=0, sticky="e", pady=3)
        box.columnconfigure(0, weight=1)

        tk.Frame(win, bg=COLORS["border"], height=1).pack(fill="x")
        tail = tk.Frame(win, bg=COLORS["surface_alt"], padx=20, pady=12)
        tail.pack(fill="x")
        ActionButton(tail, "חשבוניות וקבלות 📎", lambda: AttachmentsDialog(self, entry, can_edit=self.can("attachments")), variant="primary").pack(side="right", padx=4)
        if row["kind"] == "payment":
            ActionButton(tail, "הפקת אישור תשלום", lambda: self.show_receipt(entry), variant="soft").pack(side="right", padx=4)
        ActionButton(tail, "סגירה", win.destroy, variant="secondary").pack(side="left")
        win.bind("<Escape>", lambda _: win.destroy())

    def recurring_page(self):
        bar = self.bar()
        self.button(bar, "+ הוצאה קבועה חדשה", lambda: edit_template(None), primary=True, perm="manage_recurring")
        self.button(bar, "רישום הוצאה מהמועד", lambda: pay(), variant="soft", perm="record_expense")
        self.button(bar, "שיוך הוצאה קיימת", lambda: link(), perm="manage_recurring")
        self.button(bar, "עריכת תבנית", lambda: edit_template(self.selection(tpl_tree)), perm="manage_recurring")
        self.button(bar, "← חזרה לתנועות", lambda: self.show(4))

        due = self.ledger.recurring_due(today())
        due_tree = self.table(
            ("מועד", "ספק", "קטגוריה", "סכום רגיל", "תדירות (חודשים)", "תיאור", "מצב"),
            [
                (f"{r['id']}-{period}", (date_text(day), r["supplier_name"] or "—", r["category_name"], amount(r["usual_amount"]), r["frequency_months"], r["notes"] or "—", "ממתין לרישום"))
                for r, period, day in due
            ],
            height=5,
            title="מועדים ממתינים לרישום",
        )

        templates = {r["id"]: r for r in self.ledger.list_recurring()}
        tpl_tree = self.table(
            ("ספק", "קטגוריה", "סכום רגיל", "סוג סכום", "כל X חודשים", "יום בחודש", "התחלה", "סיום", "מצב", "תיאור"),
            [
                (
                    r["id"],
                    (
                        r["supplier_name"] or "—", r["category_name"], amount(r["usual_amount"]),
                        "משתנה" if r["variable"] else "קבוע", r["frequency_months"], r["due_day"],
                        date_text(r["starts"]), date_text(r["ends"] or ""), "פעילה" if r["active"] else "מושבתת", r["notes"],
                    ),
                )
                for r in templates.values()
            ],
            height=7,
            title="תבניות הוצאות קבועות (לחיצה כפולה לעריכה)",
        )
        tpl_tree.bind("<Double-1>", lambda e: edit_template(int(tpl_tree.identify_row(e.y))) if tpl_tree.identify_row(e.y).isdigit() else None)

        def chosen():
            selected = due_tree.selection()
            if not selected or selected[0] == "empty":
                raise Problem("יש לבחור מועד בטבלת המועדים הממתינים")
            return next(item for item in due if f"{item[0]['id']}-{item[1]}" == selected[0])

        def pay():
            row, period, day = chosen()
            self.movement_form(
                "expense",
                dict(
                    day=date_text(day), amount=number(row["usual_amount"]),
                    party=row["supplier_name"] or "", supplier=row["supplier_name"] or "ללא שיוך",
                    category=row["category_name"], description=row["notes"] or row["category_name"],
                    recurring=row["id"], period=period,
                ),
            )

        def link():
            row, period, _ = chosen()
            expenses = self.store.rows(
                """
                SELECT e.id, e.day, e.party, e.cash FROM entries e
                WHERE e.kind='expense'
                  AND NOT EXISTS (SELECT 1 FROM entries rev WHERE rev.original=e.id)
                  AND e.id NOT IN (SELECT expense FROM recurring_matches)
                ORDER BY e.day DESC, e.id DESC LIMIT 100
                """
            )
            choices = {f"#{e['id']} · {date_text(e['day'])} · {e['party']} · {amount(-e['cash'])}": e["id"] for e in expenses}
            if not choices:
                raise Problem("אין הוצאה פעילה זמינה לשיוך")

            def save(values):
                self.ledger.match_recurring(row["id"], period, choices[values["expense"]], actor=self.user)
                self.refresh("ההוצאה שויכה למועד")

            Dialog(self, "שיוך הוצאה קיימת", [("expense", "הוצאה", next(iter(choices)), tuple(choices))], save)

        def edit_template(rec_id):
            self.require("manage_recurring")
            row = templates.get(rec_id)
            suppliers = {r["name"]: r["id"] for r in self.store.rows("SELECT id,name FROM suppliers WHERE active=1 ORDER BY name")}
            categories = {r["name"]: r["id"] for r in self.store.rows("SELECT id,name FROM categories WHERE kind='expense' AND active=1 ORDER BY name")}
            if not categories:
                raise Problem("אין קטגוריות הוצאה פעילות. יש להוסיף קטגוריה בהגדרות.")
            fields = [
                ("supplier", "ספק", (row["supplier_name"] or "ללא שיוך") if row else "ללא שיוך", ("ללא שיוך", *suppliers)),
                ("category", "קטגוריה", row["category_name"] if row else next(iter(categories)), tuple(categories)),
                ("amount", "סכום רגיל בשקלים", number(row["usual_amount"]) if row else "", None),
                ("variable", "סכום", ("משתנה" if row["variable"] else "קבוע") if row else "קבוע", ("קבוע", "משתנה")),
                ("frequency", "כל כמה חודשים", str(row["frequency_months"]) if row else "1", None),
                ("due_day", "יום בחודש (1-31)", str(row["due_day"]) if row else "1", None),
                ("starts", "תאריך התחלה", date_text(row["starts"]) if row else date_text(today()), None),
                ("ends", "תאריך סיום (אופציונלי)", date_text(row["ends"] or "") if row else "", None),
                ("notes", "תיאור", row["notes"] if row else "", None),
                ("active", "מצב", ("פעילה" if row["active"] else "מושבתת") if row else "פעילה", ("פעילה", "מושבתת")),
            ]

            def save(values):
                self.ledger.save_recurring(
                    category=categories[values["category"]],
                    usual_amount=money(values["amount"]),
                    frequency_months=int(values["frequency"]),
                    due_day=int(values["due_day"]),
                    starts=iso(values["starts"]),
                    supplier=suppliers.get(values["supplier"]),
                    variable=values["variable"] == "משתנה",
                    ends=iso(values["ends"]) if values["ends"].strip() else None,
                    notes=values["notes"],
                    active=values["active"] == "פעילה",
                    rec_id=rec_id,
                    actor=self.user,
                )
                self.refresh("ההוצאה הקבועה נשמרה")

            Dialog(self, "עריכת הוצאה קבועה" if row else "הוצאה קבועה חדשה", fields, save)

    # ------------------------------------------------------------------
    # Page 5: Suppliers & Supplier Card
    # ------------------------------------------------------------------

    def suppliers(self):
        if isinstance(self.mode, tuple) and self.mode[0] == "supplier":
            self.supplier_card(self.mode[1])
            return
        bar = self.bar(card=True)
        query = self.input(bar, "חיפוש ספק", width=22)
        self.button(bar, "פתיחת כרטיס ספק", lambda: self.show(5, ("supplier", self.selection(tree))), primary=True)
        self.button(bar, "+ ספק חדש", lambda: self.edit_supplier(None), variant="soft", perm="manage_suppliers")
        self.button(bar, "עריכת ספק", lambda: self.edit_supplier(self.selection(tree)), perm="manage_suppliers")
        self.button(bar, "+ רישום הוצאה", lambda: self.movement_form("expense"), perm="record_expense")

        summary = self.ledger.suppliers_summary()
        tree = self.table(("שם", "שירות", "טלפון", "איש קשר", "שולם החודש", "שולם השנה", "הוצאה אחרונה", "קבצים", "מצב"))

        def load(*_):
            data = []
            needle = query.get().strip().casefold()
            for s in summary:
                if needle not in " ".join(str(s[k]) for k in ("name", "service", "phone", "contact")).casefold():
                    continue
                data.append((
                    s["id"],
                    (
                        s["name"], s["service"], s["phone"], s["contact"],
                        amount(s["month_total"]), amount(s["year_total"]),
                        date_text(s["last_day"]), str(s["attachments_count"]) if s["attachments_count"] else "",
                        "פעיל" if s["active"] else "לא פעיל",
                    ),
                ))
            self.fill(tree, data)

        query.trace_add("write", load)
        tree.bind("<Double-1>", lambda e: self.show(5, ("supplier", int(tree.identify_row(e.y)))) if tree.identify_row(e.y).isdigit() else None)
        load()

    def edit_supplier(self, identifier):
        self.require("manage_suppliers")
        row = self.store.rows("SELECT * FROM suppliers WHERE id=?", identifier)[0] if identifier else None
        labels = (("name", "שם"), ("service", "סוג שירות"), ("phone", "טלפון"), ("contact", "איש קשר"), ("email", "דואר אלקטרוני"), ("notes", "הערות"))
        fields = [(key, label, row[key] if row else "", None) for key, label in labels]
        fields.append(("active", "מצב", "פעיל" if not row or row["active"] else "לא פעיל", ("פעיל", "לא פעיל")))

        def save(v):
            self.ledger.save_supplier(
                v["name"], v["service"], v["phone"], v["contact"], v["email"], v["notes"],
                active=v["active"] == "פעיל", supplier_id=identifier, actor=self.user,
            )
            self.refresh("פרטי הספק נשמרו")

        Dialog(self, "פרטי ספק", fields, save)

    def supplier_card(self, supplier_id):
        s = next(item for item in self.ledger.suppliers_summary() if item["id"] == supplier_id)
        hcard = CardFrame(self.main, padx=16, pady=12)
        hcard.pack(fill="x", pady=(0, 8))
        hb = hcard.inner
        tk.Label(hb, text=f"כרטיס ספק  •  {s['name']} ({s['service'] or 'כללי'})", bg=COLORS["surface"], fg=COLORS["text"], font=(FONT, 14, "bold"), anchor="e").pack(side="right")
        tk.Label(hb, text=f"שולם השנה: {amount(s['year_total'])}", bg=COLORS["surface"], fg=COLORS["action"], font=(FONT, 12, "bold")).pack(side="left")

        tk.Label(
            self.main,
            text=f"איש קשר: {s['contact'] or '—'}   •   טלפון: {s['phone'] or '—'}   •   דוא״ל: {s['email'] or '—'}",
            bg=COLORS["background"], fg=COLORS["muted"], anchor="e", font=(FONT, 9),
        ).pack(fill="x", pady=(0, 6))

        bar = self.bar()
        self.button(bar, "+ רישום הוצאה לספק", lambda: self.movement_form("expense", dict(party=s["name"], supplier=s["name"])), primary=True, perm="record_expense")
        self.button(bar, "עריכת פרטי ספק", lambda: self.edit_supplier(supplier_id), variant="soft", perm="manage_suppliers")
        self.button(bar, "חשבוניות התנועה 📎", lambda: AttachmentsDialog(self, self.selection(tree), can_edit=self.can("attachments")))
        self.button(bar, "← חזרה לספקים", lambda: self.show(5))

        filters = self.bar(card=True)
        start = self.input(filters, "מתאריך", f"01/01/{date.today().year}", width=11)
        end = self.input(filters, "עד תאריך", date_text(today()), width=11)
        period_total_var = tk.StringVar()
        self.button(filters, "סינון תקופה", lambda: load(), variant="soft")
        self.button(filters, "ייצוא Excel", lambda: self.export_xlsx_report(f"היסטוריית ספק {s['name']}", headers, current_rows))
        tk.Label(filters, textvariable=period_total_var, bg=COLORS["surface"], fg=COLORS["action"], font=(FONT, 10, "bold")).pack(side="left")

        headers = ("תאריך", "מספר", "קופה", "סוג", "קטגוריה", "תיאור", "אמצעי", "אסמכתא", "סכום", "קבצים")
        tree = self.table(headers, height=8)
        current_rows = []

        def load():
            nonlocal current_rows
            lo, hi = self.bounds(start.get(), end.get())
            hist = self.ledger.supplier_history(supplier_id, lo, hi)
            net_total = -sum(r["cash"] for r in hist)
            period_total_var.set(f"סה״כ בתקופה הנבחרת: {amount(net_total)}")
            rows = []
            for r in hist:
                rows.append((
                    r["id"],
                    (
                        date_text(r["day"]), r["id"], ACCOUNTS.get(r["account"], "בנק"), LABELS[r["kind"]], r["category_name"] or "—",
                        r["description"], r["method"], r["reference"], amount(-r["cash"]),
                        f"📎 {r['attachment_count']}" if r["attachment_count"] else "",
                    ),
                ))
            current_rows = rows
            self.fill(tree, rows)

        load()

        atts = self.store.list_attachments(supplier_id=supplier_id)
        if atts:
            att_tree = self.table(
                ("תאריך תנועה", "מספר תנועה", "תיאור", "שם קובץ"),
                [(a["id"], (date_text(a["entry_day"]), a["entry"], a["entry_description"], a["filename"])) for a in atts],
                height=4,
                title="חשבוניות וקבלות מצורפות לספק (לחיצה כפולה לפתיחה)",
            )
            att_tree.bind("<Double-1>", lambda e: os.startfile(str(self.store.attachment_path(int(att_tree.identify_row(e.y)))[0])) if att_tree.identify_row(e.y).isdigit() else None)

    @staticmethod
    def cash_row(row, units, include_attachments=False):
        inflow = row["base_kind"] != "expense"
        kind = LABELS[row["kind"]]
        if row["original"]:
            kind += f" · #{row['original']}"
        acct_lbl = ACCOUNTS.get(row.get("account", "bank"), "בנק")
        base = (
            date_text(row["day"]), row["id"], acct_lbl, kind, row["description"],
            row["category_name"] or "", units.get(row["unit"], row["supplier_name"] or row["party"]),
            row["method"], amount(row["cash"]) if inflow else "", amount(-row["cash"]) if not inflow else "",
            amount(row["balance"]),
        )
        if include_attachments:
            att_txt = f"📎 {row['attachment_count']}" if row.get("attachment_count") else ""
            return row["id"], (*base, att_txt)
        return row["id"], base

    # ------------------------------------------------------------------
    # Page 6: Reports & Analytics
    # ------------------------------------------------------------------

    def reports(self):
        options = (
            "דוח יתרת קופה (בנק ומזומן)",
            "דוח הכנסות חודשי",
            "דוח הוצאות חודשי",
            "דוח חובות דיירים",
            "דוח תשלומים לפי יחידה",
            "דוח הוצאות לפי ספק",
            "דוח הוצאות לפי קטגוריה",
            "דוח שנתי מסכם",
            "דוח השוואת הכנסות והוצאות",
            "דוח תנועות כספיות מלא",
        )
        bar = self.bar(card=True)
        selected, from_date, to_date = self.mode or (options[0], f"01/{today()[5:7]}/{today()[:4]}", date_text(today()))
        if selected not in options:
            selected = options[0]
        option = self.input(bar, "סוג דוח", selected, options, 26)
        start = self.input(bar, "מתאריך", from_date, width=11)
        end = self.input(bar, "עד תאריך", to_date, width=11)
        self.button(bar, "הצגת דוח", lambda: self.show(6, (option.get(), start.get(), end.get())), primary=True)

        lo, hi = self.bounds(from_date, to_date)
        if selected == "דוח חובות דיירים":
            self.debtor_table()
            return

        rows = []
        totals_row = None
        kpis = []
        chart_svg = ""
        subtitle = f"תקופה: {from_date or 'תחילה'} עד {to_date or 'היום'}"
        entries = [r for r in self.ledger.cash()[1] if lo <= r["day"] <= hi]
        units = {u["id"]: f"בניין {u['building']} · {u['tenant'] or u['owner'] or unit_name(u)}" for u in self.ledger.units()}
        year = (lo or today())[:4]
        period = (lo or today())[:7]

        if selected == "דוח יתרת קופה (בנק ומזומן)":
            rep = self.ledger.report(period)
            last = monthrange(int(period[:4]), int(period[5:]))[1]
            month_end = f"{period}-{last:02d}"
            bals_end = self.ledger.balances(through=month_end)
            debts = sum(max(0, self.ledger.account(u["id"], month_end)["unpaid_total"]) for u in self.ledger.units())
            headers = ("פריט", "סכום")
            labels = [
                ("יתרת פתיחה לחודש", rep["initial"]),
                ("חיובים חודשיים (גבייה צפויה)", rep["charges"]),
                ("תשלומי דיירים בפועל", rep["payment"]),
                ("הכנסות אחרות", rep["income"]),
                ("סך הכנסות החודש", rep["payment"] + rep["income"]),
                ("סך הוצאות החודש", -rep["expense"]),
                ("יתרת סיום כוללת בקופה", rep["final"]),
                ("מתוכה: יתרה בבנק 🏦", bals_end["bank"]),
                ("מתוכה: יתרה במזומן 💵", bals_end["cash"]),
                ("חובות דיירים לסוף החודש", debts),
            ]
            rows = [(i, (lbl, amount(val))) for i, (lbl, val) in enumerate(labels)]
            kpis = [
                ("סה״כ בקופה", amount(bals_end["total"])),
                ("יתרה בבנק", amount(bals_end["bank"])),
                ("יתרה במזומן", amount(bals_end["cash"])),
                ("חובות לסוף החודש", amount(debts)),
            ]
            subtitle = f"חודש: {period[5:]}/{period[:4]}"

        elif selected == "דוח הכנסות חודשי":
            headers = ("תאריך", "מספר", "קופה", "סוג", "יחידה / מקור", "תיאור", "אמצעי", "אסמכתא", "סכום")
            incomes = [r for r in entries if r["base_kind"] in ("payment", "income")]
            total_in = sum(r["cash"] for r in incomes)
            rows = [
                (r["id"], (date_text(r["day"]), r["id"], ACCOUNTS.get(r.get("account", "bank"), "בנק"), LABELS[r["kind"]], units.get(r["unit"], r["party"]), r["description"] or "תשלום ועד", r["method"], r["reference"], amount(r["cash"])))
                for r in incomes
            ]
            totals_row = ("סה״כ הכנסות", "", "", "", "", "", "", "", amount(total_in))
            kpis = [("סך הכנסות בתקופה", amount(total_in)), ("מספר תנועות", str(len(incomes)))]

        elif selected == "דוח הוצאות חודשי":
            headers = ("תאריך", "מספר", "קופה", "ספק / מקבל", "קטגוריה", "תיאור", "אמצעי", "אסמכתא", "סכום")
            exps = [r for r in entries if r["base_kind"] == "expense"]
            total_ex = -sum(r["cash"] for r in exps)
            rows = [
                (r["id"], (date_text(r["day"]), r["id"], ACCOUNTS.get(r.get("account", "bank"), "בנק"), r["supplier_name"] or r["party"], r["category_name"] or "—", r["description"], r["method"], r["reference"], amount(-r["cash"])))
                for r in exps
            ]
            totals_row = ("סה״כ הוצאות", "", "", "", "", "", "", "", amount(total_ex))
            kpis = [("סך הוצאות בתקופה", amount(total_ex)), ("מספר תנועות", str(len(exps)))]

        elif selected == "דוח תשלומים לפי יחידה":
            headers = ("יחידה", "תאריך", "מספר", "קופה", "משלם", "אמצעי", "אסמכתא", "סכום")
            payments = sorted((r for r in entries if r["base_kind"] == "payment"), key=lambda r: (r["unit"] or 0, r["day"], r["id"]))
            total_pay = sum(r["cash"] for r in payments)
            rows = [
                (r["id"], (units.get(r["unit"], ""), date_text(r["day"]), r["id"], ACCOUNTS.get(r.get("account", "bank"), "בנק"), r["party"], r["method"], r["reference"], amount(r["cash"])))
                for r in payments
            ]
            totals_row = ("סה״כ תשלומים", "", "", "", "", "", "", amount(total_pay))

        elif selected == "דוח הוצאות לפי ספק":
            headers = ("ספק", "סך הוצאות", "אחוז מסך ההוצאות")
            by_sup = self.ledger.expenses_by_supplier(lo, hi)
            grand = sum(v for _, v in by_sup)
            rows = [(i, (name, amount(val), f"{val / grand:.1%}" if grand else "—")) for i, (name, val) in enumerate(by_sup)]
            totals_row = ("סה״כ", amount(grand), "100%" if grand else "—")

        elif selected == "דוח הוצאות לפי קטגוריה":
            headers = ("קטגוריה", "סך הוצאות", "אחוז מסך ההוצאות")
            totals = {}
            for r in entries:
                if r["base_kind"] == "expense":
                    lbl = r["category_name"] or "ללא קטגוריה"
                    totals[lbl] = totals.get(lbl, 0) - r["cash"]
            ordered = sorted(((k, v) for k, v in totals.items() if v != 0), key=lambda x: -x[1])
            grand = sum(v for _, v in ordered)
            rows = [(i, (lbl, amount(val), f"{val / grand:.1%}" if grand else "—")) for i, (lbl, val) in enumerate(ordered)]
            totals_row = ("סה״כ", amount(grand), "100%" if grand else "—")

        elif selected in ("דוח שנתי מסכם", "דוח השוואת הכנסות והוצאות"):
            rep = self.ledger.report(year)
            bals_y = self.ledger.balances(through=f"{year}-12-31")
            headers = ("חודש", "הכנסות", "הוצאות", "עודף / גירעון", "יתרת פתיחה", "יתרת סיום")
            series = []
            for m in range(1, 13):
                m_rep = self.ledger.report(f"{year}-{m:02d}")
                inc = m_rep["payment"] + m_rep["income"]
                exp = -m_rep["expense"]
                series.append({"period": f"{year}-{m:02d}", "label": f"{m:02d}/{year[2:]}", "income": inc, "expense": exp, "net": inc - exp})
                rows.append((m, (f"{m:02d}/{year}", amount(inc), amount(exp), amount(inc - exp), amount(m_rep["initial"]), amount(m_rep["final"]))))
            totals_row = ("סך שנתי", amount(rep["payment"] + rep["income"]), amount(-rep["expense"]), amount(rep["final"] - rep["initial"]), amount(rep["initial"]), amount(rep["final"]))
            kpis = [
                ("הכנסות שנתיות", amount(rep["payment"] + rep["income"])),
                ("הוצאות שנתיות", amount(-rep["expense"])),
                ("יתרה בבנק", amount(bals_y["bank"])),
                ("יתרה במזומן", amount(bals_y["cash"])),
            ]
            subtitle = f"שנת {year}"
            chart_svg = monthly_chart_svg(series)

        else:
            headers = ("תאריך", "מספר", "קופה", "סוג", "תיאור", "קטגוריה", "יחידה או צד", "אמצעי", "הכנסה", "הוצאה", "יתרה")
            rows = [self.cash_row(r, units) for r in entries]

        actions = self.bar()
        self.button(actions, "ייצוא Excel (.xlsx)", lambda: self.export_xlsx_report(selected, headers, rows, totals_row), primary=True)
        self.button(actions, "ייצוא PDF", lambda: self.export_pdf_report(selected, headers, rows, subtitle=subtitle, kpis=kpis, totals=totals_row, chart_svg=chart_svg), variant="soft")
        self.button(actions, "תצוגה להדפסה", lambda: self.print_report(selected, headers, rows, subtitle=subtitle, kpis=kpis, totals=totals_row, chart_svg=chart_svg))
        self.button(actions, "ייצוא CSV", lambda: self.export(headers, rows))

        if selected == "דוח השוואת הכנסות והוצאות":
            cc = CardFrame(self.main, padx=10, pady=8)
            cc.pack(fill="x", pady=(0, 8))
            IncomeExpenseChart(cc.inner, series, height=190).pack(fill="x")

        display_rows = list(rows)
        if totals_row:
            display_rows.append(("total", totals_row))
        self.table(headers, display_rows)

    # ------------------------------------------------------------------
    # Page 7: Settings
    # ------------------------------------------------------------------

    def settings(self):
        if self.mode == "categories":
            render_categories_page(self)
            return
        if self.mode == "users":
            render_users_page(self)
            return
        if self.mode == "audit":
            render_audit_page(self)
            return
        if self.mode == "backups":
            render_backups_page(self)
            return
        render_settings_home(self)

    def general(self):
        self.require("manage_settings")
        labels = [("name", "שם הוועד"), ("complex", "שם המתחם"), ("address", "כתובת"), ("contact", "פרטי קשר")]

        def save(v):
            if not v["name"].strip() or not v["complex"].strip():
                raise Problem("יש להזין שם ועד ומתחם")
            self.store.save(**{k: val.strip() for k, val in v.items()})
            self.after_idle(self.enter)

        Dialog(self, "פרטים כלליים", [(k, label, self.store.get(k), None) for k, label in labels], save)

    def default_rate(self):
        self.require("manage_rates")

        def save(v):
            self.ledger.rate(None, iso(v["day"]), money(v["amount"]), actor=self.user)
            self.refresh("תעריף ברירת המחדל עודכן")

        Dialog(
            self, "תעריף ברירת מחדל לכל היחידות",
            [("amount", "תעריף בשקלים", number(int(self.store.get("rate"))), None), ("day", "מועד תחולה", date_text(today()), None)],
            save,
            lambda _, bar: tk.Label(bar, text="יחידות מפוצלות יחויבו במחצית. הפעולה מחילה תעריף חדש על כל היחידות.", bg=COLORS["surface_alt"], fg=COLORS["muted"], anchor="e", font=(FONT, 8)).pack(side="bottom", fill="x", pady=(0, 8)),
        )

    def password(self):
        def save(v):
            if not self.store.authenticate_user(self.user["username"], v["old"]):
                raise Problem("הסיסמה הקיימת אינה נכונה")
            if v["new"] != v["confirm"]:
                raise Problem("הסיסמאות אינן זהות")
            self.store.set_password(v["new"], username=self.user["username"])
            self.refresh("הסיסמה שונתה בהצלחה")

        Dialog(self, "שינוי סיסמה", [(k, label, "", "password") for k, label in [("old", "סיסמה קיימת"), ("new", "סיסמה חדשה"), ("confirm", "אימות סיסמה חדשה")]], save)

    def backup(self):
        self.require("backup")
        folder = self.store.get("backup") or str(self.store.path.parent / "backups")
        path = self.store.backup_bundle(folder, kind="manual", actor=self.user)
        self.refresh("הגיבוי המלא נשמר בהצלחה")
        messagebox.showinfo("גיבוי מלא נשמר", f"הגיבוי (כולל מסד נתונים וכל הקבצים המצורפים) נשמר אל:\n{path}", parent=self)

    def restore(self):
        if self.logged:
            self.require("restore")
        source = filedialog.askopenfilename(
            parent=self,
            title="בחירת קובץ גיבוי לשחזור",
            filetypes=[("קבצי גיבוי ועד בית", "*.zip;*.sqlite3"), ("ארכיון גיבוי ZIP", "*.zip"), ("SQLite", "*.sqlite3"), ("כל הקבצים", "*.*")],
        )
        if not source:
            return
        self.store.inspect_backup(source)
        if not messagebox.askyesno(
            "שחזור מגיבוי",
            "השחזור יחליף את כל הנתונים, המסמכים המצורפים והסיסמאות.\nאם קיימים נתונים ייווצר גיבוי בטיחות לפני ההחלפה.\nלהמשיך?",
            parent=self,
        ):
            return
        self.store.restore(source, self.store.path.parent / "before-restore")
        self.lock(notice="השחזור הושלם — יש להיכנס עם פרטי הגישה של הגיבוי")

    def export_data(self):
        headers = ("מזהה", "בניין", "דירה", "יחידה", "בעלים", "שוכר", "טלפון", "דוא״ל", "תעריף", "יתרה", "מצב")
        rows = [
            (
                u["id"],
                (
                    u["id"], u["building"], "" if u["apartment"].startswith("@") else u["apartment"], u["subunit"],
                    u["owner"], u["tenant"], u["phone"], u["email"],
                    amount(u["rate"] or 0), amount(self.ledger.account(u["id"])["balance"]),
                    "פעילה" if u["active"] else "לא פעילה",
                ),
            )
            for u in self.ledger.units()
        ]
        self.export_xlsx_report("דיירים ויחידות", headers, rows)


def startup_error(text):
    root = tk.Tk()
    root.withdraw()
    try:
        messagebox.showerror("ועד הבית", text, parent=root)
    finally:
        root.destroy()


def run():
    import msvcrt

    enable_hidpi()
    data_dir = Path(os.environ.get("VAAD_DATA", Path(os.environ["LOCALAPPDATA"]) / "VaadBayt"))
    configure_logging(data_dir)
    path = data_dir / "vaad.sqlite3"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = path.with_suffix(".lock").open("a+b")
    except OSError:
        startup_error("תיקיית הנתונים אינה נגישה")
        return
    with lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            startup_error("המערכת כבר פתוחה עבור תיקיית נתונים זו")
            return
        try:
            store = Store(path)
        except (Problem, sqlite3.Error, OSError):
            logger.exception("Failed to initialize database")
            startup_error("קובץ הנתונים אינו נגיש או פגום")
            return
        try:
            App(store).mainloop()
        finally:
            store.db.close()
