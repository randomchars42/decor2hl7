"""One strict CSV parser for streaming proposals and materialized input."""
from __future__ import annotations

import csv
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .i18n import message as _msg


@dataclass(frozen=True)
class CsvTable:
    rows: list[dict[str, str]]
    columns: list[str]


@dataclass(frozen=True)
class CsvStream:
    columns: list[str]
    rows: Iterator[dict[str, str]]


@contextmanager
def open_csv_table(
    path: Path, *, encoding: str = "utf-8-sig", delimiter: str | None = None,
) -> Iterator[CsvStream]:
    """Keep the file open while the caller consumes checked rows or its header."""
    with path.open(encoding=encoding, newline="") as handle:
        if delimiter:
            reader = csv.reader(handle, delimiter=delimiter, strict=True)
        else:
            sample = handle.read(8192)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel
            reader = csv.reader(handle, dialect=dialect, strict=True)
        try:
            headers = next(reader, [])
        except csv.Error as error:
            raise ValueError(_msg('ui.csv_invalid', path=path, error=error)) from error
        if not headers or any(not name.strip() for name in headers):
            raise ValueError(_msg('ui.csv_header_empty', path=path))
        if len(headers) != len(set(headers)):
            raise ValueError(_msg('ui.csv_header_duplicate', path=path))

        def rows() -> Iterator[dict[str, str]]:
            try:
                for row in reader:
                    if not row:
                        continue
                    if len(row) != len(headers):
                        raise ValueError(_msg(
                            'ui.csv_row_width', path=path,
                            reader_line_num=reader.line_num,
                            row_length=len(row), headers_length=len(headers),
                        ))
                    yield dict(zip(headers, row))
            except csv.Error as error:
                raise ValueError(_msg('ui.csv_invalid', path=path, error=error)) from error

        yield CsvStream(headers, rows())


def read_csv_table(
    path: Path, *, encoding: str = "utf-8-sig", delimiter: str | None = None,
) -> CsvTable:
    with open_csv_table(path, encoding=encoding, delimiter=delimiter) as table:
        return CsvTable(list(table.rows), table.columns)
