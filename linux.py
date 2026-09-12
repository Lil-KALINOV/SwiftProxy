from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from typing import Optional

import pyperclip
import pystray
from PIL import Image

from proxy import get_link_host

from utils.tray_common import (
    APP_NAME, DEFAULT_CONFIG, FIRST_RUN_MARKER, LOG_FILE,
    acquire_lock, bootstrap, check_ipv6_warning, ensure_dirs, load_config,
    load_icon, log, maybe_notify_update, release_lock, restart_proxy,
    save_config, start_proxy, stop_proxy, tg_proxy_url,
)
from ui.qt.qt_dialogs import QtDialog, ask_qt_yes_no, show_qt_error, show_qt_info
from ui.qt.qt_form import (
    install_tray_config_buttons, install_tray_config_form,
    populate_first_run_window, tray_settings_scroll_and_footer,
    validate_config_form,
)
from ui.qt.qt_runtime import (
    apply_qt_appearance, ensure_qt_thread, qt_run_dialog, quit_qt,
)
from ui.qt.qt_theme import qt_theme_for_platform
from ui.i18n import set_language, t

CONFIG_DIALOG_SIZE = (460, 560)
CONFIG_DIALOG_FRAME_PAD = (20, 14)
FIRST_RUN_SIZE = (520, 480)

_tray_icon: Optional[object] = None
_config: dict = {}
_exiting = False


# dialogs (Qt message boxes)


def _show_error(text: str, title: Optional[str] = None) -> None:
    show_qt_error(None, text, title or t("app.error_title"))


def _show_info(text: str, title: Optional[str] = None) -> None:
    show_qt_info(None, text, title or t("app.name"))


def _ask_yes_no(text: str, title: Optional[str] = None) -> bool:
    return ask_qt_yes_no(None, text, title or t("app.name"))


# tray callbacks


def _on_open_in_telegram(icon=None, item=None) -> None:
    url = tg_proxy_url(_config)
    log.info("Copying %s", url)
    try:
        pyperclip.copy(url)
        _show_info(t("dialog.copy_ok", url=url))
    except Exception as exc:
        log.error("Clipboard copy failed: %s", exc)
        _show_error(t("dialog.copy_fail", error=exc))


def _on_copy_link(icon=None, item=None) -> None:
    url = tg_proxy_url(_config)
    log.info("Copying link: %s", url)
    try:
        pyperclip.copy(url)
    except Exception as exc:
        log.error("Clipboard copy failed: %s", exc)
        _show_error(t("dialog.copy_fail", error=exc))


def _on_restart(icon=None, item=None) -> None:
    threading.Thread(
        target=lambda: restart_proxy(_config, _show_error), daemon=True
    ).start()


def _on_edit_config(icon=None, item=None) -> None:
    threading.Thread(target=_edit_config_dialog, daemon=True).start()


def _on_open_logs(icon=None, item=None) -> None:
    log.info("Opening log file: %s", LOG_FILE)
    if LOG_FILE.exists():
        env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME")}
        subprocess.Popen(
            ["xdg-open", str(LOG_FILE)], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    else:
        _show_info(t("dialog.log_not_found"))


def _on_exit(icon=None, item=None) -> None:
    global _exiting
    if _exiting:
        os._exit(0)
        return
    _exiting = True
    log.info("User requested exit")
    quit_qt()
    threading.Thread(target=lambda: (time.sleep(3), os._exit(0)), daemon=True, name="force-exit").start()
    if icon:
        icon.stop()


# settings dialog


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
            topmost=False,
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
            proxy_changed = any(merged.get(k) != _config.get(k) for k in merged if k not in ui_only_keys)

            if not config_changed:
                _restore_ui_locale()
                _finish()
                return

            save_config(merged)
            _config.update(merged)
            set_language(merged.get("language", DEFAULT_CONFIG["language"]))
            log.info("Config saved: %s", merged)
            _tray_icon.menu = _build_menu()

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
                threading.Thread(target=lambda: restart_proxy(_config, _show_error), daemon=True).start()

        install_tray_config_buttons(footer, theme, on_save=on_save, on_cancel=_cancel)

        dlg.show()
        dlg.start_entrance()
        dlg.raise_()
        dlg.activateWindow()

    qt_run_dialog(_build)


# first run


def _show_first_run() -> None:
    ensure_dirs()
    if FIRST_RUN_MARKER.exists():
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
            topmost=False,
            on_close=done.set,
        )

        def on_done(open_tg: bool) -> None:
            FIRST_RUN_MARKER.touch()
            dlg.close()
            if open_tg:
                _on_open_in_telegram()

        populate_first_run_window(dlg, theme, host=host, port=port, secret=secret, on_done=on_done)

        dlg.show()
        dlg.start_entrance()
        dlg.raise_()
        dlg.activateWindow()

    qt_run_dialog(_build)


