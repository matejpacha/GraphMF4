Version 1.0.11
🚀 New Features


Dockable Channel Panel

Added a dedicated channel management dock with support for:

Drag-and-drop channel reordering
Visibility control
Quick channel editing
Digital channel stacking
Direct signal drop support


Panel visibility can be toggled from the View menu (Ctrl+Shift+P).



Signal Browser

Added a dockable Signal Browser (Ctrl+Shift+B) for browsing all available signals across loaded MF4/MDF files.
Supports:

File selection
Signal filtering
Double-click to add signals to the active graph
Drag-and-drop of signals directly into graphs or channel panels





Interactive Value Cursor

Added a synchronized graph cursor displaying interpolated signal values at any time position.
Cursor labels automatically avoid overlapping.
Cursor position can be synchronized across multiple graphs.



Delta Cursor (Δ Cursor)

Added a second cursor for measuring time and signal differences.
Displays:

Δt (time difference)
Per-channel ΔY values


Synchronizes across graphs when X-axis synchronization is enabled.



Optional Signal Labels

New Labels toggle displays signal names directly on the graph.
Labels automatically reposition during pan and zoom operations to remain readable.



Dark Theme

Added application-wide dark theme support (Ctrl+Shift+D).
Includes matching plot backgrounds, axis styling, and MDI area appearance.
Theme preference is remembered between sessions.



Multi-Document Interface (MDI)

Graphs now run inside movable and resizable MDI subwindows.
Layout and window geometry are saved with the project.
Added layout commands:

Stack Vertically
Tile
Cascade





Recent Projects

Added a Recent Projects menu that stores and displays the last 10 opened projects.
Missing project files are clearly marked.
Includes a one-click Clear Recent option.



MF4 File Replacement

Added Replace MF4 File... functionality.
Automatically remaps matching channels to a new data file while preserving graph layouts and settings.




⚡ Performance Improvements


Large File Loading

MF4 file loading now runs in a background worker thread.
Added progress indication for long-running operations.
Improved application responsiveness during file loading.



LTTB Downsampling

Added Largest-Triangle-Three-Buckets (LTTB) downsampling.
Configurable through Help → Settings.
Helps maintain responsiveness when plotting large datasets.



Rendering Optimizations

Enabled clipToView for faster rendering of zoomed-in signals.
Added pyqtgraph automatic peak-preserving downsampling.
Increased LTTB output resolution to improve zoom detail.



Optional OpenGL Rendering

Added OpenGL rendering option in application settings.
Can improve rendering performance on supported hardware.




📊 Signal Visualization Enhancements


Added support for Digital Signals:

Step-wave rendering.
Automatic lane stacking of multiple digital channels.
Digital signal configuration from the channel editor.



Added Ctrl + Left Mouse Drag rubber-band zoom.


Improved graph interaction tooltips and usability.


Added synchronized X-axis navigation across multiple graphs.



🛠 Usability Improvements

Added graph title renaming by double-clicking the title.
Added busy cursor feedback during signal browsing operations.
Added toolbar icons for common actions.
Improved missing-file handling when opening projects:

Missing MF4 files can be relocated using a dedicated dialog.
Project references are automatically updated.




🔧 Reliability & Stability


Added comprehensive file-based logging to:

Application startup
MF4 loading
Signal reading
Plotting operations
Unhandled exceptions



Improved channel metadata loading:

Channel enumeration no longer requires signal data decoding.
Prevents channels from disappearing when data decoding fails.



Added automatic signal lookup fallback:

If channel group/index information becomes invalid, GraphMF4 can fall back to name-based signal resolution.



Improved PyInstaller packaging support for CAN database decoding via canmatrix.


Expanded support for both MDF 3.x and MDF 4.x files regardless of file extension.



💾 Project & Workflow Improvements

Graph layout, size, and position are now persisted within project files.
Added synchronization of graph state before project save.
Added Windows file association support for .gmf4proj project files.
Enhanced project portability and missing-file recovery workflows.


✅ Fixed

Fixed cursor label auto-range feedback loop that could cause infinite scrolling and unstable graph behavior.
Fixed several plotting and signal-loading edge cases by adding extensive exception handling and diagnostics.
Improved channel loading reliability for corrupted or partially reprocessed MF4 files.
Improved graph synchronization logic to prevent recursive update loops during cursor and X-axis synchronization.


📦 Technical Highlights

Dockable channel and signal browser panels
Drag-and-drop signal management
Synchronized cursors and X-axes
Dark theme support
MDI graph workspace
LTTB downsampling
OpenGL rendering option
Digital signal visualization
Recent projects management
Enhanced logging and diagnostics
MDF3/MDF4 compatibility improvements

GraphMF4 continues to focus on providing a fast, responsive, and user-friendly environment for exploring and analyzing large MF4/MDF measurement datasets.
