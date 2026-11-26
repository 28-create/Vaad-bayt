"""Zero-dependency pure-Python Excel (.xlsx) & CSV reader/writer with Hebrew RTL support."""

import csv
from datetime import date, timedelta
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
import zipfile

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
EXCEL_EPOCH = date(1899, 12, 30)


def _col_letter(index):
    """Convert 1-based column index to Excel letter (1->A, 27->AA)."""
    chars = []
    while index > 0:
        index, rem = divmod(index - 1, 26)
        chars.append(chr(65 + rem))
    return "".join(reversed(chars))


def _col_index(ref):
    """Convert cell reference like 'AB12' to 0-based column index."""
    letters = "".join(ch for ch in ref if ch.isalpha()).upper()
    result = 0
    for ch in letters:
        result = result * 26 + (ord(ch) - 64)
    return max(0, result - 1)


def _safe_sheet_title(title, used):
    cleaned = re.sub(r'[\[\]:*?/\\]', " ", str(title)).strip() or "גיליון"
    cleaned = cleaned[:31]
    base = cleaned
    n = 2
    while cleaned in used:
        suffix = f" {n}"
        cleaned = base[: 31 - len(suffix)] + suffix
        n += 1
    used.add(cleaned)
    return cleaned


def _cell_xml(col_idx, row_idx, value, style_id):
    ref = f"{_col_letter(col_idx)}{row_idx}"
    if value is None or value == "":
        return f'<c r="{ref}" s="{style_id}"/>'
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b" s="{style_id}"><v>{1 if value else 0}</v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}" s="{style_id}"><v>{value}</v></c>'
    text = str(value).replace("\r\n", "\n")
    # Neutralize Excel formula injection for user-supplied strings
    if text.startswith(("=", "+", "-", "@")) and not _is_formatted_currency(text):
        text = "'" + text
    escaped = xml_escape(text)
    return f'<c r="{ref}" t="inlineStr" s="{style_id}"><is><t xml:space="preserve">{escaped}</t></is></c>'


def _is_formatted_currency(text):
    stripped = text.replace("₪", "").replace(",", "").replace("\u200e", "").replace("−", "-").strip()
    try:
        float(stripped)
        return True
    except ValueError:
        return False


def _sheet_xml(headers, rows, totals=None):
    widths = [max(10, len(str(h)) + 4) for h in headers]
    all_rows = []
    # Header row (style 1)
    header_cells = "".join(_cell_xml(i + 1, 1, h, 1) for i, h in enumerate(headers))
    all_rows.append(f'<row r="1" ht="24" customHeight="1">{header_cells}</row>')

    row_num = 2
    for idx, row in enumerate(rows):
        base_style = 3 if idx % 2 else 2
        num_style = 5 if idx % 2 else 4
        cells = []
        for col_i, val in enumerate(row):
            if col_i < len(widths):
                widths[col_i] = min(48, max(widths[col_i], len(str(val or "")) + 3))
            style = num_style if isinstance(val, (int, float)) and not isinstance(val, bool) else base_style
            cells.append(_cell_xml(col_i + 1, row_num, val, style))
        all_rows.append(f'<row r="{row_num}">{"".join(cells)}</row>')
        row_num += 1

    if totals:
        cells = []
        for col_i, val in enumerate(totals):
            if col_i < len(widths):
                widths[col_i] = min(48, max(widths[col_i], len(str(val or "")) + 3))
            style = 7 if isinstance(val, (int, float)) and not isinstance(val, bool) else 6
            cells.append(_cell_xml(col_i + 1, row_num, val, style))
        all_rows.append(f'<row r="{row_num}" ht="22" customHeight="1">{"".join(cells)}</row>')

    cols_xml = "".join(
        f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
        for i, w in enumerate(widths)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{NS_MAIN}">'
        '<sheetViews><sheetView rightToLeft="1" workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        f'<cols>{cols_xml}</cols>'
        f'<sheetData>{"".join(all_rows)}</sheetData>'
        '</worksheet>'
    )


