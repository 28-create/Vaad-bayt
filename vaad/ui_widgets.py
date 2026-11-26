"""Modern Hebrew RTL desktop widgets: HiDPI, vector logo, elevated cards, pills, buttons, chart, and dialogs."""

import ctypes
import os
import re
import sqlite3
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .reports import fmt_date, fmt_money
from .store import Problem
from .theme import COLORS, FONT

_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def enable_hidpi():
    """Enable crisp HiDPI scaling on Windows 10/11 before creating tk.Tk()."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def sort_key(raw_value):
    """Smart sort key handling DD/MM/YYYY dates, RTL ₪ currency with LRM & Unicode minus, and numbers."""
    text = str(raw_value or "").replace("\u200e", "").replace("\u200f", "").strip()
    if not text or text == "—":
        return (3, "")
    m = _DATE_RE.match(text)
    if m:
        return (0, f"{m.group(3)}-{m.group(2)}-{m.group(1)}")
    num_text = text.replace("₪", "").replace(",", "").replace("−", "-").replace("%", "").strip()
    try:
        return (1, float(num_text))
    except ValueError:
        return (2, text.casefold())


class BrandLogo(tk.Canvas):
    """Minimalist architectural 3-building vector emblem (Shahrai 14 · 16 · 18)."""

    def __init__(self, parent, size=44, bg=COLORS["nav"]):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0, bd=0)
        s = size
        # Soft rounded-square backdrop
        pad = 2
        r = max(6, s // 5)
        self._round_rect(pad, pad, s - pad, s - pad, r, fill="#1E293B", outline="#334155")
        # Three minimalist towers
        self.create_rectangle(s * 0.16, s * 0.44, s * 0.34, s * 0.84, fill="#3B82F6", outline="")
        self.create_rectangle(s * 0.39, s * 0.24, s * 0.61, s * 0.84, fill="#60A5FA", outline="")
        self.create_rectangle(s * 0.66, s * 0.36, s * 0.84, s * 0.84, fill="#38BDF8", outline="")
        # Crisp window dots
        for wy in (0.52, 0.65):
            self.create_rectangle(s * 0.21, s * wy, s * 0.29, s * (wy + 0.07), fill="#E0F2FE", outline="")
        for wy in (0.33, 0.46, 0.59, 0.72):
            self.create_rectangle(s * 0.44, s * wy, s * 0.49, s * (wy + 0.06), fill="#FFFFFF", outline="")
            self.create_rectangle(s * 0.52, s * wy, s * 0.57, s * (wy + 0.06), fill="#FFFFFF", outline="")
        for wy in (0.45, 0.58, 0.70):
            self.create_rectangle(s * 0.71, s * wy, s * 0.79, s * (wy + 0.06), fill="#E0F2FE", outline="")
        # Ground accent bar
        self.create_rectangle(s * 0.12, s * 0.83, s * 0.88, s * 0.88, fill="#93C5FD", outline="")

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]
        return self.create_polygon(pts, smooth=True, **kw)


class CardFrame(tk.Frame):
    """Elevated crisp white surface card with subtle border and soft bottom shadow hairline."""

    def __init__(self, parent, padx=14, pady=12, bg=COLORS["surface"]):
        super().__init__(parent, bg=COLORS["shadow"], bd=0)
        self.inner = tk.Frame(
            self,
            bg=bg,
            highlightbackground=COLORS["border"],
            highlightthickness=1,
            padx=padx,
            pady=pady,
        )
        self.inner.pack(fill="both", expand=True, pady=(0, 2))


class PillBadge(tk.Frame):
    """Clickable tinted pill badge for Topbar balances and status summaries."""

    def __init__(self, parent, label, value, bg, fg, border, command=None):
        super().__init__(parent, bg=bg, highlightbackground=border, highlightthickness=1, padx=11, pady=5)
        self._bg = bg
        self._hover = COLORS["surface_hover"] if bg == COLORS["surface"] else border
        self._cmd = command

        lbl_val = tk.Label(self, text=value, bg=bg, fg=fg, font=(FONT, 9, "bold"))
        lbl_val.pack(side="left")
        lbl_txt = tk.Label(self, text=f"  {label}", bg=bg, fg=fg, font=(FONT, 9))
        lbl_txt.pack(side="left")
        self._parts = [self, lbl_val, lbl_txt]

        if command:
            for w in self._parts:
                w.configure(cursor="hand2")
                w.bind("<Button-1>", lambda _: command())
                w.bind("<Enter>", self._enter)
                w.bind("<Leave>", self._leave)

    def _enter(self, _e=None):
        for w in self._parts:
            w.configure(bg=self._hover)

    def _leave(self, _e=None):
        for w in self._parts:
            w.configure(bg=self._bg)


class ActionButton(tk.Button):
    """Modern flat styled button with clean hover feedback and semantic variants."""

    VARIANTS = {
        "primary": (COLORS["action"], "#FFFFFF", COLORS["action_hover"], "#FFFFFF", COLORS["action"]),
        "secondary": (COLORS["surface"], COLORS["text"], COLORS["surface_hover"], COLORS["text"], COLORS["border_strong"]),
        "soft": (COLORS["action_soft"], COLORS["action"], COLORS["action_soft_hover"], COLORS["action_hover"], COLORS["action_border"]),
        "success": (COLORS["success"], "#FFFFFF", COLORS["success_dark"], "#FFFFFF", COLORS["success"]),
        "danger": (COLORS["danger_bg"], COLORS["danger"], COLORS["danger_border"], COLORS["danger_dark"], COLORS["danger_border"]),
        "ghost": (COLORS["background"], COLORS["text_secondary"], COLORS["border"], COLORS["text"], COLORS["background"]),
    }

    def __init__(self, parent, text, command, variant="secondary", disabled=False, padx=13, pady=6, font_size=9):
        bg, fg, hbg, hfg, border = self.VARIANTS.get(variant, self.VARIANTS["secondary"])
        self._bg, self._fg, self._hbg, self._hfg = bg, fg, hbg, hfg
        super().__init__(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=hbg,
            activeforeground=hfg,
            disabledforeground="#94A3B8",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=border,
            highlightcolor=border,
            padx=padx,
            pady=pady,
            font=(FONT, font_size, "bold" if variant in ("primary", "success", "soft") else "normal"),
            cursor="arrow" if disabled else "hand2",
            state="disabled" if disabled else "normal",
        )
        if not disabled:
            self.bind("<Enter>", lambda _: self.configure(bg=self._hbg, fg=self._hfg))
            self.bind("<Leave>", lambda _: self.configure(bg=self._bg, fg=self._fg))


class MetricCard(tk.Frame):
    """Modern SaaS KPI card supporting light cards (with icon badge & accent) and dark hero cards."""

    def __init__(self, parent, title, value, subtitle="", accent=COLORS["action"], command=None, icon="", dark=False):
        bg = COLORS["nav"] if dark else COLORS["surface"]
        hover = COLORS["nav_surface"] if dark else COLORS["surface_alt"]
        border = "#1E293B" if dark else COLORS["border"]
        shadow = "#070C17" if dark else COLORS["shadow"]
        title_fg = "#94A3B8" if dark else COLORS["muted"]
        val_fg = "#FFFFFF" if dark else COLORS["text"]
        sub_fg = "#38BDF8" if dark else accent

        super().__init__(parent, bg=shadow, bd=0)
        self._command = command
        self._base_bg = bg
        self._hover_bg = hover

        card = tk.Frame(self, bg=bg, highlightbackground=border, highlightthickness=1)
        card.pack(fill="both", expand=True, pady=(0, 2))

        accent_bar = tk.Frame(card, bg=accent, width=5)
        accent_bar.pack(side="right", fill="y")

        body = tk.Frame(card, bg=bg, padx=14, pady=12)
        body.pack(side="right", fill="both", expand=True)

        top_row = tk.Frame(body, bg=bg)
        top_row.pack(fill="x")

        lbl_title = tk.Label(top_row, text=title, bg=bg, fg=title_fg, font=(FONT, 9, "bold"), anchor="e")
        lbl_title.pack(side="right")

        self._widgets = [card, body, top_row, lbl_title]
        if icon:
            badge_bg = "#1E293B" if dark else COLORS["surface_alt"]
            lbl_icon = tk.Label(top_row, text=icon, bg=badge_bg, fg=sub_fg, font=(FONT, 11), padx=6, pady=1)
            lbl_icon.pack(side="left")

        lbl_val = tk.Label(body, text=value, bg=bg, fg=val_fg, font=(FONT, 17 if dark else 15, "bold"), anchor="e")
        lbl_val.pack(fill="x", pady=(4, 1))
        self._widgets.append(lbl_val)

        if subtitle:
            lbl_sub = tk.Label(body, text=subtitle, bg=bg, fg=sub_fg, font=(FONT, 8, "bold" if dark else "normal"), anchor="e")
            lbl_sub.pack(fill="x", pady=(2, 0))
            self._widgets.append(lbl_sub)

        if command:
            for w in self._widgets + [accent_bar]:
                w.configure(cursor="hand2")
                w.bind("<Button-1>", self._on_click)
                w.bind("<Enter>", self._on_enter)
                w.bind("<Leave>", self._on_leave)

    def _on_click(self, _event=None):
        if self._command:
            self._command()

    def _on_enter(self, _event=None):
        for w in self._widgets:
            w.configure(bg=self._hover_bg)

    def _on_leave(self, _event=None):
        for w in self._widgets:
            w.configure(bg=self._base_bg)


class IncomeExpenseChart(tk.Canvas):
    """Sleek interactive 12-month Income vs Expense bar chart with hover band & floating tooltip."""

    def __init__(self, parent, series, height=190):
        super().__init__(
            parent,
            height=height,
            bg=COLORS["surface"],
            highlightthickness=0,
            bd=0,
        )
        self.series = series
        self._bars = []
        self._hover_idx = None
        self.bind("<Configure>", lambda _: self.redraw())
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)

    def redraw(self):
        self.delete("all")
        self._bars.clear()
        w = max(self.winfo_width(), 440)
        h = max(self.winfo_height(), 165)

        if not self.series:
            self.create_text(w / 2, h / 2, text="אין נתונים להצגת גרף", fill=COLORS["muted"], font=(FONT, 11))
            return

        pad_l, pad_r, pad_t, pad_b = 60, 18, 34, 30
        plot_w = max(w - pad_l - pad_r, 120)
        plot_h = max(h - pad_t - pad_b, 60)

        # Header & refined legend
        self.create_text(w - 10, 14, text="הכנסות מול הוצאות לפי חודשים (₪)", anchor="e",
                         fill=COLORS["text"], font=(FONT, 10, "bold"))
        self.create_oval(pad_l, 9, pad_l + 9, 18, fill=COLORS["chart_income"], outline="")
        self.create_text(pad_l + 14, 13, text="הכנסות", anchor="w", fill=COLORS["muted"], font=(FONT, 9, "bold"))
        self.create_oval(pad_l + 70, 9, pad_l + 79, 18, fill=COLORS["chart_expense"], outline="")
        self.create_text(pad_l + 84, 13, text="הוצאות", anchor="w", fill=COLORS["muted"], font=(FONT, 9, "bold"))

        max_val = max((max(item["income"], item["expense"]) for item in self.series), default=10000)
        max_val = max(max_val, 10000)

        # Subtle dashed horizontal gridlines
        for step in range(5):
            y = pad_t + plot_h - (plot_h * step / 4)
            dash = () if step == 0 else (3, 3)
            color = COLORS["border_strong"] if step == 0 else COLORS["border"]
            self.create_line(pad_l, y, w - pad_r, y, fill=color, width=1, dash=dash)
            val_nis = int(max_val * step / 4 / 100)
            self.create_text(pad_l - 8, y, text=f"{val_nis:,}", anchor="e", fill=COLORS["muted"], font=(FONT, 8))

        n = len(self.series)
        group_w = plot_w / n
        bar_w = max(7, min(20, group_w * 0.32))
        y_base = pad_t + plot_h

        for i, item in enumerate(self.series):
            gx0 = pad_l + i * group_w
            gx1 = gx0 + group_w
            cx = (gx0 + gx1) / 2
            inc_h = (item["income"] / max_val) * plot_h
            exp_h = (item["expense"] / max_val) * plot_h

            # Subtle hover highlight column
            if self._hover_idx == i:
                self.create_rectangle(gx0 + 2, pad_t, gx1 - 2, y_base, fill="#F1F5F9", outline="", tags="hover")

            inc_fill = COLORS["chart_income_hover"] if self._hover_idx == i else COLORS["chart_income"]
            exp_fill = COLORS["chart_expense_hover"] if self._hover_idx == i else COLORS["chart_expense"]

            if inc_h > 0:
                self.create_rectangle(cx - bar_w - 2, y_base - inc_h, cx - 2, y_base, fill=inc_fill, outline="")
            if exp_h > 0:
                self.create_rectangle(cx + 2, y_base - exp_h, cx + bar_w + 2, y_base, fill=exp_fill, outline="")

            lbl_color = COLORS["text"] if self._hover_idx == i else COLORS["muted"]
            lbl_font = (FONT, 8, "bold") if self._hover_idx == i else (FONT, 8)
            self.create_text(cx, y_base + 14, text=item["label"], fill=lbl_color, font=lbl_font)
            self._bars.append((gx0, gx1, item))

    def _on_leave(self, _event=None):
        self._hover_idx = None
        self.redraw()

    def _on_motion(self, event):
        found = None
        for i, (x0, x1, _item) in enumerate(self._bars):
            if x0 <= event.x <= x1:
                found = i
                break
        if found != self._hover_idx:
            self._hover_idx = found
            self.redraw()
        self.delete("tooltip")
        if found is not None:
            item = self._bars[found][2]
            text = (
                f"{item['label']}   •   הכנסות: {fmt_money(item['income'])}   "
                f"•   הוצאות: {fmt_money(item['expense'])}   •   נטו: {fmt_money(item['net'])}"
            )
            w = max(self.winfo_width(), 440)
            tx = min(max(event.x, 210), w - 210)
            ty = max(event.y - 26, 40)
            tid = self.create_text(tx, ty, text=text, fill="#FFFFFF", font=(FONT, 8, "bold"), tags="tooltip")
            bbox = self.bbox(tid)
            if bbox:
                rect = self.create_rectangle(
                    bbox[0] - 10, bbox[1] - 5, bbox[2] + 10, bbox[3] + 5,
                    fill=COLORS["nav"], outline=COLORS["nav_indicator"], width=1, tags="tooltip",
                )
                self.tag_lower(rect, tid)


class Dialog(tk.Toplevel):
    """Polished modal RTL form dialog with header bar, hairline footer, and file/folder pickers."""

    def __init__(self, app, title, fields, commit, footer=None, submit_text="שמירה"):
        super().__init__(app)
        self.app = app
        self.title(title)
        self.transient(app)
        self.grab_set()
        self.resizable(False, False)
        self.configure(bg=COLORS["surface"])
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.values = {}

        # Clean header banner
        hdr = tk.Frame(self, bg=COLORS["nav"], padx=22, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text=title, bg=COLORS["nav"], fg="#FFFFFF", font=(FONT, 12, "bold"), anchor="e").pack(fill="x")

        panel = tk.Frame(self, bg=COLORS["surface"], padx=22, pady=18)
        panel.pack(fill="both", expand=True)
        self.panel = panel

        for index, (key, label, default, options) in enumerate(fields):
            var = tk.StringVar(value=default)
            self.values[key] = var
            tk.Label(panel, text=label, bg=COLORS["surface"], fg=COLORS["text_secondary"], font=(FONT, 9, "bold"), anchor="e").grid(
                row=index, column=2, padx=(14, 0), pady=6, sticky="e"
            )
            if isinstance(options, (list, tuple)):
                field = ttk.Combobox(panel, textvariable=var, values=options, state="readonly", justify="right", width=36)
            elif options == "folder":
                field = ttk.Entry(panel, textvariable=var, justify="right", width=38)
                ActionButton(panel, "עיון...", lambda v=var: self.choose_folder(v), variant="soft", padx=10, pady=3).grid(row=index, column=0, padx=(0, 8))
            elif options == "file":
                field = ttk.Entry(panel, textvariable=var, justify="right", width=38)
                ActionButton(panel, "בחר קובץ...", lambda v=var: self.choose_file(v), variant="soft", padx=10, pady=3).grid(row=index, column=0, padx=(0, 8))
            else:
                field = ttk.Entry(panel, textvariable=var, justify="right", width=38, show="●" if options == "password" else "")
            field.grid(row=index, column=1, sticky="ew", pady=6)
            if index == 0:
                field.focus_set()

        self.original = self.get()

        # Subtle hairline divider + clean footer
        tk.Frame(self, bg=COLORS["border"], height=1).pack(fill="x")
        tail = tk.Frame(self, bg=COLORS["surface_alt"], padx=22, pady=12)
        tail.pack(fill="x")
        if footer:
            footer(self, tail)
        self.button = ActionButton(tail, submit_text, lambda: self.submit(commit), variant="primary", padx=18, pady=7)
        self.button.pack(side="right", padx=(6, 0))
        ActionButton(tail, "סגירה", self.cancel, variant="secondary", padx=14, pady=7).pack(side="right", padx=(6, 0))
        self.bind("<Escape>", lambda _: self.cancel())

    def get(self):
        return {key: var.get() for key, var in self.values.items()}

    def choose_folder(self, var):
        chosen = filedialog.askdirectory(parent=self)
        if chosen:
            var.set(chosen)

    def choose_file(self, var):
        chosen = filedialog.askopenfilename(
            parent=self,
            filetypes=[("מסמכים ותמונות", "*.pdf;*.jpg;*.jpeg;*.png;*.docx;*.xlsx"), ("כל הקבצים", "*.*")],
        )
        if chosen:
            var.set(chosen)

    def submit(self, commit):
        self.button.configure(state="disabled")
        try:
            if commit(self.get()) is not False:
                self.destroy()
        except (Problem, sqlite3.Error, OSError, ValueError) as error:
            self.app.error(error, self)
        finally:
            if self.winfo_exists():
                self.button.configure(state="normal")

    def cancel(self):
        if self.get() == self.original or messagebox.askyesno("שינויים שלא נשמרו", "לסגור בלי לשמור?", parent=self):
            self.destroy()


class AttachmentsDialog(tk.Toplevel):
    """Manage invoices & receipts attached to a financial movement."""

    def __init__(self, app, entry_id, can_edit=True):
        super().__init__(app)
        self.app = app
        self.entry_id = entry_id
        self.can_edit = can_edit
        self.title(f"חשבוניות וקבלות · תנועה #{entry_id}")
        self.geometry("660x420")
        self.transient(app)
        self.grab_set()
        self.configure(bg=COLORS["background"])

        hdr = tk.Frame(self, bg=COLORS["nav"], padx=18, pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"📎 קבצים מצורפים לתנועה #{entry_id}", bg=COLORS["nav"], fg="#FFFFFF", font=(FONT, 12, "bold"), anchor="e").pack(fill="x")

        panel = ttk.Frame(self, padding=16)
        panel.pack(fill="both", expand=True)

        bar = ttk.Frame(panel)
        bar.pack(fill="x", pady=(0, 10))
        if can_edit:
            ActionButton(bar, "+ צירוף קובץ...", self.add_files, variant="primary").pack(side="right", padx=(6, 0))
            ActionButton(bar, "הסרת קובץ", self.delete_selected, variant="danger").pack(side="right", padx=(6, 0))
        ActionButton(bar, "פתיחת קובץ", self.open_selected, variant="soft").pack(side="right", padx=(6, 0))
        ActionButton(bar, "סגירה", self.destroy, variant="secondary").pack(side="left")

        self.tree = app.table(("שם קובץ", "גודל", "הועלה ע״י", "תאריך העלאה"), height=9, parent=panel)
        self.tree.bind("<Double-1>", lambda _: self.open_selected())
        self.reload()
        self.bind("<Escape>", lambda _: self.destroy())

    def reload(self):
        rows = []
        for att in self.app.store.list_attachments(entry_id=self.entry_id):
            kb = max(1, (att["size_bytes"] + 1023) // 1024)
            rows.append((att["id"], (att["filename"], f"{kb:,} KB", att["uploaded_by"] or "—", fmt_date(att["uploaded_at"][:10]))))
        self.app.fill(self.tree, rows)

    def add_files(self):
        paths = filedialog.askopenfilenames(
            parent=self,
            title="בחירת חשבוניות או קבלות לצירוף",
            filetypes=[("מסמכים ותמונות", "*.pdf;*.jpg;*.jpeg;*.png;*.docx;*.xlsx"), ("כל הקבצים", "*.*")],
        )
        if not paths:
            return
        try:
            for p in paths:
                self.app.store.add_attachment(self.entry_id, p, actor=self.app.user)
            self.reload()
            self.app.refresh("הקובץ צורף בהצלחה")
        except (Problem, OSError, sqlite3.Error) as exc:
            self.app.error(exc, self)

    def open_selected(self):
        try:
            att_id = self.app.selection(self.tree)
            path, _ = self.app.store.attachment_path(att_id)
            os.startfile(str(path))
        except (Problem, OSError) as exc:
            self.app.error(exc, self)

    def delete_selected(self):
        try:
            att_id = self.app.selection(self.tree)
            if not messagebox.askyesno("הסרת קובץ", "להסיר את הקובץ המצורף מהתנועה?", parent=self):
                return
            self.app.store.delete_attachment(att_id, actor=self.app.user)
            self.reload()
            self.app.refresh("הקובץ הוסר")
        except (Problem, OSError, sqlite3.Error) as exc:
            self.app.error(exc, self)
