"""TXT conversion contract checked through saved MF4 files."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from asammdf import MDF

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.txt_import import import_txt_to_mf4


def test_txt_import_generates_regular_time_and_preserves_columns(tmp_path):
    source = tmp_path / "data.txt"
    source.write_text("old\told\t\n1,25\t-7,5\t\n3,75\t8,25\t\n", encoding="utf-8")
    destination = tmp_path / "result.mf4"
    import_txt_to_mf4(source, destination, ["Position", "Torque"], period=0.125)
    with MDF(destination) as mdf:
        signal = mdf.get("Position")
        np.testing.assert_array_equal(signal.timestamps, [0.0, 0.125])
        np.testing.assert_array_equal(signal.samples, [1.25, 3.75])
        np.testing.assert_array_equal(mdf.get("Torque").samples, [-7.5, 8.25])


def test_txt_import_uses_selected_time_column(tmp_path):
    source = tmp_path / "data.txt"
    source.write_text("A;time;B\n-3.5;12.25;7\n4.75;12.6;9\n", encoding="utf-8")
    destination = tmp_path / "result.mf4"
    import_txt_to_mf4(
        source, destination, ["A", "Time", "B"], delimiter=";", decimal=".", time_column=1
    )
    with MDF(destination) as mdf:
        signal = mdf.get("A")
        np.testing.assert_array_equal(signal.timestamps, [12.25, 12.6])
        np.testing.assert_array_equal(signal.samples, [-3.5, 4.75])
        np.testing.assert_array_equal(mdf.get("B").samples, [7, 9])


@pytest.mark.parametrize(
    "data, options, error",
    [
        ("1,2\t3\n", {"decimal": "."}, "Řádek 2, sloupec 1"),
        ("1\t\n", {}, "Řádek 2, sloupec 2"),
        ("1\t2\t3\n", {}, "počet hodnot"),
        ("nan\t2\n", {}, "neplatné číslo"),
        ("1\t2\n" * 10 + "bad\t3\n", {}, "Řádek 12, sloupec 1"),
        ("2\t3\n1\t4\n", {"time_column": 0}, "rostoucí"),
        ("2\t3\n2\t4\n", {"time_column": 0}, "rostoucí"),
        ("1\t2\n", {"period": 0}, "kladná"),
    ],
)
def test_invalid_txt_does_not_overwrite_destination(tmp_path, data, options, error):
    source = tmp_path / "data.txt"
    source.write_text("A\tB\n" + data, encoding="utf-8")
    destination = tmp_path / "existing.mf4"
    destination.write_bytes(b"original")
    with pytest.raises(ValueError, match=error):
        import_txt_to_mf4(source, destination, ["A", "B"], **options)
    assert destination.read_bytes() == b"original"


def test_repository_txt_sample(tmp_path):
    source = Path(__file__).parent.parent / "src/samples/RT Data__16_11_2026__15_17_49.txt"
    destination = tmp_path / "sample.mf4"
    import_txt_to_mf4(source, destination, ["A", "B", "C", "D", "E"], period=0.02)
    with MDF(destination) as mdf:
        signal = mdf.get("A")
        assert len(signal.samples) == 244
        assert signal.samples[0] == pytest.approx(26.6648845672607)
        assert signal.timestamps[-1] == pytest.approx(4.86)
        assert mdf.get("E").samples[0] == pytest.approx(528.127807617188)
