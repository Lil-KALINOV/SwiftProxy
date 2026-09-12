"""Qt runtime bridge: QApplication in a daemon thread, same pattern as CTk.

The pystray loop owns the main thread; all Qt widgets must live in a single
Qt thread. Dialogs are scheduled onto that thread and the caller blocks on an
Event until the dialog closes.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable, Optional

log = logging.getLogger("swift-qt")

_qt_app: Any = None
_qt_ready = threading.Event()
_qt_queue: "queue.Queue[Callable[[], None]]" = queue.Queue()


def ensure_qt_thread(mode: str = "auto") -> bool:
    """Start the Qt event-loop thread (idempotent). Returns True on success."""
    global _qt_app
    if _qt_ready.is_set():
        return _qt_app is not None

    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is not None and _qt_app is None:
        _qt_app = QApplication.instance()

    def _run() -> None:
        global _qt_app
        from PySide6.QtCore import QTimer
        from ui.qt.qt_theme import apply_qt_palette, resolve_appearance, qt_theme_for_platform

        app: Any = QApplication.instance() or QApplication([])
        _qt_app = app
        app.setApplicationName("SwiftProxy")
        app.setQuitOnLastWindowClosed(False)

        theme = qt_theme_for_platform()
        appearance = resolve_appearance(mode, app)
        apply_qt_palette(app, theme, appearance)

        timer = QTimer()
        timer.setInterval(25)
        timer.timeout.connect(_drain)
        timer.start()

        _qt_ready.set()
        app.exec()

    threading.Thread(target=_run, daemon=True, name="qt-root").start()
    _qt_ready.wait(timeout=8.0)
    return _qt_app is not None


def _drain() -> None:
    while True:
        try:
            fn = _qt_queue.get_nowait()
        except queue.Empty:
            return
        try:
            fn()
        except Exception as exc:
            log.exception("Qt task failed: %s", repr(exc))


def on_qt_thread(fn: Callable[[], None]) -> None:
    """Schedule fn to run on the Qt thread, even from other threads."""
    _qt_queue.put(fn)


def qt_run_dialog(build_fn: Callable[[threading.Event], None]) -> None:
    """Run a dialog builder on the Qt thread and block until it finishes."""
    if _qt_app is None:
        return
    done = threading.Event()

    def _invoke() -> None:
        try:
            build_fn(done)
        except Exception:
            log.exception("Qt dialog failed")
            done.set()

    on_qt_thread(_invoke)
    done.wait()


def quit_qt() -> None:
    if _qt_app is not None:
        on_qt_thread(lambda: _qt_app.quit())


def qapp_thread() -> Optional[Any]:
    """Return the thread the QApplication lives on, or None."""
    app = _qt_app
    if app is None:
        return None
    return app.thread()


def is_qt_thread() -> bool:
    from PySide6.QtCore import QThread

    thread = qapp_thread()
    return thread is not None and QThread.currentThread() is thread


def on_qt_blocking(fn: Callable[[], Any], timeout: float = 30.0) -> Any:
    """Run fn on the Qt thread and block for its result. Callable from any thread."""
    if not is_qt_thread():
        if _qt_app is None:
            return None
        result = {}
        done = threading.Event()

        def _invoke() -> None:
            try:
                result["value"] = fn()
            except Exception:
                log.exception("Qt block task failed")
            finally:
                done.set()

        on_qt_thread(_invoke)
        done.wait(timeout)
        return result.get("value")
    return fn()


def apply_qt_appearance(mode: str) -> None:
    from PySide6.QtWidgets import QApplication
    from ui.qt.qt_theme import apply_qt_palette, qt_theme_for_platform, resolve_appearance
    app = QApplication.instance()
    if app is None:
        return
    theme = qt_theme_for_platform()
    apply_qt_palette(app, theme, resolve_appearance(mode, app))