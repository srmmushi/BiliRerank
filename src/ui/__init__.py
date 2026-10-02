"""UI layer, built on PyQt5 + PyQt-SiliconUI.

`import siui` has to happen before the QApplication exists: the library reads
the Windows DPI and exports QT_SCALE_FACTOR at import time, so importing it late
would leave Qt unscaled.
"""

try:
    import siui  # noqa: F401
except ImportError as exc:      # pragma: no cover - only when the dep is missing
    raise ImportError(
        "PyQt-SiliconUI is required. Install it with:\n"
        "    python -m pip install PyQt5\n"
        "    python -m pip install ./third_party/PyQt-SiliconUI"
    ) from exc

from .app import MainWindow, main  # noqa: E402  (after the siui import on purpose)

__all__ = ["MainWindow", "main"]
