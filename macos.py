from __future__ import annotations

import faulthandler
import os
import subprocess
import sys
import threading
import time
import webbrowser
from typing import Any, Optional

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = ImageDraw = ImageFont = None


def render_app_icon(size: int):
    from utils.icon import render_icon

    return render_icon(size)


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "--render-app-icon":
    if Image is None:
        raise SystemExit("Pillow is required to render the macOS app icon")
    output_path = sys.argv[2] if len(sys.argv) > 2 else "icon.icns"
    render_app_icon(1024).save(output_path, format="ICNS")
    raise SystemExit(0)

try:
    import pyperclip
except ImportError:
    pyperclip = None

try:
    import pystray
except ImportError:
    pystray = None

try:
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
except ImportError:
    NSApplication = None
    NSApplicationActivationPolicyAccessory = None

from proxy import get_link_host
from ui.i18n import set_language, t
from ui.qt.qt_dialogs import QtDialog, ask_qt_yes_no, show_qt_error, show_qt_info
from ui.qt.qt_form import (
    install_tray_config_buttons,
    install_tray_config_form,
    populate_first_run_window,
    tray_settings_scroll_and_footer,
    validate_config_form,
)
from ui.qt.qt_runtime import apply_qt_appearance, ensure_qt_thread, qt_run_dialog, quit_qt
from ui.qt.qt_theme import qt_theme_for_platform
from utils.tray_common import (
    APP_DIR,
    APP_NAME,
    DEFAULT_CONFIG,
    FIRST_RUN_MARKER,
    LOG_FILE,
    acquire_lock,
    bootstrap,
    check_ipv6_warning,
    ensure_dirs,
    load_config,
    load_icon,
    log,
    maybe_notify_update,
    release_lock,
    restart_proxy,
    save_config,
    start_proxy,
    stop_proxy,
    tg_proxy_url,
)

CONFIG_DIALOG_SIZE = (460, 560)
CONFIG_DIALOG_FRAME_PAD = (20, 14)
FIRST_RUN_SIZE = (520, 480)

_tray_icon: Optional[Any] = None
_ns_app: Optional[Any] = None
_config: dict = {}
_exiting = False
_crash_log: Optional[Any] = None
_icon_path: Optional[str] = None


def _activate_app() -> None:
    if _ns_app is not None:
        try:
            _ns_app.activateIgnoringOtherApps_(True)
        except Exception as exc:
            log.warning("Failed to activate macOS app: %s", repr(exc))


def _qt_icon_path() -> Optional[str]:
    """Render the app icon once and return a cached temp PNG for Qt windows."""
    global _icon_path
    if _icon_path:
        return _icon_path
    try:
        import tempfile

        _icon_path = os.path.join(tempfile.gettempdir(), "swiftproxy-icon.png")
        render_app_icon(256).save(_icon_path)
        return _icon_path
    except Exception as exc:
        log.warning("Failed to render Qt window icon: %s", repr(exc))
        return None


def _show_error(text: str, title: Optional[str] = None) -> None:
    show_qt_error(None, text, title or t("app.error_title"))


def _show_info(text: str, title: Optional[str] = None) -> None:
    show_qt_info(None, text, title or t("app.name"))


def _ask_yes_no(text: str, title: Optional[str] = None) -> bool:
    return ask_qt_yes_no(None, text, title or t("app.name"))


def _refresh_tray_menu() -> None:
    if _tray_icon is None:
        return
    _tray_icon.menu = _build_menu()
    try:
        _tray_icon.update_menu()
    except Exception as exc:
        log.warning("Failed to refresh tray menu: %s", repr(exc))


def _on_open_in_telegram(icon=None, item=None) -> None:
    url = tg_proxy_url(_config)
    log.info("Opening %s", url)
    try:
        if subprocess.call(["open", url]) != 0:
            raise OSError("open command failed")
    except OSError:
        try:
            if not webbrowser.open(url):
                raise OSError("webbrowser.open returned False")
        except OSError:
            try:
                if pyperclip is not None:
                    pyperclip.copy(url)
                else:
                    subprocess.run(["pbcopy"], input=url.encode(), check=True)
                _show_info(t("dialog.open_tg_fail_clipboard", url=url))
            except (OSError, subprocess.SubprocessError) as exc:
                _show_error(t("dialog.copy_fail", error=exc))


