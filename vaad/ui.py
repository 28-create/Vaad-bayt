from datetime import date
from pathlib import Path
import os
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from uuid import uuid4

from .store import Store, Problem, money, valid_day
from .ledger import Ledger, LABELS, METHODS


def today():
    return date.today().isoformat()


def date_text(value):
    return "/".join(reversed(value.split("-"))) if value else ""


def iso(value):
    return "-".join(reversed(value.strip().split("/"))) if "/" in value else value.strip()


def amount(value):
    sign = "−" if value < 0 else ""
    whole, remainder = divmod(abs(value),100)
    return f"\u200e{sign}{whole:,}.{remainder:02d} ₪\u200e"


def number(value):
    sign = "-" if value < 0 else ""
    whole, remainder = divmod(abs(value),100)
    return f"{sign}{whole}.{remainder:02d}"


def unit_name(unit):
    apartment = unit["apartment"]
    label = apartment if not apartment.startswith("@") else "טרם זוהתה"
    return f'{unit["building"]} / {label} {unit["subunit"]}'.strip()


class Dialog(tk.Toplevel):
    def __init__(self, app, title, fields, commit, footer=None):
        super().__init__(app)
        self.app = app
        self.title(title)
        self.transient(app)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.values = {}
        panel = ttk.Frame(self, padding=22)
        panel.pack(fill="both", expand=True)
        self.panel = panel
        for index,(key,label,default,options) in enumerate(fields):
            var = tk.StringVar(value=default)
            self.values[key] = var
            ttk.Label(panel,text=label,anchor="e").grid(row=index,column=2,padx=(14,0),pady=5,sticky="e")
            if isinstance(options,(list,tuple)):
                field = ttk.Combobox(panel,textvariable=var,values=options,state="readonly",justify="right",width=34)
            elif options == "folder":
                field = ttk.Entry(panel,textvariable=var,justify="right",width=36)
                ttk.Button(panel,text="עיון",command=lambda v=var: self.folder(v)).grid(row=index,column=0,padx=(0,8))
            else:
                field = ttk.Entry(panel,textvariable=var,justify="right",width=36,show="●" if options=="password" else "")
            field.grid(row=index,column=1,sticky="ew",pady=5)
            if index == 0:
                field.focus_set()
        self.original = self.get()
        tail = ttk.Frame(panel)
        tail.grid(row=len(fields),column=0,columnspan=3,sticky="ew",pady=(16,0))
        if footer:
            footer(self,tail)
        self.button = ttk.Button(tail,text="שמירה",style="Primary.TButton",command=lambda: self.submit(commit))
        self.button.pack(side="right",padx=5)
        ttk.Button(tail,text="סגירה",command=self.cancel).pack(side="right",padx=5)
        self.bind("<Escape>",lambda _: self.cancel())

    def get(self):
        return {key:var.get() for key,var in self.values.items()}

    def folder(self,var):
        chosen = filedialog.askdirectory(parent=self)
        if chosen:
            var.set(chosen)

    def submit(self, commit):
        self.button.state(["disabled"])
        try:
            if commit(self.get()) is not False:
                self.destroy()
        except (Problem, sqlite3.Error, OSError, ValueError) as error:
            self.app.error(error,self)
        finally:
            if self.winfo_exists():
                self.button.state(["!disabled"])

    def cancel(self):
        if self.get() == self.original or messagebox.askyesno("שינויים שלא נשמרו","לסגור בלי לשמור?",parent=self):
            self.destroy()


