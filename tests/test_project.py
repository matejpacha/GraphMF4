"""Unit tests for ProjectConfig serialization / deserialization."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

# Add src/ to path so imports work without installing the package
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


from core.project import (
    ChannelConfig,
    GraphConfig,
    ProjectConfig,
    PROJECT_FILE_EXTENSION,
    PROJECT_VERSION,
)


class TestChannelConfig:
    def test_label_defaults_to_channel_name(self):
        ch = ChannelConfig(file_path="/data/test.mf4", channel_name="Speed")
        assert ch.label == "Speed"

    def test_explicit_label_preserved(self):
        ch = ChannelConfig(file_path="/data/test.mf4", channel_name="Speed", label="Vehicle Speed")
        assert ch.label == "Vehicle Speed"

    def test_default_values(self):
        ch = ChannelConfig(file_path="/f.mf4", channel_name="X")
        assert ch.y_scale == 1.0
        assert ch.y_offset == 0.0
        assert ch.visible is True


class TestProjectConfigRoundTrip:
    def _sample_project(self) -> ProjectConfig:
        ch = ChannelConfig(
            file_path="/data/recording.mf4",
            channel_name="Engine_RPM",
            group_index=0,
            channel_index=2,
            color="#ff0000",
            y_scale=0.1,
            y_offset=-5.0,
            label="RPM",
        )
        graph = GraphConfig(
            id="graph-001",
            title="Engine",
            channels=[ch],
            x_range=[0.0, 60.0],
            y_range=[0.0, 8000.0],
            show_legend=True,
        )
        return ProjectConfig(
            name="Test Project",
            graphs=[graph],
            mf4_files=["/data/recording.mf4"],
        )

    def test_to_dict_from_dict_roundtrip(self):
        project = self._sample_project()
        restored = ProjectConfig.from_dict(project.to_dict())

        assert restored.name == project.name
        assert restored.version == PROJECT_VERSION
        assert len(restored.graphs) == 1
        g = restored.graphs[0]
        assert g.title == "Engine"
        assert g.x_range == [0.0, 60.0]
        assert len(g.channels) == 1
        ch = g.channels[0]
        assert ch.channel_name == "Engine_RPM"
        assert ch.y_scale == 0.1
        assert ch.label == "RPM"

    def test_save_and_load(self, tmp_path):
        project = self._sample_project()
        save_path = tmp_path / "project.gmf4proj"
        project.save(save_path)

        assert save_path.exists()
        loaded = ProjectConfig.load(save_path)
        assert loaded.name == project.name
        assert len(loaded.graphs) == 1
        assert loaded.graphs[0].channels[0].color == "#ff0000"

    def test_save_adds_extension_if_missing(self, tmp_path):
        project = self._sample_project()
        save_path = tmp_path / "no_extension"
        project.save(save_path)
        expected = tmp_path / f"no_extension{PROJECT_FILE_EXTENSION}"
        assert expected.exists()

    def test_empty_project_serializes(self):
        p = ProjectConfig()
        d = p.to_dict()
        restored = ProjectConfig.from_dict(d)
        assert restored.graphs == []
        assert restored.mf4_files == []

    def test_json_is_human_readable(self, tmp_path):
        project = self._sample_project()
        save_path = tmp_path / "readable.gmf4proj"
        project.save(save_path)
        text = save_path.read_text(encoding="utf-8")
        # Should be pretty-printed JSON with indentation
        assert "\n" in text
        assert "Engine_RPM" in text
