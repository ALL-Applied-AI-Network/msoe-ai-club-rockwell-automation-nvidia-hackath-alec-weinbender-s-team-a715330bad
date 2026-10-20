"""Spreadsheet files for the results tracker: rows written as XLSX (header row, dropdowns, hidden columns) or CSV, and an
uploaded XLSX or CSV read back into rows keyed by its header.

Nothing here knows what the columns mean: the test plan (services/test_plans.py) chooses them and the physical trials
service checks the values. CSV is written as UTF-8 with a byte-order mark, so Excel opens it with the right encoding, and
read leniently (UTF-8 or Windows-1252, comma or semicolon separated), since Excel saves CSV differently per locale.
"""

import csv
import io
import logging
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
SPARE_ROWS = 200  # rows below the data that keep the dropdowns, for extra trials typed in at the bottom
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

Row = Mapping[str, Any]


class SpreadsheetError(ValueError):
    """The upload can't be read as a table: a damaged file, no header row, or a required column missing."""


class UnsupportedSpreadsheetError(ValueError):
    """Not an .xlsx or .csv file. The message says what to send instead."""


def write_xlsx(
    columns: Sequence[str],
    rows: Iterable[Row],
    *,
    title: str,
    dropdowns: Mapping[str, Sequence[str]] | None = None,
    hidden: Iterable[str] = (),
) -> bytes:
    """One sheet: a bold, frozen header row, then one row per mapping (missing keys and None stay blank). Columns in
    `dropdowns` only take those values (or blank), down to SPARE_ROWS below the data; `hidden` columns are hidden."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title
    sheet.append(list(columns))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    sheet.freeze_panes = "A2"
    for row in rows:
        sheet.append([row.get(name) for name in columns])
    last = sheet.max_row + SPARE_ROWS
    for name, choices in (dropdowns or {}).items():
        letter = _letter(columns, name)
        rule = DataValidation(type="list", formula1=f'"{",".join(choices)}"', allow_blank=True, showErrorMessage=True)
        rule.errorTitle, rule.error = f"{name}", f"{name}: choose {', '.join(choices)}, or leave it blank"
        rule.add(f"{letter}2:{letter}{last}")
        sheet.add_data_validation(rule)
    for i, name in enumerate(columns, start=1):
        sheet.column_dimensions[get_column_letter(i)].width = max(10, len(name) + 3)
    for name in hidden:
        sheet.column_dimensions[_letter(columns, name)].hidden = True
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def write_csv(columns: Sequence[str], rows: Iterable[Row]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if row.get(name) is None else row.get(name) for name in columns])
    return out.getvalue().encode("utf-8-sig")


def read_rows(filename: str, content: bytes, *, required: Sequence[str] = ()) -> list[tuple[int, dict[str, Any]]]:
    """Every non-blank row under the header row, as (its row number in the spreadsheet, {column: value}). The header row
    is row 1; its names are matched trimmed and lower-case, and columns it doesn't name are ignored. Blank cells are None.
    An XLSX keeps its cell types (numbers, booleans, dates); a CSV gives text. Reads the first sheet of a workbook."""
    if len(content) > MAX_UPLOAD_BYTES:
        raise SpreadsheetError(f"{filename or 'the upload'}: larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".xlsx" or (not suffix and content.startswith(b"PK")):
        table = _xlsx_table(content)
    elif suffix in (".csv", ".txt") or not suffix:
        table = _csv_table(content)
    elif suffix in (".xls", ".xlsm", ".ods", ".numbers"):
        raise UnsupportedSpreadsheetError(f"{suffix} files aren't read: save the sheet as .xlsx (Excel Workbook) or .csv")
    else:
        raise UnsupportedSpreadsheetError(f"{filename}: upload the test plan as .xlsx or .csv")
    if not table or not any(_blank(v) is not None for v in table[0]):
        raise SpreadsheetError("the file is empty: the first row should be the header (trial_id, ..., outcome, ...)")
    header = [str(v).strip().lower() if _blank(v) is not None else "" for v in table[0]]
    missing = [name for name in required if name not in header]
    if missing:
        raise SpreadsheetError(f"the header row has no {', '.join(missing)} column; download the test plan again to get every column")
    index = {name: i for i, name in reversed(list(enumerate(header))) if name}  # the first column of a name wins
    out = []
    for number, cells in enumerate(table[1:], start=2):
        values = {name: _blank(cells[i]) if i < len(cells) else None for name, i in index.items()}
        if any(v is not None for v in values.values()):
            out.append((number, values))
    return out


def _xlsx_table(content: bytes) -> list[tuple[Any, ...]]:
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as e:  # openpyxl raises zipfile, KeyError and XML errors for a damaged or foreign file
        logger.info("Spreadsheet: unreadable .xlsx (%s)", e)
        raise SpreadsheetError("not a readable .xlsx file") from e
    try:
        return [tuple(row) for row in workbook.worksheets[0].iter_rows(values_only=True)]
    finally:
        workbook.close()


def _csv_table(content: bytes) -> list[list[str]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1252", errors="replace")  # Excel's "CSV (Comma delimited)" on Windows
    first = text.split("\n", 1)[0]
    delimiter = max((",", ";", "\t"), key=first.count)
    try:
        return list(csv.reader(io.StringIO(text), delimiter=delimiter))
    except csv.Error as e:
        raise SpreadsheetError(f"not a readable .csv file: {e}") from e


def _blank(value: Any) -> Any:
    """None for an empty cell; text trimmed; dates as ISO text; everything else as is."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _letter(columns: Sequence[str], name: str) -> str:
    return get_column_letter(list(columns).index(name) + 1)