def _styles_xml():
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<styleSheet xmlns="{NS_MAIN}">'
        '<numFmts count="1">'
        '<numFmt numFmtId="164" formatCode="#,##0.00"/>'
        '</numFmts>'
        '<fonts count="3">'
        '<font><sz val="11"/><name val="Arial"/></font>'
        '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Arial"/></font>'
        '<font><b/><sz val="11"/><color rgb="FF0F172A"/><name val="Arial"/></font>'
        '</fonts>'
        '<fills count="5">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF1E293B"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFF8FAFC"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFE2E8F0"/></patternFill></fill>'
        '</fills>'
        '<borders count="3">'
        '<border><left/><right/><top/><bottom/><diagonal/></border>'
        '<border>'
        '<left style="thin"><color rgb="FFCBD5E1"/></left>'
        '<right style="thin"><color rgb="FFCBD5E1"/></right>'
        '<top style="thin"><color rgb="FFCBD5E1"/></top>'
        '<bottom style="thin"><color rgb="FFCBD5E1"/></bottom>'
        '</border>'
        '<border>'
        '<left style="thin"><color rgb="FF94A3B8"/></left>'
        '<right style="thin"><color rgb="FF94A3B8"/></right>'
        '<top style="medium"><color rgb="FF334155"/></top>'
        '<bottom style="double"><color rgb="FF334155"/></bottom>'
        '</border>'
        '</borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="8">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'  # 0 default
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>'  # 1 header
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>'  # 2 row text
        '<xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>'  # 3 alt text
        '<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>'  # 4 row num
        '<xf numFmtId="164" fontId="0" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>'  # 5 alt num
        '<xf numFmtId="0" fontId="2" fillId="4" borderId="2" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>'  # 6 total text
        '<xf numFmtId="164" fontId="2" fillId="4" borderId="2" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>'  # 7 total num
        '</cellXfs>'
        '</styleSheet>'
    )


