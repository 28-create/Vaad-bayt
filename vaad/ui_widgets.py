"""Reusable Hebrew RTL Tkinter widgets: KPI cards, interactive chart, dialogs, and sorting."""

import os
import re
import sqlite3
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .reports import fmt_date, fmt_money
from .store import Problem
from .theme import COLORS, FONT

_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


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


class MetricCard(tk.Frame):
    """Modern clickable KPI card with RTL right accent border and hover highlight."""

    def __init__(self, parent, title, value, subtitle="", accent=COLORS["action"], command=None):
        super().__init__(parent, bg=COLORS["surface"], highlightbackground=COLORS["border"], highlightthickness=1)
        self._command = command
        self._base_bg = COLORS["surface"]
        self._hover_bg = COLORS["surface_alt"]

        accent_bar = tk.Frame(self, bg=accent, width=5)
        accent_bar.pack(side="right", fill="y")

        body = tk.Frame(self, bg=self._base_bg, padx=12, pady=10)
        body.pack(side="right", fill="both", expand=True)

        lbl_title = tk.Label(body, text=title, bg=self._base_bg, fg=COLORS["muted"], font=(FONT, 9, "bold"), anchor="e")
        lbl_title.pack(fill="x")

        lbl_val = tk.Label(body, text=value, bg=self._base_bg, fg=COLORS["text"], font=(FONT, 15, "bold"), anchor="e")
        lbl_val.pack(fill="x", pady=(2, 0))

        self._widgets = [self, body, lbl_title, lbl_val]
        if subtitle:
            lbl_sub = tk.Label(body, text=subtitle, bg=self._base_bg, fg=accent, font=(FONT, 8), anchor="e")
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
    """Interactive Canvas grouped bar chart displaying monthly income vs expenses."""

    def __init__(self, parent, series, height=195):
        super().__init__(
            parent,
            height=height,
            bg=COLORS["surface"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
            bd=0,
        )
        self.series = series
        self._bars = []
        self._tooltip_id = None
        self.bind("<Configure>", lambda _: self.redraw())
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda _: self._clear_tooltip())

    def redraw(self):
        self.delete("all")
        self._bars.clear()
        w = max(self.winfo_width(), 420)
        h = max(self.winfo_height(), 170)

        if not self.series:
            self.create_text(w / 2, h / 2, text="אין נתונים להצגת גרף", fill=COLORS["muted"], font=(FONT, 11))
            return

        pad_l, pad_r, pad_t, pad_b = 58, 18, 28, 30
        plot_w = max(w - pad_l - pad_r, 100)
        plot_h = max(h - pad_t - pad_b, 60)

        # Title & legend
        self.create_text(w - 14, 13, text="הכנסות מול הוצאות לפי חודשים (₪)", anchor="e",
                         fill=COLORS["text"], font=(FONT, 10, "bold"))
        self.create_rectangle(pad_l, 8, pad_l + 10, 18, fill="#16A34A", outline="")
        self.create_text(pad_l + 15, 13, text="הכנסות", anchor="w", fill=COLORS["muted"], font=(FONT, 9))
        self.create_rectangle(pad_l + 68, 8, pad_l + 78, 18, fill="#DC2626", outline="")
        self.create_text(pad_l + 83, 13, text="הוצאות", anchor="w", fill=COLORS["muted"], font=(FONT, 9))

        max_val = max((max(item["income"], item["expense"]) for item in self.series), default=10000)
        max_val = max(max_val, 10000)

        # Horizontal grid
        for step in range(5):
            y = pad_t + plot_h - (plot_h * step / 4)
            self.create_line(pad_l, y, w - pad_r, y, fill="#E2E8F0", width=1)
            val_nis = int(max_val * step / 4 / 100)
            self.create_text(pad_l - 8, y, text=f"{val_nis:,}", anchor="e", fill=COLORS["muted"], font=(FONT, 8))

        n = len(self.series)
        group_w = plot_w / n
        bar_w = max(6, min(20, group_w * 0.34))

        for i, item in enumerate(self.series):
            cx = pad_l + i * group_w + group_w / 2
            inc_h = (item["income"] / max_val) * plot_h
            exp_h = (item["expense"] / max_val) * plot_h
            y_base = pad_t + plot_h

            self.create_rectangle(cx - bar_w - 1, y_base - inc_h, cx - 1, y_base, fill="#16A34A", outline="")
            self.create_rectangle(cx + 1, y_base - exp_h, cx + bar_w + 1, y_base, fill="#DC2626", outline="")
            self.create_text(cx, y_base + 14, text=item["label"], fill=COLORS["muted"], font=(FONT, 8))
            self._bars.append((pad_l + i * group_w, pad_l + (i + 1) * group_w, item))

    def _clear_tooltip(self):
        self.delete("tooltip")

    def _on_motion(self, event):
        self._clear_tooltip()
        for x0, x1, item in self._bars:
            if x0 <= event.x <= x1:
                text = (
                    f"{item['label']}   |   הכנסות: {fmt_money(item['income'])}   "
                    f"|   הוצאות: {fmt_money(item['expense'])}   |   נטו: {fmt_money(item['net'])}"
                )
                w = max(self.winfo_width(), 420)
                tx = min(max(event.x, 190), w - 190)
                ty = max(event.y - 26, 36)
                tid = self.create_text(tx, ty, text=text, fill="white", font=(FONT, 8, "bold"), tags="tooltip")
                bbox = self.bbox(tid)
                if bbox:
                    rect = self.create_rectangle(
                        bbox[0] - 8, bbox[1] - 4, bbox[2] + 8, bbox[3] + 4,
                        fill="#0F172A", outline="#334155", tags="tooltip",
                    )
                    self.tag_lower(rect, tid)
                break