class App(tk.Tk):
    PAGES = ("לוח בקרה","דיירים ודירות","גבייה ותשלומים","תנועות כספיות","דוחות","הגדרות")

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.ledger = Ledger(store)
        self.title("ועד הבית  |  שחריי 14 · 16 · 18")
        self.geometry("1210x760")
        self.minsize(880,620)
        self.configure(bg="#edf1f5")
        self.option_add("*font", ("Segoe UI",10))
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame",background="#edf1f5")
        style.configure("TLabel",background="#edf1f5",foreground="#243650",padding=2)
        style.configure("TButton",padding=(12,7),background="#ffffff",foreground="#243650")
        style.configure("Primary.TButton",background="#203b59",foreground="#ffffff")
        style.map("Primary.TButton",background=[("active","#325676")])
        style.configure("Treeview",rowheight=31,background="#ffffff",fieldbackground="#ffffff",foreground="#243650",borderwidth=0)
        style.configure("Treeview.Heading",background="#e1e8f0",foreground="#243650",padding=(6,8),font=("Segoe UI",10,"bold"))
        style.map("Treeview",background=[("selected","#345b7c")])
        self.status = tk.StringVar()
        self.period = today()[:7]
        self.logged = False
        self.after(100,self.lock)
        self.after(60000,self.tick)

    def tick(self):
        try:
            if self.logged:
                self.ledger.generate()
        except (Problem, sqlite3.Error) as exc:
            self.error(exc)
        finally:
            self.after(60000,self.tick)

    def error(self, exc, parent=None):
        if isinstance(exc,Problem):
            msg = str(exc)
        elif isinstance(exc,sqlite3.IntegrityError):
            msg = "הפרטים כפולים או אינם עומדים בכללי הנתונים"
        else:
            msg = "לא ניתן להשלים את הפעולה. יש לבדוק את הערכים או את קובץ הנתונים"
        messagebox.showerror("הפעולה נכשלה",msg,parent=parent or self)

    def report_callback_exception(self, typ, value, traceback):
        self.error(value)

    def reset(self):
        for child in self.winfo_children():
            child.destroy()

    def lock(self):
        self.logged = False
        self.reset()
        panel = ttk.Frame(self,padding=35)
        panel.place(relx=.5,rely=.42,anchor="center")
        ttk.Label(panel,text="ניהול ועד הבית",font=("Segoe UI",30,"bold")).pack()
        ttk.Label(panel,text=self.store.get("complex","שחריי 14 · 16 · 18")).pack(pady=(0,22))
        if self.store.get("start"):
            var = tk.StringVar()
            field = ttk.Entry(panel,textvariable=var,show="●",justify="right",width=28)
            field.pack(pady=6)
            def login():
                if not self.store.authenticate(var.get()):
                    var.set("")
                    raise Problem("הסיסמה אינה נכונה")
                self.enter()
            ttk.Button(panel,text="כניסה למערכת",style="Primary.TButton",command=login).pack(fill="x")
            field.bind("<Return>",lambda _: login())
            field.focus_set()
        else:
            ttk.Button(panel,text="הגדרת מערכת",style="Primary.TButton",command=self.setup).pack(fill="x")
            ttk.Button(panel,text="שחזור ממחשב קודם",command=self.restore).pack(fill="x",pady=8)

    def setup(self):
        defaults = str(self.store.path.parent / "backups")
        fields = [
            ("name","שם ועד הבית","ועד הבית",None),("complex","שם המתחם","שחריי 14, 16, 18",None),
            ("start","תאריך תחילת הניהול",date_text(today()),None),("initial","יתרת קופה בשקלים","0",None),
            ("password","סיסמת מנהל","", "password"),("backup","תיקיית גיבוי",defaults,"folder"),
            ("rate","תעריף חודשי בשקלים","100",None),("split","מספר הדירה המחולקת בבניין 16","",None),
        ]
        def save(v):
            self.store.setup(v["name"],v["complex"],iso(v["start"]),money(v["initial"]),v["password"],
                             v["backup"],money(v["rate"]),v["split"])
            self.after_idle(self.enter)
        Dialog(self,"הגדרת מערכת",fields,save)

    def enter(self):
        self.ledger.generate()
        self.logged = True
        self.reset()
        sidebar = tk.Frame(self,bg="#18314c",width=196)
        sidebar.pack(side="right",fill="y")
        sidebar.pack_propagate(False)
        tk.Label(sidebar,text="ועד הבית",bg="#18314c",fg="white",font=("Segoe UI",22,"bold"),anchor="e").pack(fill="x",padx=18,pady=(26,3))
        tk.Label(sidebar,text=self.store.get("complex"),bg="#18314c",fg="#bdcddd",anchor="e",wraplength=165,justify="right").pack(fill="x",padx=18,pady=(0,24))
        self.nav = []
        for i,name in enumerate(self.PAGES):
            button = tk.Button(sidebar,text=name,anchor="e",padx=15,pady=9,relief="flat",borderwidth=0,
                               bg="#18314c",fg="white",activebackground="#345674",activeforeground="white",
                               command=lambda idx=i: self.show(idx))
            button.pack(fill="x",padx=9,pady=2)
            self.nav.append(button)
        tk.Button(sidebar,text="נעילת המערכת",relief="flat",bg="#18314c",fg="#d4dfed",command=self.lock).pack(side="bottom",fill="x",pady=16)
        self.main = ttk.Frame(self,padding=(20,14))
        self.main.pack(side="right",fill="both",expand=True)
        self.show(0)

    def show(self,index, mode=None):
        self.page,self.mode = index,mode
        for i,button in enumerate(self.nav):
            button.configure(bg="#345674" if i==index else "#18314c")
        for child in self.main.winfo_children():
            child.destroy()
        ttk.Label(self.main,text=self.PAGES[index],font=("Segoe UI",24,"bold"),anchor="e").pack(fill="x",pady=(0,11))
        ttk.Label(self.main,textvariable=self.status,anchor="e",foreground="#27634d").pack(side="bottom",fill="x")
        (self.dashboard,self.units,self.collection,self.movements,self.reports,self.settings)[index]()

    def refresh(self, message="הפעולה נשמרה"):
        self.status.set(message)
        self.show(self.page,self.mode)

    def bar(self,parent=None):
        bar = ttk.Frame(parent or self.main)
        bar.pack(fill="x",pady=(2,9))
        return bar

    def button(self,bar,text,command,primary=False):
        ttk.Button(bar,text=text,command=command,style="Primary.TButton" if primary else "TButton").pack(side="right",padx=(5,0))

    def input(self,bar,label,value="",options=None,width=14):
        ttk.Label(bar,text=label).pack(side="right",padx=(4,8))
        var = tk.StringVar(value=value)
        if options:
            field = ttk.Combobox(bar,textvariable=var,values=options,state="readonly",justify="right",width=width)
        else:
            field = ttk.Entry(bar,textvariable=var,justify="right",width=width)
        field.pack(side="right")
        return var

    def table(self,headers,rows=(),height=12,parent=None):
        parent = parent or self.main
        box = ttk.Frame(parent)
        box.pack(fill="both",expand=True,pady=(0,7))
        tree = ttk.Treeview(box,columns=list(range(len(headers))),show="headings",height=height)
        scroll = ttk.Scrollbar(box,orient="vertical",command=tree.yview)
        horiz = ttk.Scrollbar(box,orient="horizontal",command=tree.xview)
        tree.configure(yscrollcommand=scroll.set,xscrollcommand=horiz.set)
        horiz.pack(side="bottom",fill="x")
        scroll.pack(side="left",fill="y")
        tree.pack(side="right",fill="both",expand=True)
        tree.tag_configure("alternate",background="#f5f8fb")
        for index,label in enumerate(reversed(headers)):
            tree.heading(index,text=label,anchor="e")
            tree.column(index,width=max(90,len(label)*9+16),minwidth=65,anchor="e")
        self.fill(tree,rows)
        return tree

    def fill(self,tree,rows):
        tree.delete(*tree.get_children())
        for i,(key,values) in enumerate(rows):
            tree.insert("","end",iid=str(key),values=list(reversed(values)),tags=("alternate",) if i%2 else ())
        if not tree.get_children():
            tree.insert("","end",iid="empty",values=("","") if not tree["columns"] else [""]*(len(tree["columns"])-1)+["אין נתונים להצגה"])

    def selection(self,tree):
        selected = tree.selection()
        if not selected or selected[0]=="empty":
            raise Problem("יש לבחור שורה בטבלה")
        return int(selected[0])

    def payment(self, unit_id=None):
        units = self.ledger.units()
        choices = {f'{unit_name(u)} · {u["id"]}':u["id"] for u in units}
        selected = next((label for label,id_ in choices.items() if id_==unit_id),next(iter(choices),""))
        due = lambda label: max(0,self.ledger.account(choices[label])["balance"])
        fields = [("unit","יחידת תשלום",selected,list(choices)),("party","שם המשלם","",None),
                  ("amount","סכום בשקלים",number(due(selected)),None),("day","תאריך",date_text(today()),None),
                  ("method","אמצעי תשלום",METHODS[0],METHODS),("reference","אסמכתא","",None),("notes","הערות","",None)]
        token = uuid4().hex
        def footer(dialog,bar):
            result = tk.StringVar()
            ttk.Label(bar,textvariable=result,anchor="e",justify="right").pack(side="bottom",fill="x",pady=8)
            def preview(*_):
                v = dialog.get()
                bal = self.ledger.account(choices[v["unit"]])["balance"]
                try:
                    payment = money(v["amount"])
                except Problem:
                    result.set("")
                    return
                after = bal-payment
                result.set(f"חוב לפני {amount(max(bal,0))}   •   תשלום {amount(payment)}\n"
                           f"חוב אחרי {amount(max(after,0))}   •   זכות אחרי {amount(max(-after,0))}")
            def update(*_):
                dialog.values["amount"].set(number(due(dialog.values["unit"].get())))
            dialog.values["unit"].trace_add("write",update)
            dialog.values["amount"].trace_add("write",preview)
            preview()
        def post(v):
            unit = choices[v["unit"]]
            args = ("payment",money(v["amount"]),iso(v["day"]),v["method"],token)
            kw = dict(unit=unit,party=v["party"],reference=v["reference"],notes=v["notes"])
            try:
                entry = self.ledger.post(*args,**kw)
            except Problem as exc:
                if str(exc)!="נמצא תשלום דומה":
                    raise
                if not messagebox.askyesno("תשלום דומה","נמצא תשלום דומה. האם זהו תשלום נוסף?",parent=self):
                    return False
                entry = self.ledger.post(*args,**kw,allow_duplicate=True)
            self.refresh(f'תשלום {entry} · {v["unit"]} · {v["day"]} · {amount(money(v["amount"]))} · יתרה {amount(self.ledger.account(unit)["balance"])}')
        Dialog(self,"רישום תשלום",fields,post,footer)

    def movement_form(self,kind):
        label = LABELS[kind]
        categories = {r["name"]:r["id"] for r in self.store.rows("SELECT * FROM categories WHERE kind=? AND active=1 ORDER BY name",kind)}
        fields = [("day","תאריך",date_text(today()),None),("amount","סכום בשקלים","",None),
                  ("party","ספק או מקור","",None),("category","קטגוריה",next(iter(categories),""),list(categories)),
                  ("description","תיאור","",None),("method","אמצעי תשלום",METHODS[0],METHODS),
                  ("reference","מספר חשבונית או אסמכתא","",None),("notes","הערות","",None)]
        token = uuid4().hex
        def save(v):
            value = money(v["amount"])
            if kind=="expense" and self.ledger.cash()[0]-value<0 and not messagebox.askyesno(
                "יתרת קופה שלילית","ההוצאה תיצור יתרה שלילית. לשמור בכל זאת?",parent=self
            ):
                return False
            entry = self.ledger.post(kind,value,iso(v["day"]),v["method"],token,category=categories.get(v["category"]),
                                     **{k:v[k] for k in ("party","description","reference","notes")})
            self.refresh(f"הפעולה נשמרה · {entry}")
        Dialog(self,label,fields,save)

    def reversal(self,entry):
        def save(v):
            if not messagebox.askyesno("ביטול פעולה",f"ליצור תנועה הפוכה לפעולה {entry}?",parent=self):
                return False
            self.ledger.reverse(entry,v["reason"],iso(v["day"]))
            self.refresh()
        Dialog(self,"ביטול פעולה",[("reason","סיבת הביטול","",None),("day","תאריך חשבונאי",date_text(today()),None)],save)

    def dashboard(self):
        period = today()[:7]
        report = self.ledger.report(period)
        details = self.ledger.details(period)
        expected = sum(c["due"] for _,c,*_ in details)
        received = sum(c["paid"] for _,c,*_ in details)
        debtors = self.debt_rows()
        metrics = [
            ("יתרת הקופה",self.ledger.cash()[0],lambda: self.show(3)),
            ("הכנסות החודש",report["payment"]+report["income"],lambda: self.show(3,"income")),
            ("הוצאות החודש",-report["expense"],lambda: self.show(3,"expense")),
            ("סך החובות",sum(a["balance"] for _,a in debtors),lambda: self.show(2,"debt")),
            ("גבייה צפויה",expected,lambda: self.show(2,"current")),
            ("גבייה בפועל",received,lambda: self.show(2,"current")),
        ]
        grid = self.bar()
        for index,(label,value,command) in enumerate(metrics):
            column = 2-index%3
            grid.columnconfigure(column,weight=1,uniform="metrics")
            ttk.Button(grid,text=f"{label}\n{amount(value)}",command=command).grid(row=index//3,column=column,sticky="ew",padx=4,pady=4)
        counts = [f'{state} {sum(item[4]==state for item in details)}' for state in ("שולם","שולם חלקית","לא שולם","פטור")]
        summary = "   ·   ".join(counts + [f"נותר לגבות {amount(expected-received)}", f"{received/expected:.0%}" if expected else "—"])
        ttk.Label(self.main,text=summary,anchor="e",wraplength=650,justify="right").pack(fill="x",pady=6)
        bar = self.bar()
        self.button(bar,"רישום תשלום",self.payment,True)
        self.button(bar,"רישום הוצאה",lambda: self.movement_form("expense"))
        self.button(bar,"רישום הכנסה",lambda: self.movement_form("income"))
        self.button(bar,"הצגת חובות",lambda:self.show(2,"debt"))
        ttk.Label(self.main,text="תנועות אחרונות",anchor="e",font=("Segoe UI",12,"bold")).pack(fill="x")
        self.table(("תאריך","פעולה","תיאור","סכום","יתרה"),[
            (r["id"],(date_text(r["day"]),LABELS[r["kind"]],r["description"] or r["party"],amount(r["cash"]),amount(r["balance"])))
            for r in reversed(self.ledger.cash()[1][-5:])
        ],height=4)
        ttk.Label(self.main,text="חובות עיקריים",anchor="e",font=("Segoe UI",12,"bold")).pack(fill="x")
        self.table(("יחידה","דייר","חוב"),[(u["id"],(unit_name(u),u["tenant"] or u["owner"],amount(a["balance"])))
                  for u,a in debtors[:5]],height=4)

    def units(self):
        if isinstance(self.mode,tuple) and self.mode[0]=="unit":
            self.unit_sheet(self.mode[1])
            return
        bar = self.bar()
        query = self.input(bar,"חיפוש",width=20)
        building = self.input(bar,"בניין","הכול",("הכול","14","16","18"),8)
        states = ("הכול","חוב","זכות","מאוזן","פעילה","לא פעילה")
        state = self.input(bar,"מצב","הכול",states,10)
        actions = self.bar()
        self.button(actions,"פתיחת כרטיס יחידה",lambda: self.unit_detail(self.selection(tree)),True)
        tree = self.table(("בניין","דירה","יחידה","בעלים","שוכר","טלפון","תעריף","יתרה","מצב"))
        def load(*_):
            result = []
            for u in self.ledger.units():
                balance = self.ledger.account(u["id"])["balance"]
                flag = state.get()
                flags = (
                    "הכול","חוב" if balance>0 else "זכות" if balance<0 else "מאוזן",
                    "פעילה" if u["active"] else "לא פעילה",
                )
                apartment = u["apartment"] if not u["apartment"].startswith("@") else ""
                searchable = " ".join((str(u["building"]),apartment,u["owner"],u["tenant"],u["phone"])).casefold()
                if flag in flags and building.get() in ("הכול",str(u["building"])) and query.get().strip().casefold() in searchable:
                    result.append((u["id"],(u["building"],apartment or "טרם זוהתה",u["subunit"],u["owner"],
                                            u["tenant"],u["phone"],amount(u["rate"] or 0),amount(balance),flags[2])))
            self.fill(tree,result)
        for variable in (query,building,state):
            variable.trace_add("write",load)
        tree.bind("<Double-1>",lambda event: self.unit_detail(int(tree.identify_row(event.y)))
                  if tree.identify_row(event.y).isdigit() else None)
        load()

    def unit_detail(self,unit):
        self.show(1,("unit",unit))

    def unit_sheet(self,unit):
        row = next(u for u in self.ledger.units() if u["id"]==unit)
        account = self.ledger.account(unit)
        ttk.Label(self.main,text=f'{unit_name(row)}   ·   מזהה {unit}   ·   יתרה {amount(account["balance"])}',
                  anchor="e",font=("Segoe UI",17,"bold")).pack(fill="x",pady=4)
        ttk.Label(self.main,text=f'בעלים {row["owner"] or "—"}   ·   שוכר {row["tenant"] or "—"}   ·   תעריף {amount(row["rate"] or 0)}   ·   מתאריך {date_text(row["effective"])}',
                  anchor="e").pack(fill="x")
        bar = self.bar()
        self.button(bar,"רישום תשלום",lambda: self.payment(unit),True)
        self.button(bar,"פרטי היחידה",lambda: self.edit_unit(row))
        self.button(bar,"שינוי תעריף",lambda: self.change_rate(unit,row["rate"] or 0))
        self.button(bar,"חזרה לרשימה",lambda: self.show(1))
        if not any(entry["kind"]=="opening" for entry in self.ledger.history(unit)):
            def opening(v):
                self.ledger.opening(unit,money(v["amount"]))
                self.refresh()
            self.button(bar,"יתרת פתיחה",lambda: Dialog(self,"יתרת פתיחה",[
                ("amount","חוב חיובי או זכות שלילית בשקלים","0",None)],opening))
        filters = self.bar()
        start = self.input(filters,"מתאריך",width=12)
        end = self.input(filters,"עד תאריך",width=12)
        self.button(filters,"סינון",lambda: load())
        self.button(filters,"השנה",lambda: year())
        tree = self.table(("תאריך","תיאור","חיוב","זיכוי","יתרה","הערות"))
        def year():
            start.set(f"01/01/{date.today().year}")
            end.set(f"31/12/{date.today().year}")
            load()
        def load():
            lo,hi = self.bounds(start.get(),end.get())
            running = 0
            data = []
            for r in self.ledger.history(unit):
                running += r["debit"]
                if r["day"] < lo:
                    continue
                if not data and lo:
                    data.append((0,("", "יתרה קודמת","","",amount(running-r["debit"]),"")))
                if r["day"] <= hi:
                    desc = LABELS[r["kind"]] + (f' · {r["period"]}' if r["period"] else "")
                    if r["original"]:
                        desc += f' · {r["original"]}'
                    data.append((r["id"],(date_text(r["day"]),desc,amount(r["debit"]) if r["debit"]>0 else "",
                                           amount(-r["debit"]) if r["debit"]<0 else "",amount(running),r["notes"])))
            if lo and not data:
                data.append((0,("", "יתרה קודמת","","",amount(running),"")))
            self.fill(tree,data)
        load()

    def edit_unit(self,row):
        keys = ("apartment","owner","tenant","phone","email","notes")
        labels = ("מספר דירה","שם בעלים","שם שוכר","טלפון","דואר אלקטרוני","הערות")
        fields = [(k,label,"" if k=="apartment" and row[k].startswith("@") else row[k],None) for k,label in zip(keys,labels)]
        fields.append(("active","מצב","פעילה" if row["active"] else "לא פעילה",("פעילה","לא פעילה")))
        def save(v):
            if v["tenant"].strip()!=row["tenant"] and self.ledger.account(row["id"])["balance"]>0:
                if not messagebox.askyesno("החלפת דייר","החוב נשאר בכרטיס היחידה. שינוי השם אינו משנה אחריות לתשלום. להמשיך?",parent=self):
                    return False
            self.ledger.unit_update(row["id"],[v[k] for k in keys],v["active"]=="פעילה")
            self.refresh()
        Dialog(self,"פרטי היחידה",fields,save)

    def change_rate(self,unit,current):
        def save(v):
            self.ledger.rate(unit,iso(v["day"]),money(v["amount"]))
            self.refresh()
        Dialog(self,"שינוי תעריף",[("amount","תעריף בשקלים",number(current),None),
                                  ("day","מועד תחולה",date_text(today()),None)],save)

    def debt_rows(self):
        data = [(u,self.ledger.account(u["id"])) for u in self.ledger.units()]
        return sorted(((u,a) for u,a in data if a["balance"]>0),key=lambda item: -item[1]["balance"])

    def debtor_table(self,parent=None):
        parent = parent or self.main
        bar = self.bar(parent)
        sort = self.input(bar,"מיון","סכום",("סכום","שם","בניין","דירה"),10)
        self.button(bar,"רישום תשלום",lambda:self.payment(self.selection(tree)),True)
        ttk.Label(parent,text=f'סך החובות {amount(sum(a["balance"] for _,a in self.debt_rows()))}',anchor="e").pack(fill="x")
        tree = self.table(("יחידה","דייר","חוב כולל","חוב החודש","חוב קודם","וותק בימים"),parent=parent)
        def load(*_):
            data = self.debt_rows()
            keys = {"שם": lambda x:x[0]["tenant"] or x[0]["owner"],
                    "בניין": lambda x:(x[0]["building"],x[0]["slot"]),
                    "דירה": lambda x:x[0]["apartment"]}
            if sort.get() in keys:
                data.sort(key=keys[sort.get()])
            rows = []
            for u,a in data:
                current = a["charges"].get(today()[:7],{}).get("left",0)
                age = (date.today()-date.fromisoformat(a["oldest"])).days if a["oldest"] else 0
                rows.append((u["id"],(unit_name(u),u["tenant"] or u["owner"],amount(a["balance"]),
                                       amount(current),amount(a["balance"]-current),age)))
            self.fill(tree,rows)
        sort.trace_add("write",load)
        load()

    def collection(self):
        if self.mode=="current":
            self.period = today()[:7]
        bar = self.bar()
        self.button(bar,"מעקב חודשי",lambda:self.show(2))
        self.button(bar,"חובות פתוחים",lambda:self.show(2,"debt"))
        self.button(bar,"רישום תשלום",self.payment,True)
        if self.mode=="debt":
            self.debtor_table()
            return
        filters = self.bar()
        month = self.input(filters,"חודש",self.period[5:],tuple(f"{m:02d}" for m in range(1,13)),5)
        year = self.input(filters,"שנה",self.period[:4],width=7)
        self.button(filters,"הצגה",lambda: load())
        self.button(filters,"תשלום ליחידה",lambda:self.payment(self.selection(tree)))
        self.button(filters,"תיקון או פטור",lambda: adjust())
        tree = self.table(("יחידה","חיוב","שולם","נותר","חוב קודם","זכות","מצב"))
        def load():
            self.period = date(int(year.get()),int(month.get()),1).isoformat()[:7]
            self.fill(tree,[(u["id"],(unit_name(u),amount(c["due"]),amount(c["paid"]),amount(c["left"]),
                                      amount(older),amount(credit),status)) for u,c,older,credit,status in self.ledger.details(self.period)])
        def adjust():
            unit = self.selection(tree)
            charge = self.ledger.account(unit)["charges"][self.period]
            def save(v):
                self.ledger.adjust(unit,self.period,money(v["amount"]),v["reason"])
                self.refresh()
            Dialog(self,"תיקון חיוב או פטור",[("amount","סכום חדש בשקלים (0 לפטור)",number(charge["due"]),None),
                                             ("reason","סיבה","",None)],save)
        load()

    def bounds(self,start,end):
        lo = valid_day(iso(start)) if start.strip() else ""
        hi = valid_day(iso(end)) if end.strip() else "9999-12-31"
        if lo > hi:
            raise Problem("תאריך ההתחלה מאוחר מתאריך הסיום")
        return lo,hi

    def movements(self):
        bar = self.bar()
        self.button(bar,"רישום הוצאה",lambda:self.movement_form("expense"),True)
        self.button(bar,"רישום הכנסה",lambda:self.movement_form("income"))
        self.button(bar,"ביטול פעולה",lambda:self.reversal(self.selection(tree)))
        self.button(bar,"פרטי תנועה",lambda:self.movement_info(self.selection(tree)))
        ttk.Label(bar,text=f'יתרת קופה {amount(self.ledger.cash()[0])}',anchor="e").pack(side="left")
        filters = self.bar()
        start = self.input(filters,"מתאריך",f"01/{today()[5:7]}/{today()[:4]}" if self.mode else "",width=11)
        end = self.input(filters,"עד תאריך",date_text(today()) if self.mode else "",width=11)
        kinds = {"הכול":None,"הכנסות":("payment","income"),"הוצאות":("expense",),"תשלומי דיירים":("payment",)}
        kind = self.input(filters,"סוג",{"income":"הכנסות","expense":"הוצאות"}.get(self.mode,"הכול"),tuple(kinds),12)
        self.button(filters,"חודש נוכחי",lambda: preset(False))
        self.button(filters,"שנה נוכחית",lambda: preset(True))
        filters = self.bar()
        methods = ("הכול",)+METHODS
        method = self.input(filters,"אמצעי","הכול",methods,12)
        names = sorted({r["name"] for r in self.store.rows("SELECT name FROM categories")})
        category = self.input(filters,"קטגוריה","הכול",("הכול",*names),12)
        query = self.input(filters,"חיפוש",width=14)
        self.button(filters,"סינון",lambda: load())
        tree = self.table(("תאריך","מספר","סוג","תיאור","קטגוריה","יחידה או צד","אמצעי","הכנסה","הוצאה","יתרה"))
        tree.bind("<Double-1>",lambda event: self.movement_info(int(tree.identify_row(event.y)))
                  if tree.identify_row(event.y).isdigit() else None)
        def preset(year):
            start.set(f"01/{'01' if year else today()[5:7]}/{today()[:4]}")
            end.set(date_text(today()))
            load()
        def load():
            lo,hi = self.bounds(start.get(),end.get())
            units = {u["id"]:unit_name(u) for u in self.ledger.units()}
            entries = []
            for r in reversed(self.ledger.cash()[1]):
                if not lo <= r["day"] <= hi or kinds[kind.get()] and r["base_kind"] not in kinds[kind.get()]:
                    continue
                if method.get() not in ("הכול",r["method"]) or category.get() not in ("הכול",r["category_name"]):
                    continue
                if query.get().casefold().strip() not in " ".join(
                    str(r[k] or "") for k in ("description","party","reference","notes","id","category_name")
                ).casefold() + units.get(r["unit"],"").casefold():
                    continue
                entries.append(self.cash_row(r,units))
            self.fill(tree,entries)
        load()

    def movement_info(self,entry):
        row = next(r for r in self.ledger.cash()[1] if r["id"]==entry)
        reversed_by = self.store.rows("SELECT id FROM entries WHERE original=?",entry)
        lines = [
            f'פעולה {entry} · {LABELS[row["kind"]]}',
            f'תאריך חשבונאי {date_text(row["day"])}',
            f'מועד רישום {row["recorded"]}',
            f'סכום {amount(row["cash"])}',
            f'אסמכתא {row["reference"] or "—"}',
            f'הערות {row["notes"] or "—"}',
        ]
        if row["original"]:
            lines.append(f'פעולת מקור {row["original"]}')
        if reversed_by:
            lines.append(f'בוטלה בפעולה {reversed_by[0]["id"]}')
        messagebox.showinfo("פרטי תנועה","\n".join(lines),parent=self)

    @staticmethod
    def cash_row(row,units):
        inflow = row["base_kind"]!="expense"
        kind = LABELS[row["kind"]]
        if row["original"]:
            kind += f' · {row["original"]}'
        return row["id"],(date_text(row["day"]),row["id"],kind,row["description"],
                          row["category_name"] or "",units.get(row["unit"],row["party"]),row["method"],
                          amount(row["cash"]) if inflow else "",amount(-row["cash"]) if not inflow else "",
                          amount(row["balance"]))

    def reports(self):
        options = ("דוח חודשי","דוח שנתי","חובות פתוחים","הוצאות לפי קטגוריה","תשלומים לפי יחידה","היסטוריית קופה")
        bar = self.bar()
        selected,from_date,to_date = self.mode or (options[0],f"01/{today()[5:7]}/{today()[:4]}",date_text(today()))
        option = self.input(bar,"דוח",selected,options,20)
        start = self.input(bar,"מתאריך",from_date,width=11)
        end = self.input(bar,"עד תאריך",to_date,width=11)
        self.button(bar,"הצגה",lambda:self.show(4,(option.get(),start.get(),end.get())),True)
        lo,hi = self.bounds(from_date,to_date)
        if selected==options[2]:
            self.debtor_table()
            return
        rows = []
        if selected in options[:2]:
            year = (lo or today())[:4]
            period = (lo or today())[:7]
            report = self.ledger.report(period if selected==options[0] else year)
            if selected==options[0]:
                from calendar import monthrange
                last = monthrange(int(period[:4]),int(period[5:]))[1]
                month_end = f"{period}-{last:02d}"
                debts = sum(max(0,self.ledger.account(u["id"],month_end)["balance"]) for u in self.ledger.units())
                headers = ("פריט","סכום")
                labels = [
                    ("יתרת פתיחה",report["initial"]),("חיובים חודשיים",report["charges"]),
                    ("תשלומי דיירים",report["payment"]),("הכנסות אחרות",report["income"]),
                    ("סך הכנסות",report["payment"]+report["income"]),("סך הוצאות",-report["expense"]),
                    ("יתרת סיום",report["final"]),("חובות לסוף החודש",debts),
                ]
                rows = [(i,(label,amount(value))) for i,(label,value) in enumerate(labels)]
            else:
                headers = ("תקופה","הכנסות","הוצאות","תוצאה","יתרת פתיחה","יתרת סיום")
                def values(label,r):
                    return (label,amount(r["payment"]+r["income"]),amount(-r["expense"]),
                            amount(r["final"]-r["initial"]),amount(r["initial"]),amount(r["final"]))
                rows = [(m,values(f"{m:02d}/{year}",self.ledger.report(f"{year}-{m:02d}"))) for m in range(1,13)]
                rows.append((13,values("סך שנתי",report)))
        else:
            entries = [r for r in self.ledger.cash()[1] if lo<=r["day"]<=hi]
            units = {u["id"]:unit_name(u) for u in self.ledger.units()}
            if selected==options[3]:
                headers = ("קטגוריה","סך הוצאות")
                totals = {}
                for r in entries:
                    if r["base_kind"]=="expense":
                        label = r["category_name"] or "ללא קטגוריה"
                        totals[label] = totals.get(label,0)-r["cash"]
                rows = [(i,(label,amount(total))) for i,(label,total) in enumerate(sorted(totals.items()))]
            elif selected==options[4]:
                headers = ("יחידה","תאריך","מספר","משלם","אמצעי","סכום")
                payments = sorted((r for r in entries if r["base_kind"]=="payment"),key=lambda r:(r["unit"],r["day"],r["id"]))
                rows = [(r["id"],(units.get(r["unit"],""),date_text(r["day"]),r["id"],r["party"],
                                  r["method"],amount(r["cash"]))) for r in payments]
            else:
                headers = ("תאריך","מספר","סוג","תיאור","קטגוריה","יחידה או צד","אמצעי","הכנסה","הוצאה","יתרה")
                rows = [self.cash_row(r,units) for r in entries]
        actions = self.bar()
        self.button(actions,"ייצוא CSV",lambda: self.export(headers,rows))
        self.button(actions,"תצוגה להדפסה",lambda: self.print_report(selected,headers,rows))
        self.table(headers,rows)

    def export(self,headers,rows):
        import csv
        path = filedialog.asksaveasfilename(parent=self,defaultextension=".csv",filetypes=[("CSV","*.csv")])
        if not path:
            return
        with open(path,"w",encoding="utf-8-sig",newline="") as target:
            writer = csv.writer(target)
            writer.writerow(headers)
            for _,values in rows:
                writer.writerow("'" + value if isinstance(value,str) and value.startswith(("=","+","-","@","\t","\r")) else value
                                for value in values)
        self.status.set("הקובץ נשמר")

    def print_report(self,title,headers,rows):
        from html import escape
        import tempfile
        import webbrowser
        with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",suffix=".html",delete=False) as target:
            table = "<tr>"+"".join(f"<th>{escape(h)}</th>" for h in headers)+"</tr>"
            for _,values in rows:
                table += "<tr>"+"".join(f"<td>{escape(str(value))}</td>" for value in values)+"</tr>"
            target.write(f'<!doctype html><html lang="he" dir="rtl"><meta charset="utf-8"><title>{escape(title)}</title>'
                         '<style>body{font:14px Arial;margin:2rem}table{width:100%;border-collapse:collapse}'
                         'th,td{padding:.5rem;border:1px solid #bfc8d3}@media print{button{display:none}}</style>'
                         f'<h1>{escape(title)}</h1><button onclick="print()">הדפסה</button><table>{table}</table></html>')
        webbrowser.open(Path(target.name).as_uri())

    def settings(self):
        if self.mode=="categories":
            self.category_list()
            return
        sections = [
            ("פרטי ועד הבית", [
                ("עריכת פרטים כלליים",self.general),
                ("תעריף ברירת מחדל",self.default_rate),
                ("ניהול קטגוריות",lambda:self.show(5,"categories")),
            ]),
            ("אבטחה", [("שינוי סיסמה",self.password),("נעילה והתנתקות",self.lock)]),
            ("נתונים וגיבוי", [
                ("יצירת גיבוי",self.backup),("שחזור מגיבוי",self.restore),
                ("תיקיית גיבוי",self.backup_settings),("ייצוא נתונים",self.export_data),
            ]),
        ]
        for title,actions in sections:
            ttk.Label(self.main,text=title,anchor="e",font=("Segoe UI",14,"bold")).pack(fill="x",pady=(8,2))
            bar = self.bar()
            for label, action in actions:
                self.button(bar,label,action)
        last = self.store.get("last_backup")
        stale = not last or (date.today()-date.fromisoformat(last[:10])).days>=7
        msg = f"גיבוי אחרון {date_text(last[:10])}" if last else "טרם נוצר גיבוי"
        ttk.Label(self.main,text=msg+(" · מומלץ ליצור גיבוי" if stale else ""),anchor="e",
                  foreground="#9b521d" if stale else "#27634d").pack(fill="x",pady=6)
        ttk.Label(self.main,text=str(self.store.path),anchor="e",wraplength=650).pack(fill="x")
        ttk.Label(self.main,text="ועד הבית · גרסה 1.0 · SQLite מקומי",anchor="e").pack(fill="x",pady=6)

    def general(self):
        labels = [("name","שם הוועד"),("complex","שם המתחם"),("address","כתובת"),("contact","פרטי קשר")]
        def save(v):
            if not v["name"].strip() or not v["complex"].strip():
                raise Problem("יש להזין שם ועד ומתחם")
            with self.store.write():
                self.store.save(**v)
            self.after_idle(self.enter)
        Dialog(self,"פרטים כלליים",[(k,label,self.store.get(k),None) for k,label in labels],save)

    def default_rate(self):
        def save(v):
            self.ledger.rate(None,iso(v["day"]),money(v["amount"]))
            self.refresh()
        Dialog(self,"תעריף ברירת מחדל לכל היחידות",[
            ("amount","תעריף בשקלים",number(int(self.store.get("rate"))),None),
            ("day","מועד תחולה",date_text(today()),None)],
            save,lambda _,bar:ttk.Label(bar,text="יחידות מפוצלות יחויבו במחצית. הפעולה מחילה תעריף חדש על כל היחידות.",
                                         anchor="e").pack(side="bottom",fill="x"))

    def password(self):
        def save(v):
            if not self.store.authenticate(v["old"]):
                raise Problem("הסיסמה הקיימת אינה נכונה")
            if v["new"]!=v["confirm"]:
                raise Problem("הסיסמאות אינן זהות")
            with self.store.write():
                self.store.set_password(v["new"])
            self.refresh()
        Dialog(self,"שינוי סיסמה",[(k,label,"","password") for k,label in [
            ("old","סיסמה קיימת"),("new","סיסמה חדשה"),("confirm","אימות סיסמה חדשה")]],save)

    def category_list(self):
        bar = self.bar()
        self.button(bar,"קטגוריה חדשה",lambda: edit(None),True)
        self.button(bar,"עריכת קטגוריה",lambda:edit(self.selection(tree)))
        self.button(bar,"חזרה",lambda:self.show(5))
        items = {r["id"]:r for r in self.store.rows("SELECT * FROM categories ORDER BY kind,name")}
        tree = self.table(("שם","סוג","מצב"),[(r["id"],(r["name"],LABELS[r["kind"]],"פעילה" if r["active"] else "לא פעילה"))
                          for r in items.values()])
        def edit(id_):
            row = items[id_] if id_ else None
            def save(v):
                self.ledger.category(row["kind"] if row else kind_lookup[v["kind"]],v["name"],id_,v.get("active")!="לא פעילה")
                self.refresh()
            kind_lookup = {LABELS[k]:k for k in ("expense","income")}
            fields = [("name","שם",row["name"] if row else "",None)]
            if row:
                fields.append(("active","מצב","פעילה" if row["active"] else "לא פעילה",("פעילה","לא פעילה")))
            else:
                fields.append(("kind","סוג",LABELS["expense"],tuple(kind_lookup)))
            Dialog(self,"קטגוריה",fields,save)

    def backup_settings(self):
        def save(v):
            if not v["folder"].strip():
                raise Problem("יש לבחור תיקייה")
            self.store.save(backup=v["folder"])
            self.refresh()
        Dialog(self,"תיקיית גיבוי",[("folder","תיקייה",self.store.get("backup"),"folder")],save)

    def backup(self):
        path = self.store.backup(self.store.get("backup"))
        self.refresh("הגיבוי נשמר")
        messagebox.showinfo("גיבוי נשמר",str(path),parent=self)

    def restore(self):
        source = filedialog.askopenfilename(parent=self,filetypes=[("SQLite","*.sqlite3"),("כל הקבצים","*.*")])
        if not source:
            return
        self.store.inspect_backup(source)
        if not messagebox.askyesno("שחזור מגיבוי","השחזור יחליף את הנתונים ואת סיסמת המערכת. אם קיימים נתונים ייווצר גיבוי לפני ההחלפה. להמשיך?",parent=self):
            return
        self.store.restore(source,self.store.path.parent/"before-restore")
        self.lock()
        messagebox.showinfo("השחזור הושלם","יש להיכנס עם הסיסמה של הגיבוי",parent=self)

    def export_data(self):
        self.export(("מזהה","בניין","דירה","יחידה","בעלים","שוכר","טלפון","דואר אלקטרוני","תעריף בשקלים","יתרה בשקלים"),
                    [(u["id"],(u["id"],u["building"],"" if u["apartment"].startswith("@") else u["apartment"],u["subunit"],
                               u["owner"],u["tenant"],u["phone"],u["email"],number(u["rate"] or 0),
                               number(self.ledger.account(u["id"])["balance"]))) for u in self.ledger.units()])


def startup_error(text):
    root = tk.Tk()
    root.withdraw()
    try:
        messagebox.showerror("ועד הבית",text,parent=root)
    finally:
        root.destroy()


def run():
    import msvcrt

    path = Path(os.environ.get("VAAD_DATA",Path(os.environ["LOCALAPPDATA"])/"VaadBayt")) / "vaad.sqlite3"
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        lock = path.with_suffix(".lock").open("a+b")
    except OSError:
        startup_error("תיקיית הנתונים אינה נגישה")
        return
    with lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            startup_error("המערכת כבר פתוחה עבור תיקיית נתונים זו")
            return
        try:
            store = Store(path)
        except (Problem,sqlite3.Error,OSError):
            startup_error("קובץ הנתונים אינו נגיש או פגום")
            return
        try:
            App(store).mainloop()
        finally:
            store.db.close()