def _on_copy_link(icon=None, item=None) -> None:
    url = tg_proxy_url(_config)
    try:
        if pyperclip is not None:
            pyperclip.copy(url)
        else:
            subprocess.run(["pbcopy"], input=url.encode(), check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        _show_error(t("dialog.copy_fail", error=exc))


def _on_restart(icon=None, item=None) -> None:
    threading.Thread(
        target=lambda: restart_proxy(_config, _show_error),
        daemon=True,
        name="proxy-restart",
    ).start()


def _on_edit_config(icon=None, item=None) -> None:
    threading.Thread(target=_edit_config_dialog, daemon=True).start()


def _on_open_logs(icon=None, item=None) -> None:
    if LOG_FILE.exists():
        try:
            subprocess.run(["open", str(LOG_FILE)], check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            _show_error(t("dialog.log_open_fail", error=exc))
    else:
        _show_info(t("dialog.log_not_found"))


def _finish_exit() -> None:
    global _exiting
    if _exiting:
        return
    _exiting = True
    log.info("User requested exit")
    if _tray_icon is not None:
        try:
            _tray_icon.stop()
        except Exception as exc:
            log.warning("Failed to stop tray icon: %s", repr(exc))
    quit_qt()


def _on_exit(icon=None, item=None) -> None:
    if _exiting:
        return
    _finish_exit()


def _edit_config_dialog() -> None:
    if not ensure_qt_thread(_config.get("appearance", "auto")):
        _show_error(t("dialog.qt_missing"))
        return

    cfg = dict(_config)

    def _build(done: threading.Event) -> None:
        from PySide6.QtWidgets import QScrollArea

        theme = qt_theme_for_platform()
        w, h = CONFIG_DIALOG_SIZE

        _skip_restore = {"v": False}

        def _restore() -> None:
            if _skip_restore["v"]:
                return
            apply_qt_appearance(_original_appearance)
            _restore_ui_locale()

        dlg = QtDialog(
            title=t("app.settings_title"), width=w, height=h, theme=theme,
            topmost=False, icon_path=_qt_icon_path(),
            on_close=lambda: (_restore(), done.set()),
        )

        def _refresh_tray_menu() -> None:
            if _tray_icon is not None:
                _tray_icon.menu = _build_menu()

        lay = dlg.content_frame(padx=CONFIG_DIALOG_FRAME_PAD[0], pady=CONFIG_DIALOG_FRAME_PAD[1])

        content, footer = tray_settings_scroll_and_footer(theme)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        lay.addWidget(scroll, 1)
        lay.addWidget(footer)

        _original_language = _config.get("language", DEFAULT_CONFIG["language"])

        widgets = install_tray_config_form(
            content, theme, cfg, DEFAULT_CONFIG,
            show_autostart=False,
            on_language_change=_refresh_tray_menu,
        )

        _original_appearance = cfg.get("appearance", "auto")

        def _restore_ui_locale() -> None:
            set_language(_original_language)
            _refresh_tray_menu()

        def _finish() -> None:
            _skip_restore["v"] = True
            dlg.close()

        def _cancel() -> None:
            dlg.close()

        def on_save() -> None:
            merged = validate_config_form(widgets, DEFAULT_CONFIG, include_autostart=False)
            if isinstance(merged, str):
                show_qt_error(dlg, merged)
                return

            merged["force_test_dc"] = _config.get("force_test_dc", DEFAULT_CONFIG["force_test_dc"])

            ui_only_keys = {"appearance", "check_updates", "language"}
            config_changed = any(merged.get(k) != _config.get(k) for k in merged)
            proxy_changed = any(
                merged.get(k) != _config.get(k)
                for k in merged
                if k not in ui_only_keys
            )

            if not config_changed:
                _restore_ui_locale()
                _finish()
                return

            save_config(merged)
            _config.update(merged)
            set_language(merged.get("language", DEFAULT_CONFIG["language"]))
            log.info("Config saved: %s", merged)
            _refresh_tray_menu()

            if not proxy_changed:
                _finish()
                return

            do_restart = ask_qt_yes_no(
                dlg,
                t("dialog.restart_body"),
                t("dialog.restart_title"),
            )
            _finish()
            if do_restart:
                threading.Thread(
                    target=lambda: restart_proxy(_config, _show_error),
                    daemon=True,
                    name="proxy-restart",
                ).start()

        install_tray_config_buttons(footer, theme, on_save=on_save, on_cancel=_cancel)

        dlg.show()
        dlg.start_entrance()
        dlg.raise_()
        dlg.activateWindow()
        _activate_app()

    qt_run_dialog(_build)


def _show_first_run() -> None:
    ensure_dirs()
    if FIRST_RUN_MARKER.exists():
        check_ipv6_warning(_show_info)
        return
    if not ensure_qt_thread(_config.get("appearance", "auto")):
        FIRST_RUN_MARKER.touch()
        return

    host = _config.get("host", DEFAULT_CONFIG["host"])
    port = _config.get("port", DEFAULT_CONFIG["port"])
    secret = _config.get("secret", DEFAULT_CONFIG["secret"])

    def _build(done: threading.Event) -> None:
        theme = qt_theme_for_platform()
        w, h = FIRST_RUN_SIZE
        dlg = QtDialog(
            title=t("app.name"), width=w, height=h, theme=theme,
            topmost=False, icon_path=_qt_icon_path(),
            on_close=done.set,
        )

        def on_done(open_telegram: bool) -> None:
            FIRST_RUN_MARKER.touch()
            dlg.close()
            if open_telegram:
                _on_open_in_telegram()
            check_ipv6_warning(_show_info)

        populate_first_run_window(dlg, theme, host=host, port=port, secret=secret, on_done=on_done)

        dlg.show()
        dlg.start_entrance()
        dlg.raise_()
        dlg.activateWindow()
        _activate_app()

    qt_run_dialog(_build)


def _build_menu():
    if pystray is None:
        return None
    host = _config.get("host", DEFAULT_CONFIG["host"])
    port = _config.get("port", DEFAULT_CONFIG["port"])
    link_host = get_link_host(host)
    return pystray.Menu(
        pystray.MenuItem(
            t("tray.open_telegram", host=link_host, port=port),
            _on_open_in_telegram,
            default=True,
        ),
        pystray.MenuItem(t("tray.copy_link"), _on_copy_link),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(t("tray.restart"), _on_restart),
        pystray.MenuItem(t("tray.settings"), _on_edit_config),
        pystray.MenuItem(t("tray.logs"), _on_open_logs),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(t("tray.exit"), _on_exit),
    )


def _initialize_gui() -> bool:
    global _ns_app
    if pystray is None or Image is None or NSApplication is None:
        return False
    if not ensure_qt_thread(_config.get("appearance", "auto")):
        return False
    _ns_app = NSApplication.sharedApplication()
    if NSApplicationActivationPolicyAccessory is not None:
        _ns_app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    return True


def _enable_crash_log() -> None:
    global _crash_log
    try:
        ensure_dirs()
        _crash_log = open(APP_DIR / "crash.log", "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=_crash_log, all_threads=True)
    except OSError as exc:
        log.warning("Failed to enable crash log: %s", repr(exc))


def run_tray() -> None:
    global _tray_icon, _config
    _config = load_config()
    bootstrap(_config)
    _enable_crash_log()

    if not _initialize_gui():
        log.error("PySide6, pystray, Pillow or AppKit not installed; running in console mode")
        start_proxy(_config, _show_error)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop_proxy()
        return

    start_proxy(_config, _show_error)
    _tray_icon = pystray.Icon(
        APP_NAME,
        load_icon(),
        t("app.name"),
        menu=_build_menu(),
        darwin_nsapplication=_ns_app,
    )
    _tray_icon.run_detached()
    maybe_notify_update(_config, lambda: _exiting, _ask_yes_no)
    _show_first_run()
    log.info("Tray icon running")

    if NSApplication is not None:
        _ns_app.run()

    stop_proxy()
    log.info("Tray app exited")


def _standalone_info(text: str) -> None:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo(t("app.name"), text, parent=root)
    root.destroy()


def main() -> None:
    if not acquire_lock():
        _standalone_info(t("dialog.already_running"))
        return
    try:
        run_tray()
    finally:
        release_lock()


if __name__ == "__main__":
    main()