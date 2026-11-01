"""Tests for main-window rendering setup."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pyqtgraph as pg
import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtOpenGLWidgets import QOpenGLWidget

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.mf4_reader import ChannelInfo
from core.project import ChannelConfig
from ui import channel_list_dock
from ui.main_window import MainWindow
from version import __version__


def test_opengl_surface_is_present_before_first_graph(qtbot):
    previous = pg.getConfigOption("useOpenGL")
    pg.setConfigOption("useOpenGL", True)
    try:
        window = MainWindow()
        qtbot.addWidget(window)

        assert window._graph_widgets == []
        assert isinstance(window._opengl_surface_anchor, QOpenGLWidget)
    finally:
        pg.setConfigOption("useOpenGL", previous)


def test_window_title_contains_application_version(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.windowTitle() == f"GraphMF4 v{__version__} – Unnamed Project"

    window._set_dirty(True)
    assert window.windowTitle() == f"GraphMF4 v{__version__} – Unnamed Project *"
    window._dirty = False


def test_signal_browser_grouping_and_filter(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    dock = window._signal_list_dock
    dock._all_channels = [
        ChannelInfo("Speed", 0, 1, "km/h", "", "EngineStatus", "Engine ECU"),
        ChannelInfo("RPM", 0, 2, "rpm", "", "EngineStatus", "Engine ECU"),
        ChannelInfo("Voltage", 1, 1, "V", ""),
    ]
    dock._group_combo.setCurrentIndex(1)
    tree = dock._list
    assert tree.topLevelItemCount() == 2
    assert tree.topLevelItem(0).text(0) == "EngineStatus"
    assert tree.topLevelItem(0).childCount() == 2
    assert tree.topLevelItem(1).text(0) == "Ostatní"
    dock._filter_edit.setText("speed")
    assert tree.topLevelItemCount() == 1
    assert tree.topLevelItem(0).childCount() == 1
    assert tree.topLevelItem(0).child(0).text(0) == "Speed  [km/h]"
    dock._group_combo.setCurrentIndex(2)
    assert tree.topLevelItem(0).text(0) == "Engine ECU"
    dock._filter_edit.clear()
    dock._group_combo.setCurrentIndex(0)
    assert tree.topLevelItemCount() == 3


@pytest.mark.parametrize("grouping", [0, 1, 2])
def test_double_click_adds_signal_to_selected_graph(qtbot, grouping):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window._add_graph()
    window._add_graph()
    window._dirty = False

    selected_graph = window._graph_widgets[1]
    window._mdi_area.setActiveSubWindow(window._widget_to_subwin[selected_graph])
    assert window._channel_dock._graph is selected_graph

    channel = ChannelInfo("VehicleSpeed", 1, 2, "km/h", "", "Motion", "ABS ECU")
    dock = window._signal_list_dock
    dock._current_file = "measurement.mf4"
    dock._all_channels = [channel]
    dock._group_combo.setCurrentIndex(grouping)
    dock._apply_filter("")
    item = dock._list.topLevelItem(0)
    if grouping:
        item = item.child(0)

    item_position = window._signal_list_dock._list.visualItemRect(item).center()
    qtbot.mouseClick(
        window._signal_list_dock._list.viewport(),
        Qt.MouseButton.LeftButton,
        pos=item_position,
    )
    qtbot.mouseDClick(
        window._signal_list_dock._list.viewport(),
        Qt.MouseButton.LeftButton,
        pos=item_position,
    )

    assert window._graph_widgets[0]._config.channels == []
    assert [ch.channel_name for ch in selected_graph._config.channels] == ["VehicleSpeed"]
    window._dirty = False


def test_channel_context_menu_removes_selected_signals(qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window._add_graph()
    window._dirty = False
    graph = window._graph_widgets[0]
    graph._config.channels = [
        ChannelConfig("measurement.mf4", "VehicleSpeed"),
        ChannelConfig("measurement.mf4", "EngineSpeed"),
    ]
    window._channel_dock.set_graph(graph)
    window._channel_dock._list.selectAll()

    class FakeAction:
        def __init__(self, text):
            self.text = text

    class FakeMenu:
        def __init__(self, _parent):
            self.actions = []

        def addAction(self, text):
            action = FakeAction(text)
            self.actions.append(action)
            return action

        def addSeparator(self):
            pass

        def exec(self, _pos):
            return next(action for action in self.actions if action.text == "Odstranit z grafu")

    monkeypatch.setattr(channel_list_dock, "QMenu", FakeMenu)
    window._channel_dock._on_context_menu(window._channel_dock._list.rect().center())

    assert graph._config.channels == []
    assert window._channel_dock._list.count() == 0
    window._dirty = False


def test_graph_window_move_snaps_to_neighbor(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window._add_graph()
    window._add_graph()
    window._dirty = False
    first, second = (window._widget_to_subwin[graph] for graph in window._graph_widgets)
    first.setGeometry(50, 50, 700, 300)
    second.setGeometry(900, 80, 700, 300)
    qtbot.wait(1)
    second.setGeometry(757, 80, 700, 300)
    qtbot.wait(1)

    assert second.x() == 750
    assert second.y() == 80


def test_graph_window_resize_snaps_dragged_edge_to_neighbor(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window._add_graph()
    window._add_graph()
    window._dirty = False
    first, second = (window._widget_to_subwin[graph] for graph in window._graph_widgets)
    first.setGeometry(50, 50, 700, 300)
    previous = QRect(850, 80, 700, 300)
    second.setGeometry(previous)
    qtbot.wait(1)
    second.setGeometry(757, 80, 793, 300)
    qtbot.wait(1)

    assert second.x() == 750
    assert second.width() == 800
    assert second.x() + second.width() == previous.x() + previous.width()
