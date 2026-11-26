"""Professional Hebrew RTL HTML reports, receipts, PDF export, CSV export, and full data archive."""

import csv
from datetime import datetime, timedelta
from html import escape
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import webbrowser
import zipfile

from .excel import write_xlsx
from .store import Problem


def fmt_date(value):
    return "/".join(reversed(value.split("-"))) if value else ""


def fmt_money(value):
    sign = "−" if value < 0 else ""
    whole, remainder = divmod(abs(value), 100)
    return f"\u200e{sign}{whole:,}.{remainder:02d} ₪\u200e"


def fmt_number(value):
    return round(value / 100.0, 2)


def fmt_unit(unit):
    apartment = unit["apartment"]
    label = apartment if not apartment.startswith("@") else "טרם זוהתה"
    return f'{unit["building"]} / {label} {unit["subunit"]}'.strip()


def _base_css():
    return """
    @page { size: A4; margin: 14mm; }
    * { box-sizing: border-box; }
    body {
        font-family: "Segoe UI", Arial, Helvetica, sans-serif;
        color: #0F172A;
        background: #FFFFFF;
        margin: 0;
        padding: 24px 32px;
        direction: rtl;
        font-size: 13px;
        line-height: 1.5;
    }
    .doc-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        border-bottom: 3px solid #1E293B;
        padding-bottom: 12px;
        margin-bottom: 18px;
    }
    .doc-brand h1 { margin: 0 0 4px 0; font-size: 22px; color: #0F172A; }
    .doc-brand .sub { color: #475569; font-size: 13px; }
    .doc-meta { text-align: left; color: #475569; font-size: 12px; }
    .doc-title { font-size: 18px; font-weight: 700; margin: 8px 0 12px 0; color: #1E293B; }
    .kpi-strip {
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
        margin: 0 0 18px 0;
    }
    .kpi-box {
        flex: 1 1 150px;
        border: 1px solid #CBD5E1;
        border-right: 4px solid #2563EB;
        border-radius: 6px;
        padding: 10px 12px;
        background: #F8FAFC;
    }
    .kpi-box .label { font-size: 11px; color: #64748B; }
    .kpi-box .value { font-size: 16px; font-weight: 700; margin-top: 2px; color: #0F172A; }
    table { width: 100%; border-collapse: collapse; margin-top: 8px; }
    th {
        background: #1E293B;
        color: #FFFFFF;
        padding: 8px 10px;
        text-align: right;
        font-weight: 600;
        border: 1px solid #1E293B;
        font-size: 12px;
    }
    td {
        padding: 7px 10px;
        border: 1px solid #CBD5E1;
        text-align: right;
        font-size: 12px;
    }
    tbody tr:nth-child(even) { background: #F8FAFC; }
    tr.total-row td {
        background: #E2E8F0;
        font-weight: 700;
        border-top: 2px solid #334155;
    }
    .toolbar { margin-bottom: 16px; display: flex; gap: 10px; }
    .btn {
        background: #2563EB; color: #fff; border: none; border-radius: 6px;
        padding: 8px 16px; font-size: 13px; cursor: pointer; font-weight: 600;
    }
    .btn:hover { background: #1D4ED8; }
    .chart-wrap { margin: 16px 0 20px 0; text-align: center; }
    .footer {
        margin-top: 26px;
        padding-top: 10px;
        border-top: 1px solid #CBD5E1;
        font-size: 11px;
        color: #64748B;
        display: flex;
        justify-content: space-between;
    }
    .receipt-box {
        border: 2px solid #1E293B;
        border-radius: 8px;
        padding: 20px 24px;
        max-width: 740px;
        margin: 0 auto;
    }
    .receipt-badge {
        display: inline-block;
        padding: 4px 12px;
        background: #DCFCE7;
        color: #166534;
        border-radius: 999px;
        font-weight: 700;
        font-size: 12px;
    }
    .receipt-badge.cancelled { background: #FEE2E2; color: #991B1B; }
    .receipt-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 10px 24px;
        margin: 16px 0;
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 6px;
        padding: 14px 16px;
    }
    .receipt-field .lbl { font-size: 11px; color: #64748B; }
    .receipt-field .val { font-size: 14px; font-weight: 600; }
    .receipt-amount {
        text-align: center;
        background: #EFF6FF;
        border: 1px solid #BFDBFE;
        border-radius: 8px;
        padding: 14px;
        margin: 16px 0;
    }
    .receipt-amount .big { font-size: 26px; font-weight: 800; color: #1E3A8A; }
    .sig-row { display: flex; justify-content: space-between; margin-top: 34px; }
    .sig-line { width: 220px; border-top: 1px solid #475569; padding-top: 6px; text-align: center; font-size: 12px; color: #475569; }
    @media print {
        body { padding: 0; }
        .toolbar { display: none !important; }
    }
    """


