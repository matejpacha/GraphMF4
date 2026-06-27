"""Project data models with JSON serialization.

The project file (*.gmf4proj) stores:
  - Paths to MF4 files
  - Graph configurations (channels, view ranges, legend state)
  - Channel configurations (color, scale, offset, visibility)
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

PROJECT_FILE_EXTENSION = ".gmf4proj"
PROJECT_VERSION = "1.0"

# Default color cycle (matches matplotlib tab10)
DEFAULT_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]


@dataclass
class ChannelConfig:
    """Configuration for a single signal/channel in a graph."""

    file_path: str
    channel_name: str
    group_index: int = 0
    channel_index: int = 0
    color: str = ""          # empty = let GraphWidget assign via _next_color()
    y_scale: float = 1.0
    y_offset: float = 0.0
    visible: bool = True
    label: str = ""

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.channel_name


@dataclass
class GraphConfig:
    """Configuration for one graph panel."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = "Graph"
    channels: list[ChannelConfig] = field(default_factory=list)
    x_range: Optional[list[float]] = None   # [x_min, x_max], None = auto-fit
    y_range: Optional[list[float]] = None   # [y_min, y_max], None = auto-fit
    show_legend: bool = True
    legend_position: str = "top-right"
    x_label: str = "Time [s]"
    y_label: str = ""
    win_geometry: Optional[list[int]] = None   # [x, y, width, height] in MDI coords
    x_axis_mode: str = "relative"              # "relative" | "absolute"


@dataclass
class ProjectConfig:
    """Root project model serialized to/from the .gmf4proj file."""

    version: str = PROJECT_VERSION
    name: str = "Unnamed Project"
    graphs: list[GraphConfig] = field(default_factory=list)
    mf4_files: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectConfig":
        graphs = [
            GraphConfig(
                **{
                    **{k: v for k, v in g.items() if k != "channels"},
                    "channels": [ChannelConfig(**c) for c in g.get("channels", [])],
                }
            )
            for g in data.get("graphs", [])
        ]
        return cls(
            version=data.get("version", PROJECT_VERSION),
            name=data.get("name", "Unnamed Project"),
            graphs=graphs,
            mf4_files=data.get("mf4_files", []),
        )

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> None:
        path = Path(path)
        if path.suffix.lower() != PROJECT_FILE_EXTENSION:
            path = path.with_suffix(PROJECT_FILE_EXTENSION)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: str | Path) -> "ProjectConfig":
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return cls.from_dict(data)
