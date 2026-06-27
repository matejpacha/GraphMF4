# GraphMF4

Interactive MF4 signal viewer for Windows 10/11.

## Features

- Load and parse MF4 / MDF4 files via [asammdf](https://github.com/danielhrisca/asammdf)
- Browse all channels in a file with text filter
- Select individual channels and add them to interactive graphs
- Add multiple independent graph panels in one view
- **Zoom** on both axes — mouse wheel or drag
- **Pan** on both axes — middle-click drag or right-drag
- Toggle **legend** visibility per graph
- Per-channel: custom color, y-scale multiplier, y-offset, label
- **Export** each graph to PNG / BMP / JPEG
- **Save & load** project configuration (`.gmf4proj`) — stores file paths,
  selected channels, view state (zoom/pan ranges), and legend visibility

## Requirements

| | |
|-|-|
| OS | Windows 10 or 11 (64-bit) |
| Python | ≥ 3.11 |
| Libraries | See `requirements.txt` |

## Quick start

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run
python src/main.py

# (Optional) open a project directly
python src/main.py path\to\project.gmf4proj
```

## Project file format

Projects are saved as UTF-8 JSON with the `.gmf4proj` extension.
See [`src/core/project.py`](src/core/project.py) for the full schema.

```json
{
  "version": "1.0",
  "name": "My Project",
  "mf4_files": ["C:/data/recording.mf4"],
  "graphs": [
    {
      "id": "...",
      "title": "Engine",
      "channels": [
        {
          "file_path": "C:/data/recording.mf4",
          "channel_name": "Engine_RPM",
          "color": "#1f77b4",
          "y_scale": 1.0,
          "y_offset": 0.0,
          "label": "Engine RPM"
        }
      ],
      "x_range": [0.0, 60.0],
      "y_range": [0.0, 8000.0],
      "show_legend": true
    }
  ]
}
```

## Tech stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.11+ |
| GUI | PySide6 (Qt 6) |
| Interactive plots | pyqtgraph |
| MF4 I/O | asammdf |
| Numerics | NumPy |

## Development

```powershell
pip install -r requirements-dev.txt
pytest                  # run tests
black src tests         # format
ruff check src tests    # lint
```

## Project structure

```
src/
├── main.py                      Entry point
├── core/
│   ├── project.py               Data models + JSON serialization
│   ├── mf4_reader.py            MF4 file I/O (asammdf wrapper)
│   └── graph_model.py           Reserved for future graph-level logic
├── ui/
│   ├── main_window.py           Main window
│   ├── graph_widget.py          Single graph panel widget
│   └── signal_selector_dialog.py  Channel picker dialog
└── utils/
    └── export.py                Bitmap export
tests/
├── test_project.py
└── test_mf4_reader.py
```
