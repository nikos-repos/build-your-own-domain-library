#!/usr/bin/env python3
"""
html_table_converter.py — Convert OCR HTML table_body to pipe-format markdown.

OCR table extraction can produce `<table>` HTML with varying quality:
- Some tables have correct cell alignment
- Frequently, multi-row data gets crammed into a single `<td>`
- colspan/rowspan attributes may be present but unreliable

This converter handles all cases gracefully, falling back to best-effort
pipe tables when the HTML is malformed.

Usage (as library):
    from html_table_converter import convert_html_table
    markdown = convert_html_table("<table>...</table>")

Usage (CLI):
    domain-library run html_table_converter --input table.html
    echo '<table>...' | domain-library run html_table_converter --stdin
"""

import argparse
import html
import re
import sys
from html.parser import HTMLParser


class TableRow:
    """Represents one row of a table."""
    def __init__(self):
        self.cells = []

    def add_cell(self, text: str, colspan: int = 1, rowspan: int = 1):
        self.cells.append({
            "text": text.strip(),
            "colspan": max(1, colspan),
            "rowspan": max(1, rowspan),
        })


class TableParser(HTMLParser):
    """Parse HTML <table> into rows of cells."""

    def __init__(self):
        super().__init__()
        self.rows: list[TableRow] = []
        self._current_row: TableRow | None = None
        self._current_cell_text: str = ""
        self._in_cell = False
        self._current_colspan = 1
        self._current_rowspan = 1

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "tr":
            self._current_row = TableRow()
            self.rows.append(self._current_row)
        elif tag in ("td", "th"):
            self._in_cell = True
            self._current_cell_text = ""
            raw_colspan = attrs_dict.get("colspan", "1")
            raw_rowspan = attrs_dict.get("rowspan", "1")
            self._current_colspan = int(raw_colspan) if raw_colspan else 1
            self._current_rowspan = int(raw_rowspan) if raw_rowspan else 1
        elif tag in ("br", "br/"):
            if self._in_cell:
                self._current_cell_text += "\n"

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._in_cell:
            self._in_cell = False
            if self._current_row is not None:
                self._current_row.add_cell(
                    self._current_cell_text,
                    self._current_colspan,
                    self._current_rowspan,
                )

    def handle_data(self, data):
        if self._in_cell:
            self._current_cell_text += data


def _escape_pipe(text: str) -> str:
    """Escape pipe characters in cell content."""
    return text.replace("|", "\\|").replace("\n", " ")


def _normalize_cells(rows: list[TableRow]) -> list[list[str]]:
    """Normalize rows to same column count, expanding colspan/rowspan."""
    if not rows:
        return []

    # First pass: determine max columns
    max_cols = max(
        sum(cell["colspan"] for cell in row.cells) for row in rows
    ) if rows else 0

    # Expand rowspan: build a grid
    grid = [[""] * max_cols for _ in range(len(rows))]
    occupied = [[False] * max_cols for _ in range(len(rows))]

    for r_idx, row in enumerate(rows):
        c_idx = 0
        for cell in row.cells:
            # Skip occupied cells
            while c_idx < max_cols and occupied[r_idx][c_idx]:
                c_idx += 1
            if c_idx >= max_cols:
                break

            text = _escape_pipe(cell["text"])

            # Fill the cell and any rowspan/colspan targets
            for dr in range(cell["rowspan"]):
                for dc in range(cell["colspan"]):
                    tr = r_idx + dr
                    tc = c_idx + dc
                    if tr < len(grid) and tc < max_cols:
                        if not occupied[tr][tc]:
                            grid[tr][tc] = text if (dr == 0 and dc == 0) else ""
                            occupied[tr][tc] = True

            c_idx += cell["colspan"]

    return grid


def convert_html_table(html_str: str) -> str:
    """Convert an HTML <table> string to pipe-format markdown.

    Returns empty string if no valid table data found.
    """
    if not html_str or "<table" not in html_str.lower():
        return ""

    try:
        parser = TableParser()
        parser.feed(html_str)
    except Exception:
        # Malformed HTML — fall back to regex extraction
        return _fallback_extract(html_str)

    if not parser.rows:
        return ""

    grid = _normalize_cells(parser.rows)
    if not grid:
        return ""

    # Filter out completely empty rows
    grid = [row for row in grid if any(cell.strip() for cell in row)]
    if not grid:
        return ""

    # Determine column widths for alignment
    col_count = len(grid[0]) if grid else 0
    col_widths = [3] * col_count
    for row in grid:
        for i, cell in enumerate(row):
            if i < col_count:
                col_widths[i] = max(col_widths[i], len(cell))

    # Cap column widths at 40 chars
    col_widths = [min(w, 40) for w in col_widths]

    lines = []

    # Header row (first row)
    header = grid[0]
    header_cells = [cell.ljust(col_widths[i]) for i, cell in enumerate(header)]
    lines.append("| " + " | ".join(header_cells) + " |")

    # Separator
    sep_cells = ["-" * col_widths[i] for i in range(col_count)]
    lines.append("| " + " | ".join(sep_cells) + " |")

    # Data rows
    for row in grid[1:]:
        # Pad row if short
        while len(row) < col_count:
            row.append("")
        cells = [row[i].ljust(col_widths[i]) for i in range(col_count)]
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines)


def _fallback_extract(html_str: str) -> str:
    """Regex-based fallback for completely broken HTML."""
    # Strip tags, extract text between td/th
    cells = re.findall(r"<(?:td|th)[^>]*>(.*?)</(?:td|th)>", html_str, re.DOTALL | re.IGNORECASE)
    if not cells:
        return ""

    cells = [html.unescape(c.strip()) for c in cells]

    # Try to detect column count from first row
    # Count cells in first <tr>
    first_tr = re.search(r"<tr[^>]*>(.*?)</tr>", html_str, re.DOTALL | re.IGNORECASE)
    if first_tr:
        first_cells = re.findall(r"<(?:td|th)[^>]*>", first_tr.group(1), re.IGNORECASE)
        col_count = len(first_cells)
    else:
        col_count = max(2, len(cells) // max(1, len(cells) // 6))

    if col_count < 2:
        col_count = 2

    lines = []
    # Header
    header = cells[:col_count]
    while len(header) < col_count:
        header.append("")
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * col_count) + " |")

    # Data
    remaining = cells[col_count:]
    for i in range(0, len(remaining), col_count):
        row = remaining[i:i + col_count]
        while len(row) < col_count:
            row.append("")
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Convert HTML table to markdown")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="Input HTML file")
    source.add_argument("--stdin", action="store_true", help="Read from stdin")
    parser.add_argument("--output", help="Output file (default: stdout)")
    args = parser.parse_args()

    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            html_input = f.read()
    else:
        html_input = sys.stdin.read()

    result = convert_html_table(html_input)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result)
            f.write("\n")
    else:
        print(result)


if __name__ == "__main__":
    main()
