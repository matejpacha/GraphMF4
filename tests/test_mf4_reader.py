"""Unit tests for MF4Reader.

These tests use asammdf's in-memory MDF creation so no real .mf4 file
is needed on disk. Tests that require a real file are marked with
@pytest.mark.requires_mf4 and skipped in CI.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


from core.mf4_reader import MF4Reader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_temp_mf4(tmp_path: Path) -> Path:
    """Create a minimal MF4 file with one channel using asammdf."""
    from asammdf import MDF, Signal

    mdf = MDF()
    t = np.linspace(0.0, 1.0, 101)
    sig = Signal(samples=np.sin(2 * np.pi * t), timestamps=t, name="Sine", unit="V")
    mdf.append([sig])
    out_path = tmp_path / "test_signal.mf4"
    mdf.save(str(out_path), overwrite=True)
    mdf.close()
    return out_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMF4ReaderCaching:
    def test_load_returns_same_instance(self, tmp_path):
        path = _make_temp_mf4(tmp_path)
        reader = MF4Reader()
        mdf1 = reader.load_file(path)
        mdf2 = reader.load_file(path)
        assert mdf1 is mdf2
        reader.close_all()

    def test_is_loaded(self, tmp_path):
        path = _make_temp_mf4(tmp_path)
        reader = MF4Reader()
        assert not reader.is_loaded(path)
        reader.load_file(path)
        assert reader.is_loaded(path)
        reader.close_all()

    def test_unload_file(self, tmp_path):
        path = _make_temp_mf4(tmp_path)
        reader = MF4Reader()
        reader.load_file(path)
        reader.unload_file(path)
        assert not reader.is_loaded(path)

    def test_close_all_clears_cache(self, tmp_path):
        path = _make_temp_mf4(tmp_path)
        reader = MF4Reader()
        reader.load_file(path)
        reader.close_all()
        assert not reader.is_loaded(path)


class TestMF4ReaderChannelList:
    def test_get_channel_list_returns_sine(self, tmp_path):
        path = _make_temp_mf4(tmp_path)
        reader = MF4Reader()
        channels = reader.get_channel_list(path)
        names = [ch.name for ch in channels]
        assert "Sine" in names
        reader.close_all()

    def test_channel_has_unit(self, tmp_path):
        path = _make_temp_mf4(tmp_path)
        reader = MF4Reader()
        channels = reader.get_channel_list(path)
        sine_ch = next(ch for ch in channels if ch.name == "Sine")
        assert sine_ch.unit == "V"
        reader.close_all()


class TestMF4ReaderReadSignal:
    def test_read_signal_shape(self, tmp_path):
        path = _make_temp_mf4(tmp_path)
        reader = MF4Reader()
        sig = reader.read_signal(path, "Sine")
        assert len(sig.timestamps) == 101
        assert len(sig.samples) == 101
        reader.close_all()

    def test_read_signal_values(self, tmp_path):
        path = _make_temp_mf4(tmp_path)
        reader = MF4Reader()
        sig = reader.read_signal(path, "Sine")
        expected = np.sin(2 * np.pi * np.linspace(0.0, 1.0, 101))
        np.testing.assert_allclose(sig.samples, expected, atol=1e-6)
        reader.close_all()

    def test_read_nonexistent_channel_raises(self, tmp_path):
        path = _make_temp_mf4(tmp_path)
        reader = MF4Reader()
        with pytest.raises(Exception):
            reader.read_signal(path, "DoesNotExist_XYZ")
        reader.close_all()