class Dialog(tk.Toplevel):
    """Modal RTL form dialog supporting text, password, combobox, folder, and file pickers."""

    def __init__(self, app, title, fields, commit, footer=None, submit_text="שמירה"):
        super().__init__(app)
        self.app = app
        self.title(title)
        self.transient(app)
        self.grab_set()
        self.resizable(False, False)
        self.configure(bg=COLORS["background"])
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.values = {}

        panel = ttk.Frame(self, padding=22)
        panel.pack(fill="both", expand=True)
        self.panel = panel

        for index, (key, label, default, options) in enumerate(fields):
            var = tk.StringVar(value=default)
            self.values[key] = var
            ttk.Label(panel, text=label, anchor="e").grid(row=index, column=2, padx=(14, 0), pady=5, sticky="e")
            if isinstance(options, (list, tuple)):
                field = ttk.Combobox(panel, textvariable=var, values=options, state="readonly", justify="right", width=36)
            elif options == "folder":
                field = ttk.Entry(panel, textvariable=var, justify="right", width=38)
                ttk.Button(panel, text="עיון...", command=lambda v=var: self.choose_folder(v)).grid(row=index, column=0, padx=(0, 8))
            elif options == "file":
                field = ttk.Entry(panel, textvariable=var, justify="right", width=38)
                ttk.Button(panel, text="בחר קובץ...", command=lambda v=var: self.choose_file(v)).grid(row=index, column=0, padx=(0, 8))
            else:
                field = ttk.Entry(panel, textvariable=var, justify="right", width=38, show="●" if options == "password" else "")
            field.grid(row=index, column=1, sticky="ew", pady=5)
            if index == 0:
                field.focus_set()

        self.original = self.get()
        tail = ttk.Frame(panel)
        tail.grid(row=len(fields), column=0, columnspan=3, sticky="ew", pady=(16, 0))
        if footer:
            footer(self, tail)
        self.button = ttk.Button(tail, text=submit_text, style="Primary.TButton", command=lambda: self.submit(commit))
        self.button.pack(side="right", padx=5)
        ttk.Button(tail, text="סגירה", command=self.cancel).pack(side="right", padx=5)
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
        self.button.state(["disabled"])
        try:
            if commit(self.get()) is not False:
                self.destroy()
        except (Problem, sqlite3.Error, OSError, ValueError) as error:
            self.app.error(error, self)
        finally:
            if self.winfo_exists():
                self.button.state(["!disabled"])

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
        self.geometry("620x380")
        self.transient(app)
        self.grab_set()
        self.configure(bg=COLORS["background"])

        panel = ttk.Frame(self, padding=16)
        panel.pack(fill="both", expand=True)

        ttk.Label(panel, text=f"קבצים מצורפים לתנועה #{entry_id}", font=(FONT, 13, "bold"), anchor="e").pack(fill="x", pady=(0, 10))

        bar = ttk.Frame(panel)
        bar.pack(fill="x", pady=(0, 8))
        if can_edit:
            ttk.Button(bar, text="צירוף קובץ...", style="Primary.TButton", command=self.add_files).pack(side="right", padx=(5, 0))
            ttk.Button(bar, text="הסרת קובץ", command=self.delete_selected).pack(side="right", padx=(5, 0))
        ttk.Button(bar, text="פתיחת קובץ", command=self.open_selected).pack(side="right", padx=(5, 0))
        ttk.Button(bar, text="סגירה", command=self.destroy).pack(side="left")

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
