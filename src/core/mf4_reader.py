"""MF4 file reader — thin wrapper around asammdf.

All opened MDF handles are cached by absolute file path so large files
are parsed only once per application session.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from asammdf import MDF

_log = logging.getLogger(__name__)


@dataclass
class ChannelInfo:
    """Metadata for one channel discovered in an MF4 file."""

    name: str
    group_index: int
    channel_index: int
    unit: str
    comment: str


@dataclass
class SignalData:
    """Numeric data for one channel read from an MF4 file."""

    name: str
    timestamps: np.ndarray
    samples: np.ndarray
    unit: str


class MF4Reader:
    """Loads and caches MF4 files; provides channel enumeration and data access."""

    def __init__(self) -> None:
        # Maps absolute path string -> open MDF instance
        self._cache: dict[str, MDF] = {}

    # ------------------------------------------------------------------
    # File management
    # ------------------------------------------------------------------

    def load_file(self, path: str | Path) -> MDF:
        """Return a cached MDF handle, opening the file if necessary."""
        key = str(Path(path).resolve())
        if key not in self._cache:
            _log.info("Opening MDF file: %s", key)
            try:
                self._cache[key] = MDF(key)
                _log.info("MDF opened OK: %d groups", len(self._cache[key].groups))
            except Exception:
                _log.exception("Failed to open MDF file: %s", key)
                raise
        return self._cache[key]

    def unload_file(self, path: str | Path) -> None:
        key = str(Path(path).resolve())
        if key in self._cache:
            mdf = self._cache.pop(key)
            mdf.close()

    def is_loaded(self, path: str | Path) -> bool:
        return str(Path(path).resolve()) in self._cache

    def inject(self, resolved_path: str, mdf: MDF) -> None:
        """Store a pre-opened MDF handle in the cache (used after threaded loading)."""
        self._cache[resolved_path] = mdf

    def close_all(self) -> None:
        for mdf in self._cache.values():
            mdf.close()
        self._cache.clear()

    # ------------------------------------------------------------------
    # Measurement metadata
    # ------------------------------------------------------------------

    def get_file_start_time(self, path: str | Path) -> float:
        """Return the measurement start time as Unix epoch seconds.

        Returns 0.0 if the file has no start-time information.
        """
        mdf = self.load_file(path)
        dt = getattr(mdf, "start_time", None)
        if dt is None:
            return 0.0
        try:
            return dt.timestamp()
        except Exception:
            return 0.0

    # ------------------------------------------------------------------
    # Channel discovery
    # ------------------------------------------------------------------

    def get_channel_list(self, path: str | Path) -> list[ChannelInfo]:
        """Return all readable channels in the file (de-duplicated by name+group)."""
        mdf = self.load_file(path)
        channels: list[ChannelInfo] = []
        seen: set[tuple[str, int]] = set()

        for group_idx, group in enumerate(mdf.groups):
            for ch_idx, ch in enumerate(group.channels):
                name = getattr(ch, "name", None)
                if not name:
                    continue
                key = (name, group_idx)
                if key in seen:
                    continue
                seen.add(key)
                channels.append(
                    ChannelInfo(
                        name=name,
                        group_index=group_idx,
                        channel_index=ch_idx,
                        unit=getattr(ch, "unit", "") or "",
                        comment=getattr(ch, "comment", "") or "",
                    )
                )

        return channels

    # ------------------------------------------------------------------
    # Data access
    # ------------------------------------------------------------------

    def read_signal(
        self,
        path: str | Path,
        channel_name: str,
        group_index: Optional[int] = None,
        channel_index: Optional[int] = None,
    ) -> SignalData:
        """Read timestamps and samples for a single channel."""
        mdf = self.load_file(path)
        kwargs: dict = {}
        if group_index is not None:
            kwargs["group"] = group_index
        if channel_index is not None:
            kwargs["index"] = channel_index

        _log.debug("read_signal %s group=%s index=%s", channel_name, group_index, channel_index)
        try:
            sig = mdf.get(channel_name, **kwargs)
        except Exception:
            _log.exception("mdf.get failed for channel '%s'", channel_name)
            raise
        return SignalData(
            name=channel_name,
            timestamps=np.asarray(sig.timestamps, dtype=float),
            samples=np.asarray(sig.samples, dtype=float),
            unit=sig.unit or "",
        )