def monthly_chart_svg(series):
    """Build a crisp inline SVG bar chart of monthly income vs expenses."""
    if not series:
        return ""
    width, height = 740, 220
    pad_l, pad_r, pad_t, pad_b = 56, 20, 22, 42
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    max_val = max((max(item["income"], item["expense"]) for item in series), default=10000)
    max_val = max(max_val, 10000)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" style="max-width:740px;direction:ltr;">']
    # Grid lines
    for step in range(5):
        y = pad_t + plot_h - (plot_h * step / 4)
        val = int(max_val * step / 4 / 100)
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" stroke="#E2E8F0" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="10" fill="#64748B">{val:,}</text>')

    group_w = plot_w / len(series)
    bar_w = max(8, min(18, group_w * 0.34))
    for i, item in enumerate(series):
        cx = pad_l + i * group_w + group_w / 2
        inc_h = (item["income"] / max_val) * plot_h
        exp_h = (item["expense"] / max_val) * plot_h
        parts.append(f'<rect x="{cx - bar_w - 1:.1f}" y="{pad_t + plot_h - inc_h:.1f}" width="{bar_w:.1f}" height="{inc_h:.1f}" rx="2" fill="#16A34A"/>')
        parts.append(f'<rect x="{cx + 1:.1f}" y="{pad_t + plot_h - exp_h:.1f}" width="{bar_w:.1f}" height="{exp_h:.1f}" rx="2" fill="#DC2626"/>')
        parts.append(f'<text x="{cx:.1f}" y="{height - 20}" text-anchor="middle" font-size="10" fill="#334155">{escape(item["label"])}</text>')

    # Legend
    parts.append('<rect x="520" y="4" width="10" height="10" rx="2" fill="#16A34A"/>')
    parts.append('<text x="536" y="13" font-size="11" fill="#0F172A">הכנסות (₪)</text>')
    parts.append('<rect x="620" y="4" width="10" height="10" rx="2" fill="#DC2626"/>')
    parts.append('<text x="636" y="13" font-size="11" fill="#0F172A">הוצאות (₪)</text>')
    parts.append("</svg>")
    return "".join(parts)


def build_report_html(store, title, headers, rows, subtitle="", kpis=None, totals=None, chart_svg=""):
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    vaad_name = store.get("name", "ועד הבית")
    complex_name = store.get("complex", "")
    address = store.get("address", "")
    contact = store.get("contact", "")
    sub_parts = [p for p in (complex_name, address, contact) if p]

    kpi_html = ""
    if kpis:
        boxes = "".join(
            f'<div class="kpi-box"><div class="label">{escape(lbl)}</div><div class="value">{escape(val)}</div></div>'
            for lbl, val in kpis
        )
        kpi_html = f'<div class="kpi-strip">{boxes}</div>'

    thead = "<tr>" + "".join(f"<th>{escape(str(h))}</th>" for h in headers) + "</tr>"
    tbody = "".join(
        "<tr>" + "".join(f"<td>{escape(str(v))}</td>" for v in values) + "</tr>"
        for _, values in rows
    )
    if totals:
        tbody += '<tr class="total-row">' + "".join(f"<td>{escape(str(v))}</td>" for v in totals) + "</tr>"

    chart_block = f'<div class="chart-wrap">{chart_svg}</div>' if chart_svg else ""

    return (
        f'<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">'
        f'<title>{escape(title)} · {escape(vaad_name)}</title>'
        f'<style>{_base_css()}</style></head><body>'
        '<div class="toolbar"><button class="btn" onclick="window.print()">הדפסה / שמירה כ-PDF</button></div>'
        '<div class="doc-header">'
        f'<div class="doc-brand"><h1>{escape(vaad_name)}</h1>'
        f'<div class="sub">{escape(" · ".join(sub_parts))}</div></div>'
        f'<div class="doc-meta"><div>תאריך הפקה: {now_str}</div>'
        f'{f"<div>{escape(subtitle)}</div>" if subtitle else ""}</div>'
        '</div>'
        f'<div class="doc-title">{escape(title)}</div>'
        f'{kpi_html}{chart_block}'
        f'<table><thead>{thead}</thead><tbody>{tbody}</tbody></table>'
        f'<div class="footer"><span>הופק ממערכת ניהול ועד הבית · {escape(complex_name)}</span>'
        f'<span>סה״כ שורות: {len(rows)}</span></div>'
        '</body></html>'
    )


