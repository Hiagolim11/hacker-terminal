"""Read-only loaders for spreadsheets (CSV/TSV, XLSX, ODS) using only the stdlib.

Everything is capped: rows, columns, cell text and the uncompressed size of
zip members, so a huge or hostile file costs bounded time and memory.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

MAX_ROWS = 5_000
MAX_COLUMNS = 200
MAX_CELL_CHARS = 1_000
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_MEMBER_BYTES = 300 * 1024 * 1024
MAX_SHEETS = 64
# Rows scanned (not shown) just to count totals; beyond this the total
# becomes a lower bound so a million-row file never costs seconds of CPU.
MAX_SCAN_ROWS = 50_000

IMAGE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".svgz", ".ico",
    ".tif", ".tiff", ".avif", ".heic", ".heif", ".jxl", ".qoi", ".tga", ".pnm",
    ".ppm", ".pgm", ".pbm", ".xpm",
}
SPREADSHEET_SUFFIXES = {".csv", ".tsv", ".tab", ".xlsx", ".xlsm", ".ods"}


class DocumentError(ValueError):
    """Raised when a file cannot be shown."""


@dataclass
class Sheet:
    name: str
    rows: list[list[str]] = field(default_factory=list)
    total_rows: int = 0
    total_columns: int = 0
    # "" exact, "≈" estimated, ">" lower bound (reading stopped early)
    total_prefix: str = ""

    @property
    def truncated(self) -> bool:
        return bool(self.total_prefix) or self.total_rows > len(self.rows) or self.total_columns > self.width

    @property
    def width(self) -> int:
        return max((len(row) for row in self.rows), default=0)


def kind_of(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in SPREADSHEET_SUFFIXES:
        return "spreadsheet"
    return None


def column_name(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _clip(text: str) -> str:
    text = text.replace("\r\n", "\n")
    return text if len(text) <= MAX_CELL_CHARS else text[: MAX_CELL_CHARS - 1] + "…"


def _trim(rows: list[list[str]]) -> list[list[str]]:
    """Drop trailing empty cells and rows, which spreadsheets often carry."""
    trimmed = [row[: max((i + 1 for i, cell in enumerate(row) if cell), default=0)] for row in rows]
    while trimmed and not trimmed[-1]:
        trimmed.pop()
    return trimmed


def load_spreadsheet(path: Path) -> list[Sheet]:
    try:
        size = path.stat().st_size
    except OSError as error:
        raise DocumentError(f"não foi possível ler {path.name}: {error.strerror}") from error
    if size > MAX_FILE_BYTES:
        raise DocumentError(f"{path.name} tem mais de {MAX_FILE_BYTES // 1024 // 1024} MB")
    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv", ".tab"):
        return [_load_delimited(path)]
    if suffix in (".xlsx", ".xlsm"):
        return _load_xlsx(path)
    if suffix == ".ods":
        return _load_ods(path)
    raise DocumentError(f"formato não suportado: {suffix or path.name}")


# ---------------------------------------------------------------- CSV / TSV


def _detect_encoding(sample: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            sample.decode(encoding)
            return encoding
        except UnicodeDecodeError as error:
            # A multi-byte character cut at the end of the sample is fine.
            if encoding == "utf-8-sig" and error.start >= len(sample) - 3:
                return encoding
    return "latin-1"


def _count_lines(path: Path) -> int:
    count = 0
    last = b"\n"
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            count += chunk.count(b"\n")
            last = chunk[-1:]
    return count + (last != b"\n")


def _load_delimited(path: Path) -> Sheet:
    # Streamed: only the rows that can be shown are parsed; the rest is
    # counted in C, so a 300k-line file costs milliseconds, not seconds.
    with path.open("rb") as raw:
        sample_bytes = raw.read(256 * 1024)
    encoding = _detect_encoding(sample_bytes)
    sample = sample_bytes.decode(encoding, errors="replace")
    if path.suffix.lower() in (".tsv", ".tab"):
        dialect: type[csv.Dialect] | csv.Dialect = csv.excel_tab
    else:
        try:
            dialect = csv.Sniffer().sniff(sample[:64 * 1024], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
    sheet = Sheet(path.name)
    stopped_early = False
    with path.open(encoding=encoding, errors="replace", newline="") as handle:
        reader = csv.reader(handle, dialect)
        try:
            for row in reader:
                if len(sheet.rows) >= MAX_ROWS:
                    stopped_early = True
                    break
                sheet.total_columns = max(sheet.total_columns, len(row))
                sheet.rows.append([_clip(cell) for cell in row[:MAX_COLUMNS]])
        except csv.Error as error:
            raise DocumentError(f"CSV inválido na linha {reader.line_num}: {error}") from error
    sheet.total_rows = len(sheet.rows)
    if stopped_early:
        sheet.total_rows = max(_count_lines(path), MAX_ROWS + 1)
        sheet.total_prefix = "≈"
    sheet.rows = _trim(sheet.rows)
    return sheet


# --------------------------------------------------------------------- zip


def _open_member(archive: zipfile.ZipFile, name: str):
    try:
        info = archive.getinfo(name)
    except KeyError as error:
        raise DocumentError(f"arquivo interno ausente: {name}") from error
    if info.file_size > MAX_MEMBER_BYTES:
        raise DocumentError(f"conteúdo descompactado grande demais: {name}")
    return archive.open(info)


def _open_zip(path: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as error:
        raise DocumentError(f"{path.name} não é uma planilha válida (zip corrompido)") from error


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# -------------------------------------------------------------------- XLSX

_CELL_REF = re.compile(r"([A-Z]+)(\d+)")
_DATE_FORMAT_IDS = set(range(14, 23)) | {45, 46, 47}
_DATE_TOKENS = re.compile(r"(?<![\\\"])[dmyhs]", re.I)
_EXCEL_EPOCH = dt.datetime(1899, 12, 30)


def _column_index(letters: str) -> int:
    index = 0
    for char in letters:
        index = index * 26 + ord(char) - 64
    return index - 1


def _xlsx_date_styles(archive: zipfile.ZipFile) -> set[int]:
    """Indexes of cell styles that display numbers as dates or times."""
    try:
        with _open_member(archive, "xl/styles.xml") as handle:
            root = ElementTree.parse(handle).getroot()
    except (DocumentError, ElementTree.ParseError):
        return set()
    custom = {}
    for element in root.iter():
        if _local(element.tag) == "numFmt":
            code = re.sub(r"\[[^\]]*\]|\"[^\"]*\"", "", element.get("formatCode", ""))
            custom[int(element.get("numFmtId", "0"))] = bool(_DATE_TOKENS.search(code))
    styles = set()
    for element in root.iter():
        if _local(element.tag) == "cellXfs":
            for index, xf in enumerate(child for child in element if _local(child.tag) == "xf"):
                format_id = int(xf.get("numFmtId", "0"))
                if format_id in _DATE_FORMAT_IDS or custom.get(format_id):
                    styles.add(index)
            break
    return styles


def _excel_date(value: str) -> str:
    try:
        number = float(value)
    except ValueError:
        return value
    if not 0 <= number < 2_958_466:
        return value
    # Round to the second: serials are fractions of a day, so 08:05 is
    # stored as 08:04:59.999… and would otherwise be truncated.
    moment = _EXCEL_EPOCH + dt.timedelta(seconds=round(number * 86_400))
    if number < 1:
        return moment.strftime("%H:%M:%S")
    if moment.hour or moment.minute or moment.second:
        return moment.strftime("%d/%m/%Y %H:%M")
    return moment.strftime("%d/%m/%Y")


def _number(value: str) -> str:
    try:
        number = float(value)
    except ValueError:
        return value
    if number.is_integer() and abs(number) < 1e15:
        return str(int(number))
    return f"{number:.10g}"


def _load_xlsx(path: Path) -> list[Sheet]:
    with _open_zip(path) as archive:
        relationships = {}
        with _open_member(archive, "xl/_rels/workbook.xml.rels") as handle:
            for element in ElementTree.parse(handle).getroot():
                target = element.get("Target", "")
                target = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
                relationships[element.get("Id")] = target
        sheets_meta = []
        with _open_member(archive, "xl/workbook.xml") as handle:
            for element in ElementTree.parse(handle).getroot().iter():
                if _local(element.tag) == "sheet":
                    rel = next((value for key, value in element.attrib.items() if _local(key) == "id"), None)
                    if rel in relationships:
                        sheets_meta.append((element.get("name", "Planilha"), relationships[rel]))
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            with _open_member(archive, "xl/sharedStrings.xml") as handle:
                for _event, element in ElementTree.iterparse(handle):
                    if _local(element.tag) == "si":
                        shared.append(_clip("".join(
                            node.text or "" for node in element.iter() if _local(node.tag) == "t"
                        )))
                        element.clear()
        date_styles = _xlsx_date_styles(archive)
        sheets = []
        for name, member in sheets_meta[:MAX_SHEETS]:
            sheets.append(_load_xlsx_sheet(archive, name, member, shared, date_styles))
        if not sheets:
            raise DocumentError("a pasta de trabalho não tem planilhas")
        return sheets


_DIMENSION = re.compile(r"(?:[A-Z]+\d+:)?([A-Z]+)(\d+)")


def _load_xlsx_sheet(archive, name, member, shared, date_styles) -> Sheet:
    sheet = Sheet(name)
    rows: dict[int, list[str]] = {}
    declared: tuple[int, int] | None = None
    sheet_data = None
    scanned = 0
    with _open_member(archive, member) as handle:
        for event, element in ElementTree.iterparse(handle, events=("start", "end")):
            tag = _local(element.tag)
            if event == "start":
                if tag == "sheetData":
                    sheet_data = element
                elif tag == "dimension":
                    match = _DIMENSION.fullmatch(element.get("ref", ""))
                    if match:
                        declared = (int(match.group(2)), _column_index(match.group(1)) + 1)
                continue
            if tag == "row":
                # Rows are fully read by now; dropping them keeps memory flat.
                if sheet_data is not None:
                    sheet_data.clear()
                else:
                    element.clear()
                if declared and len(rows) >= MAX_ROWS:
                    break  # the declared size already tells the totals
                scanned += 1
                if scanned >= MAX_SCAN_ROWS:
                    sheet.total_prefix = ">"
                    break
                continue
            if tag != "c":
                continue
            reference = _CELL_REF.fullmatch(element.get("r", ""))
            if reference is None:
                continue
            column = _column_index(reference.group(1))
            row_index = int(reference.group(2)) - 1
            sheet.total_rows = max(sheet.total_rows, row_index + 1)
            sheet.total_columns = max(sheet.total_columns, column + 1)
            if row_index >= MAX_ROWS or column >= MAX_COLUMNS:
                continue
            kind = element.get("t", "n")
            value_node = next((child for child in element if _local(child.tag) == "v"), None)
            value = value_node.text if value_node is not None and value_node.text else ""
            formula = next((child for child in element if _local(child.tag) == "f"), None)
            if not value and formula is not None and formula.text:
                text = "=" + formula.text  # no cached result was saved
            elif kind == "s" and value.isdigit():
                text = shared[int(value)] if int(value) < len(shared) else ""
            elif kind == "inlineStr":
                text = "".join(node.text or "" for node in element.iter() if _local(node.tag) == "t")
            elif kind == "b":
                text = "VERDADEIRO" if value == "1" else "FALSO"
            elif kind in ("str", "e"):
                text = value
            elif value and int(element.get("s", "0") or 0) in date_styles:
                text = _excel_date(value)
            else:
                text = _number(value) if value else ""
            row = rows.setdefault(row_index, [])
            if len(row) <= column:
                row.extend([""] * (column + 1 - len(row)))
            row[column] = _clip(text)
    if rows and declared and declared[0] > sheet.total_rows and not sheet.total_prefix:
        sheet.total_rows, sheet.total_columns = declared[0], max(sheet.total_columns, declared[1])
    if rows:
        last = max(rows)
        sheet.rows = _trim([rows.get(index, []) for index in range(last + 1)])
    return sheet


# --------------------------------------------------------------------- ODS

_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


def _ods_cell_text(cell) -> str:
    kind = cell.get(f"{_OFFICE}value-type")
    if kind in ("float", "percentage", "currency"):
        paragraphs = [node for node in cell.iter(f"{_TEXT}p")]
        if paragraphs:
            return "".join(paragraphs[0].itertext())
        return _number(cell.get(f"{_OFFICE}value", ""))
    if kind == "date":
        value = cell.get(f"{_OFFICE}date-value", "")
        try:
            moment = dt.datetime.fromisoformat(value)
            return moment.strftime("%d/%m/%Y %H:%M" if "T" in value else "%d/%m/%Y")
        except ValueError:
            return value
    if kind == "boolean":
        return "VERDADEIRO" if cell.get(f"{_OFFICE}boolean-value") == "true" else "FALSO"
    return "\n".join("".join(node.itertext()) for node in cell.iter(f"{_TEXT}p"))


def _load_ods(path: Path) -> list[Sheet]:
    sheets: list[Sheet] = []
    with _open_zip(path) as archive, _open_member(archive, "content.xml") as handle:
        current: Sheet | None = None
        pending_empty = 0  # blank rows only count if content follows them
        skip_to_table_end = False
        skipped = 0
        incomplete = False
        for event, element in ElementTree.iterparse(handle, events=("start", "end")):
            if event == "start":
                if element.tag == f"{_TABLE}table" and not skip_to_table_end:
                    current = Sheet(element.get(f"{_TABLE}name", f"Planilha {len(sheets) + 1}"))
                    pending_empty = 0
                continue
            if skip_to_table_end:
                if element.tag == f"{_TABLE}table":
                    skip_to_table_end = False
                    if len(sheets) >= MAX_SHEETS:
                        break
                elif element.tag == f"{_TABLE}table-row":
                    skipped += 1
                    element.clear()
                    if skipped >= MAX_SCAN_ROWS:
                        incomplete = True
                        break  # later sheets, if any, are not read
                continue
            if current is None:
                continue
            if element.tag == f"{_TABLE}table-row":
                repeat = max(1, int(element.get(f"{_TABLE}number-rows-repeated", "1") or 1))
                cells: list[str] = []
                position = 0
                content_width = 0
                for cell in element:
                    if _local(cell.tag) not in ("table-cell", "covered-table-cell"):
                        continue
                    span = max(1, int(cell.get(f"{_TABLE}number-columns-repeated", "1") or 1))
                    text = _clip(_ods_cell_text(cell))
                    position += span
                    if text:
                        content_width = position
                    # Empty cells are often repeated up to column 1024; only
                    # materialize what can be displayed.
                    room = MAX_COLUMNS - len(cells)
                    if room > 0:
                        cells.extend([text] * min(span, room))
                element.clear()
                if not content_width:
                    pending_empty += repeat
                    continue
                cells = cells[: min(content_width, MAX_COLUMNS)]
                for _ in range(min(pending_empty, MAX_ROWS - len(current.rows))):
                    current.rows.append([])
                current.total_rows += pending_empty + repeat
                pending_empty = 0
                for _ in range(min(repeat, MAX_ROWS - len(current.rows))):
                    current.rows.append(list(cells))
                current.total_columns = max(current.total_columns, content_width)
                if len(current.rows) >= MAX_ROWS:
                    # Stop parsing: ODS has no declared size, so the total
                    # becomes a lower bound instead of costing a full read.
                    current.total_prefix = ">"
                    sheets.append(current)
                    current = None
                    skip_to_table_end = True
            elif element.tag == f"{_TABLE}table":
                sheets.append(current)
                current = None
                element.clear()
                if len(sheets) >= MAX_SHEETS:
                    break
    if not sheets:
        raise DocumentError("o arquivo não tem planilhas")
    if incomplete:
        sheets[-1].name += " (leitura interrompida)"
    return sheets
