"""Signal downsampling — Largest-Triangle-Three-Buckets (LTTB).

LTTB reduces the number of samples while preserving the visual shape of the
signal.  It is visually superior to simple stride-based thinning and runs in
O(n_out) time, making it cheap even for million-sample channels.

Reference: Steinarsson, S. (2013). Downsampling Time Series for Visual
           Representation. MSc thesis, University of Iceland.

Public API
----------
lttb(x, y, n_out, threshold) -> (x_out, y_out)
"""
from __future__ import annotations

import numpy as np

# Apply downsampling when the channel exceeds this many samples.
DOWNSAMPLE_THRESHOLD: int = 10_000

# Target output sample count.  5 000 gives good zoom detail; pyqtgraph's render-time
# auto-downsampling further reduces what's actually drawn to match screen pixel count.
DOWNSAMPLE_TARGET: int = 5_000


def lttb(
    x: np.ndarray,
    y: np.ndarray,
    n_out: int = DOWNSAMPLE_TARGET,
    threshold: int = DOWNSAMPLE_THRESHOLD,
) -> tuple[np.ndarray, np.ndarray]:
    """Downsample *x* / *y* to *n_out* points using LTTB.

    Returns the original arrays unchanged when ``len(x) <= threshold`` or
    when *n_out* is already >= len(x).

    Parameters
    ----------
    x, y:
        1-D arrays of equal length.  *x* must be monotonically increasing.
    n_out:
        Desired output length (including the mandatory first and last points).
    threshold:
        Minimum input length that triggers downsampling.

    Returns
    -------
    (x_out, y_out) — views or copies of the input arrays.
    """
    n = len(x)
    if n <= threshold or n_out >= n or n_out < 3:
        return x, y

    sampled = np.empty(n_out, dtype=np.intp)
    sampled[0] = 0
    sampled[-1] = n - 1

    # Size of each "current" bucket — floats so the boundary arithmetic is exact.
    bucket_size = (n - 2) / (n_out - 2)

    a = 0  # index of the last selected point

    for i in range(n_out - 2):
        # ── Current bucket ────────────────────────────────────────────────────
        cur_lo = int(i * bucket_size) + 1
        cur_hi = min(int((i + 1) * bucket_size) + 1, n - 1)

        # ── Next-bucket average (the "far vertex" of the LTTB triangle) ───────
        avg_lo = cur_hi
        avg_hi = min(int((i + 2) * bucket_size) + 1, n)
        # Clamp: last iteration's next bucket might be empty (use last point).
        if avg_lo >= avg_hi:
            avg_x = float(x[n - 1])
            avg_y = float(y[n - 1])
        else:
            avg_x = float(np.mean(x[avg_lo:avg_hi]))
            avg_y = float(np.mean(y[avg_lo:avg_hi]))

        # ── Triangle area (×2, sign dropped) for each point in current bucket ─
        ax = float(x[a])
        ay = float(y[a])
        bx = x[cur_lo:cur_hi]
        by = y[cur_lo:cur_hi]

        # Area = |( ax-avg_x)(by-ay) - (bx-ax)(avg_y-ay)| / 2
        # The /2 is omitted (monotonic with area → argmax is the same).
        area = np.abs((ax - avg_x) * (by - ay) - (bx - ax) * (avg_y - ay))

        a = int(np.argmax(area)) + cur_lo
        sampled[i + 1] = a

    return x[sampled], y[sampled]