def build_receipt_html(data):
    entry = data["entry"]
    unit = data["unit"]
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    status_badge = (
        '<span class="receipt-badge cancelled">מבוטל</span>'
        if data["reversed"]
        else '<span class="receipt-badge">שולם ואושר</span>'
    )
    payer = entry["party"] or unit["tenant"] or unit["owner"] or "—"
    sub_parts = [p for p in (data["complex_name"], data["address"], data["contact"]) if p]
    bal_now = data["balance_now"]
    bal_label = "יתרת זכות" if bal_now < 0 else "יתרת חוב עדכנית"

    return (
        f'<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">'
        f'<title>אישור תשלום {escape(data["receipt_no"])}</title>'
        f'<style>{_base_css()}</style></head><body>'
        '<div class="toolbar"><button class="btn" onclick="window.print()">הדפסת אישור / שמירה כ-PDF</button></div>'
        '<div class="receipt-box">'
        '<div class="doc-header">'
        f'<div class="doc-brand"><h1>{escape(data["vaad_name"])}</h1>'
        f'<div class="sub">{escape(" · ".join(sub_parts))}</div></div>'
        f'<div class="doc-meta"><div><strong>אישור תשלום #{escape(data["receipt_no"])}</strong></div>'
        f'<div>תאריך הפקה: {now_str}</div><div style="margin-top:4px">{status_badge}</div></div>'
        '</div>'
        '<div class="receipt-amount">'
        '<div style="font-size:12px;color:#475569">התקבל סך של</div>'
        f'<div class="big">{escape(fmt_money(entry["cash"]))}</div>'
        '</div>'
        '<div class="receipt-grid">'
        f'<div class="receipt-field"><div class="lbl">יחידת מגורים</div><div class="val">{escape(fmt_unit(unit))}</div></div>'
        f'<div class="receipt-field"><div class="lbl">שם המשלם</div><div class="val">{escape(payer)}</div></div>'
        f'<div class="receipt-field"><div class="lbl">תאריך תשלום</div><div class="val">{escape(fmt_date(entry["day"]))}</div></div>'
        f'<div class="receipt-field"><div class="lbl">אמצעי תשלום</div><div class="val">{escape(entry["method"])}</div></div>'
        f'<div class="receipt-field"><div class="lbl">אסמכתא</div><div class="val">{escape(entry["reference"] or "—")}</div></div>'
        f'<div class="receipt-field"><div class="lbl">{bal_label}</div><div class="val">{escape(fmt_money(abs(bal_now)))}</div></div>'
        f'<div class="receipt-field" style="grid-column:1 / -1"><div class="lbl">הערות</div><div class="val">{escape(entry["notes"] or "תשלום דמי ועד בית")}</div></div>'
        '</div>'
        '<div class="sig-row">'
        '<div class="sig-line">חתימת נציג ועד הבית</div>'
        f'<div class="sig-line">מספר פעולה במערכת: {entry["id"]}</div>'
        '</div>'
        '</div></body></html>'
    )


def _find_chromium_browser():
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        shutil.which("msedge"),
        shutil.which("chrome"),
    ]
    for path in candidates:
        if path and Path(path).is_file():
            return str(path)
    return None


def export_pdf(html_content, pdf_path):
    """Export HTML to a native Hebrew RTL PDF via headless Edge/Chrome."""
    browser = _find_chromium_browser()
    if not browser:
        raise Problem("לא נמצא דפדפן Edge או Chrome להמרה ישירה ל-PDF. ניתן להשתמש בתצוגת ההדפסה ולשמור כ-PDF.")
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        html_file = Path(tmpdir) / "report.html"
        html_file.write_text(html_content, encoding="utf-8")
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path.resolve()}",
            html_file.resolve().as_uri(),
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(cmd, capture_output=True, timeout=30, creationflags=creationflags)
        if result.returncode != 0 or not pdf_path.is_file() or pdf_path.stat().st_size == 0:
            # Retry legacy --headless flag for older Chromium builds
            cmd[1] = "--headless"
            result = subprocess.run(cmd, capture_output=True, timeout=30, creationflags=creationflags)
        if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
            raise Problem("הפקת קובץ ה-PDF נכשלה. ניתן להשתמש בתצוגת ההדפסה.")
    return pdf_path


def open_printable_html(data_dir, html_content, slug="report"):
    cache_dir = Path(data_dir) / "reports_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Clean files older than 24 hours
    cutoff = datetime.now() - timedelta(hours=24)
    for old in cache_dir.glob("*.html"):
        try:
            if datetime.fromtimestamp(old.stat().st_mtime) < cutoff:
                old.unlink(missing_ok=True)
        except OSError:
            pass
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = cache_dir / f"{slug}-{stamp}.html"
    target.write_text(html_content, encoding="utf-8")
    webbrowser.open(target.resolve().as_uri())
    return target


