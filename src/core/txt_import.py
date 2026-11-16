"""Delimited numeric text to MF4 conversion, independent of Qt."""

from __future__ import annotations

import csv
import os
import tempfile
from itertools import islice
from pathlib import Path

import numpy as np
from asammdf import MDF, Signal


def read_txt_table(
    path: str | Path,
    delimiter: str = "\t",
    limit: int | None = None,
) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """Read a header and data rows; ignore empty trailing columns in the header."""
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, delimiter=delimiter)
        header = next(reader, [])
        while header and not header[-1].strip():
            header.pop()
        if not header:
            raise ValueError("Soubor nemá hlavičku sloupců.")
        rows = ((reader.line_num, row) for row in reader if any(cell.strip() for cell in row))
        return header, list(islice(rows, limit)) if limit is not None else list(rows)


def parse_txt_values(
    rows: list[tuple[int, list[str]]],
    names: list[str],
    decimal: str,
    time_column: int | None,
    period: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Validate all selected columns and return timestamps and numeric table."""
    if not names or any(not name.strip() for name in names):
        raise ValueError("Každý sloupec musí mít neprázdný název.")
    if len(set(names)) != len(names):
        raise ValueError("Názvy sloupců musí být jedinečné.")
    if decimal not in (",", "."):
        raise ValueError("Neplatný desetinný oddělovač.")
    if time_column is not None and not 0 <= time_column < len(names):
        raise ValueError("Vyberte platný časový sloupec.")
    if time_column is not None and len(names) < 2:
        raise ValueError("Kromě času je potřeba alespoň jeden signál.")
    if time_column is None and (not np.isfinite(period) or period <= 0):
        raise ValueError("Perioda vzorkování musí být kladná.")
    if not rows:
        raise ValueError("Soubor neobsahuje datové řádky.")
    values = []
    for line, row in rows:
        if len(row) < len(names) or any(cell.strip() for cell in row[len(names) :]):
            raise ValueError(f"Řádek {line}: počet hodnot neodpovídá hlavičce.")
        parsed = []
        for column, cell in enumerate(row[: len(names)]):
            text = cell.strip()
            try:
                if decimal == "." and "," in text:
                    raise ValueError
                if decimal == "," and "." in text:
                    raise ValueError
                value = float(text.replace(",", "."))
                if not np.isfinite(value):
                    raise ValueError
            except ValueError as exc:
                raise ValueError(
                    f"Řádek {line}, sloupec {column + 1} ({names[column]}): "
                    f"neplatné číslo {cell!r}."
                ) from exc
            parsed.append(value)
        values.append(parsed)
    table = np.asarray(values, dtype=float)
    timestamps = (
        table[:, time_column].copy()
        if time_column is not None
        else np.arange(len(table), dtype=float) * period
    )
    if not np.all(np.isfinite(timestamps)) or np.any(np.diff(timestamps) <= 0):
        raise ValueError("Čas musí být konečný a přísně rostoucí (v sekundách).")
    return timestamps, table


def import_txt_to_mf4(
    source: str | Path,
    destination: str | Path,
    names: list[str],
    delimiter: str = "\t",
    decimal: str = ",",
    time_column: int | None = None,
    period: float = 0.01,
) -> Path:
    """Validate before writing; publish the MF4 atomically only on success."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination:
        raise ValueError("Výstup nesmí přepsat vstupní TXT soubor.")
    header, rows = read_txt_table(source, delimiter)
    if len(header) != len(names):
        raise ValueError("Počet názvů neodpovídá počtu sloupců souboru.")
    timestamps, table = parse_txt_values(rows, names, decimal, time_column, period)
    handle, temporary = tempfile.mkstemp(suffix=".mf4", dir=destination.parent)
    os.close(handle)
    try:
        with MDF(version="4.10") as mdf:
            mdf.append(
                [
                    Signal(samples=table[:, index], timestamps=timestamps, name=name)
                    for index, name in enumerate(names)
                    if index != time_column
                ],
                common_timebase=True,
                acq_name="TXT import",
            )
            mdf.save(temporary, overwrite=True)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return destination