# tray menu


def _build_menu():
    host = _config.get("host", DEFAULT_CONFIG["host"])
    port = _config.get("port", DEFAULT_CONFIG["port"])
    link_host = get_link_host(host)
    return pystray.Menu(
        pystray.MenuItem(t("tray.open_telegram", host=link_host, port=port), _on_open_in_telegram, default=True),
        pystray.MenuItem(t("tray.copy_link"), _on_copy_link),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(t("tray.restart"), _on_restart),
        pystray.MenuItem(t("tray.settings"), _on_edit_config),
        pystray.MenuItem(t("tray.logs"), _on_open_logs),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(t("tray.exit"), _on_exit),
    )


# entry point


def run_tray() -> None:
    global _tray_icon, _config

    _config = load_config()
    bootstrap(_config)

    if pystray is None or Image is None:
        log.error("pystray or Pillow not installed; running in console mode")
        start_proxy(_config, _show_error)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop_proxy()
        return

    start_proxy(_config, _show_error)
    maybe_notify_update(_config, lambda: _exiting, _ask_yes_no)
    _show_first_run()
    check_ipv6_warning(_show_info)

    _tray_icon = pystray.Icon(APP_NAME, load_icon(), t("app.name"), menu=_build_menu())
    log.info("Tray icon running")
    _tray_icon.run()

    stop_proxy()
    log.info("Tray app exited")


def _smoke_test() -> None:
    """Exercise the frozen GUI stack without starting the proxy or writing config."""
    import gi

    gi.require_version('AppIndicator3', '0.1')
    gi.require_version('AyatanaAppIndicator3', '0.1')
    from gi.repository import AppIndicator3, AyatanaAppIndicator3

    # Namespace imports alone do not resolve app_indicator_new: call it too.
    indicators = [
        namespace.Indicator.new(
            'swift-proxy-smoke-test', '', namespace.IndicatorCategory.APPLICATION_STATUS,
        )
        for namespace in (AppIndicator3, AyatanaAppIndicator3)
    ]
    icon = pystray.Icon('swift-proxy-smoke-test', Image.new('RGB', (16, 16)))
    root = ensure_qt_thread('auto')
    assert root

    # A successful constructor on the build host can hide missing bundled
    # libraries. Check where the dynamic loader actually obtained them.
    bundle_dir = os.path.realpath(sys._MEIPASS) + os.sep
    prefixes = ('libglib-', 'libgobject-', 'libgio-', 'libgtk-',
                'libappindicator', 'libayatana-', 'libdbusmenu-')
    with open('/proc/self/maps', encoding='utf-8') as maps:
        paths = {line.split(maxsplit=5)[-1].strip() for line in maps}
    for path in sorted(paths):
        if os.path.basename(path).startswith(prefixes):
            if not os.path.realpath(path).startswith(bundle_dir):
                raise RuntimeError('GUI library loaded outside the bundle: ' + path)
            print(path)
    assert icon is not None and all(indicators)

    def _build(done: threading.Event) -> None:
        dlg = QtDialog(title='smoke', width=320, height=200, theme=qt_theme_for_platform())
        dlg.show()
        done.set()

    qt_run_dialog(_build)
    print('Linux bundle smoke test passed')


def main() -> None:
    if sys.argv[1:] == ['--smoke-test']:
        _smoke_test()
        return
    if not acquire_lock():
        _show_info(t("dialog.already_running"), os.path.basename(sys.argv[0]))
        return
    try:
        run_tray()
    finally:
        release_lock()


if __name__ == "__main__":
    main()