def export_csv(path, headers, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as target:
        writer = csv.writer(target)
        writer.writerow(headers)
        for _, values in rows:
            writer.writerow(
                "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")) else value
                for value in values
            )
    return Path(path)


def export_full_archive(store, ledger, zip_path):
    """Export all system data to a portable ZIP containing a multi-sheet Excel workbook + all attachments."""
    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    units_rows = []
    unit_map = {}
    for u in ledger.units():
        unit_map[u["id"]] = fmt_unit(u)
        bal = ledger.account(u["id"])["balance"]
        units_rows.append([
            u["id"], u["building"], "" if u["apartment"].startswith("@") else u["apartment"],
            u["subunit"], u["owner"], u["tenant"], u["phone"], u["email"],
            fmt_number(u["rate"] or 0), fmt_number(bal), "פעילה" if u["active"] else "לא פעילה", u["notes"],
        ])

    cash_rows = []
    for r in ledger.cash()[1]:
        cash_rows.append([
            r["id"], fmt_date(r["day"]), r["kind"], r["description"], r["category_name"] or "",
            unit_map.get(r["unit"], r["party"]), r["supplier_name"] or "", r["method"],
            fmt_number(r["cash"]), fmt_number(r["balance"]), r["reference"], r["notes"],
        ])

    suppliers_rows = [
        [s["id"], s["name"], s["service"], s["phone"], s["contact"], s["email"],
         fmt_number(s["month_total"]), fmt_number(s["year_total"]), "פעיל" if s["active"] else "לא פעיל", s["notes"]]
        for s in ledger.suppliers_summary()
    ]

    occupants_rows = [
        [r["id"], unit_map.get(r["unit"], r["unit"]), "בעלים" if r["role"] == "owner" else "שוכר",
         r["name"], r["phone"], r["email"], fmt_date(r["arrived"]), fmt_date(r["departed"] or ""), r["notes"]]
        for r in store.rows("SELECT * FROM occupants ORDER BY unit, arrived")
    ]

    recurring_rows = [
        [r["id"], r["supplier_name"] or "", r["category_name"], fmt_number(r["usual_amount"]),
         r["frequency_months"], r["due_day"], fmt_date(r["starts"]), fmt_date(r["ends"] or ""),
         "פעילה" if r["active"] else "לא פעילה", r["notes"]]
        for r in ledger.list_recurring()
    ]

    audit_rows = [
        [r["id"], r["ts"], r["username"], r["action"], r["entity_type"], r["entity_id"], r["details"]]
        for r in store.audit_entries(limit=5000)
    ]

    sheets = [
        {"title": "יחידות ודיירים", "headers": ["מזהה", "בניין", "דירה", "יחידה", "בעלים", "שוכר", "טלפון", "דוא״ל", "תעריף", "יתרה", "מצב", "הערות"], "rows": units_rows},
        {"title": "תנועות כספיות", "headers": ["מספר", "תאריך", "סוג", "תיאור", "קטגוריה", "יחידה או צד", "ספק", "אמצעי", "סכום", "יתרה", "אסמכתא", "הערות"], "rows": cash_rows},
        {"title": "ספקים", "headers": ["מזהה", "שם", "שירות", "טלפון", "איש קשר", "דוא״ל", "החודש", "השנה", "מצב", "הערות"], "rows": suppliers_rows},
        {"title": "היסטוריית דיירים", "headers": ["מזהה", "יחידה", "תפקיד", "שם", "טלפון", "דוא״ל", "כניסה", "עזיבה", "הערות"], "rows": occupants_rows},
        {"title": "הוצאות קבועות", "headers": ["מזהה", "ספק", "קטגוריה", "סכום רגיל", "תדירות", "יום", "התחלה", "סיום", "מצב", "תיאור"], "rows": recurring_rows},
        {"title": "יומן פעולות", "headers": ["מזהה", "מועד", "משתמש", "פעולה", "סוג", "מזהה ישות", "פרטים"], "rows": audit_rows},
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        xlsx_file = Path(tmpdir) / "vaad-data.xlsx"
        write_xlsx(xlsx_file, sheets)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(xlsx_file, "vaad-data.xlsx")
            for att in store.list_attachments():
                src = store.attachments_dir / att["stored_name"]
                if src.is_file():
                    zf.write(src, f"attachments/{att['entry']}_{att['filename']}")
    return zip_path