def write_xlsx(path, sheets):
    """Write an RTL-formatted .xlsx workbook.

    `sheets` is a list of dicts: {"title": str, "headers": [...], "rows": [[...], ...], "totals": [...] (optional)}.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    used_names = set()
    normalized = []
    for item in sheets:
        normalized.append(
            (
                _safe_sheet_title(item.get("title", "נתונים"), used_names),
                list(item.get("headers", [])),
                list(item.get("rows", [])),
                item.get("totals"),
            )
        )

    sheet_entries = []
    wb_rels = [
        '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    ]
    content_overrides = [
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ]

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for idx, (title, headers, rows, totals) in enumerate(normalized, start=1):
            sheet_entries.append(f'<sheet name="{xml_escape(title)}" sheetId="{idx}" r:id="rId{idx}"/>')
            wb_rels.append(
                f'<Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{idx}.xml"/>'
            )
            content_overrides.append(
                f'<Override PartName="/xl/worksheets/sheet{idx}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
            zf.writestr(f"xl/worksheets/sheet{idx}.xml", _sheet_xml(headers, rows, totals).encode("utf-8"))

        zf.writestr(
            "[Content_Types].xml",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                + "".join(content_overrides)
                + "</Types>"
            ).encode("utf-8"),
        )
        zf.writestr(
            "_rels/.rels",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                "</Relationships>"
            ).encode("utf-8"),
        )
        zf.writestr(
            "xl/workbook.xml",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<workbook xmlns="{NS_MAIN}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                f'<sheets>{"".join(sheet_entries)}</sheets>'
                "</workbook>"
            ).encode("utf-8"),
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                + "".join(wb_rels)
                + "</Relationships>"
            ).encode("utf-8"),
        )
        zf.writestr("xl/styles.xml", _styles_xml().encode("utf-8"))
    return path


def _date_style_indices(zf):
    """Identify cellXfs style indices that format numbers as dates."""
    date_styles = set()
    if "xl/styles.xml" not in zf.namelist():
        return date_styles
    root = ET.fromstring(zf.read("xl/styles.xml"))
    custom_date_fmts = set()
    for nf in root.findall(f".//{{{NS_MAIN}}}numFmt"):
        code = (nf.attrib.get("formatCode") or "").lower()
        fmt_id = int(nf.attrib.get("numFmtId", "0"))
        cleaned = re.sub(r'"[^"]*"', "", code)
        if any(tok in cleaned for tok in ("yy", "dd", "mm")) and "0.00" not in cleaned:
            custom_date_fmts.add(fmt_id)
    builtin_dates = set(range(14, 23)) | {45, 46, 47}
    xfs = root.find(f"{{{NS_MAIN}}}cellXfs")
    if xfs is not None:
        for idx, xf in enumerate(xfs.findall(f"{{{NS_MAIN}}}xf")):
            fmt_id = int(xf.attrib.get("numFmtId", "0"))
            if fmt_id in builtin_dates or fmt_id in custom_date_fmts:
                date_styles.add(idx)
    return date_styles


def read_xlsx(path):
    """Read the first worksheet of an .xlsx file into a list of string rows."""
    with zipfile.ZipFile(path, "r") as zf:
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            sst = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in sst.findall(f"{{{NS_MAIN}}}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS_MAIN}}}t")))
        date_styles = _date_style_indices(zf)
        sheet_names = sorted(
            name for name in zf.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        if not sheet_names:
            return []
        ws = ET.fromstring(zf.read(sheet_names[0]))
        rows = []
        for row_el in ws.findall(f".//{{{NS_MAIN}}}sheetData/{{{NS_MAIN}}}row"):
            cells = {}
            max_col = -1
            for c in row_el.findall(f"{{{NS_MAIN}}}c"):
                ref = c.attrib.get("r", "")
                col = _col_index(ref) if ref else max_col + 1
                max_col = max(max_col, col)
                ctype = c.attrib.get("t", "")
                style = int(c.attrib.get("s", "-1"))
                v_el = c.find(f"{{{NS_MAIN}}}v")
                is_el = c.find(f"{{{NS_MAIN}}}is")
                value = ""
                if ctype == "s" and v_el is not None and v_el.text is not None:
                    idx = int(v_el.text)
                    value = shared[idx] if 0 <= idx < len(shared) else ""
                elif ctype == "inlineStr" and is_el is not None:
                    value = "".join(t.text or "" for t in is_el.iter(f"{{{NS_MAIN}}}t"))
                elif v_el is not None and v_el.text is not None:
                    raw = v_el.text.strip()
                    if ctype in ("", "n") and style in date_styles:
                        try:
                            serial = int(float(raw))
                            if 20000 <= serial <= 80000:
                                value = (EXCEL_EPOCH + timedelta(days=serial)).isoformat()
                            else:
                                value = raw
                        except ValueError:
                            value = raw
                    else:
                        value = raw
                cells[col] = value.strip()
            if max_col >= 0:
                row_vals = [cells.get(i, "") for i in range(max_col + 1)]
                if any(row_vals):
                    rows.append(row_vals)
        return rows


def read_tabular(path):
    """Read either .xlsx or .csv (supporting UTF-8, UTF-8-BOM, and Hebrew CP1255)."""
    path = Path(path)
    if path.suffix.lower() == ".xlsx":
        return read_xlsx(path)
    raw = path.read_bytes()
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1255", "windows-1255", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return []
    sample = "\n".join(text.splitlines()[:10])
    delimiter = ","
    for cand in (",", ";", "\t"):
        if sample.count(cand) > sample.count(delimiter):
            delimiter = cand
    reader = csv.reader(text.splitlines(), delimiter=delimiter)
    return [[cell.strip() for cell in row] for row in reader if any(cell.strip() for cell in row)]
