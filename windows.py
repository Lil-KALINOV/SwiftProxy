from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
import webbrowser
import winreg
import tempfile

from pathlib import Path
from typing import Optional
from proxy.utils import build_github_opener

try:
    import pyperclip
except ImportError:
    pyperclip = None

try:
    import pystray
except ImportError:
    pystray = None

try:
    from PIL import Image
except ImportError:
    Image = None

from proxy import __version__, get_link_host

from utils.win32_theme import (
    is_windows_dark_theme, 
    apply_windows_dark_theme,
)
from utils.tray_common import (
    APP_NAME, DEFAULT_CONFIG, FIRST_RUN_MARKER, IS_FROZEN, LOG_FILE,
    acquire_lock, bootstrap, check_ipv6_warning, ensure_dirs, load_config,
    load_icon, log, release_lock, restart_proxy,
    save_config, start_proxy, stop_proxy, tg_proxy_url,
)
from utils.update_check import (
    get_status, get_update_asset, run_check, RELEASES_PAGE_URL, 
)
from ui.qt.qt_runtime import ensure_qt_thread, qt_run_dialog, quit_qt
from ui.qt.qt_theme import qt_theme_for_platform
from ui.qt.qt_form import (
    install_tray_config_buttons, install_tray_config_form,
    populate_first_run_window,
    validate_config_form,
)
from ui.qt.qt_dialogs import (
    QtDialog, ask_qt_yes_no, show_qt_error,
)
from ui.i18n import set_language, t

CONFIG_DIALOG_SIZE = (480, 620)
CONFIG_DIALOG_FRAME_PAD = (20, 14)
FIRST_RUN_SIZE = (520, 480)

_tray_icon: Optional[object] = None
_config: dict = {}
_exiting = False
_win_mutex_handle = None
_update_flow_lock = threading.Lock()

_ERROR_ALREADY_EXISTS = 183


def _acquire_win_mutex() -> bool | None:
    global _win_mutex_handle
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        handle = kernel32.CreateMutexW(None, True, "Local\\SwiftProxy_SingleInstance")
        if kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            return False
        if not handle:
            return None
        _win_mutex_handle = handle
        return True
    except Exception:
        return None


def _release_win_mutex() -> None:
    global _win_mutex_handle
    if _win_mutex_handle:
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.ReleaseMutex(ctypes.c_void_p(_win_mutex_handle))
            kernel32.CloseHandle(ctypes.c_void_p(_win_mutex_handle))
        except Exception:
            pass
        _win_mutex_handle = None

ICON_PATH = str(Path(__file__).parent / "icon.ico")

# win32 dialogs

_u32 = ctypes.windll.user32
_u32.MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
_u32.MessageBoxW.restype = ctypes.c_int

_MB_OK_ERR = 0x10
_MB_OK_INFO = 0x40
_MB_YESNO_Q = 0x24
_MB_YESNOCANCEL_Q = 0x23
_IDYES = 6
_IDNO = 7


def _show_error(text: str, title: Optional[str] = None) -> None:
    _u32.MessageBoxW(None, text, title or t("app.error_title"), _MB_OK_ERR)


def _show_info(text: str, title: Optional[str] = None) -> None:
    _u32.MessageBoxW(None, text, title or t("app.name"), _MB_OK_INFO)


def _ask_yes_no(text: str, title: Optional[str] = None) -> bool:
    return _u32.MessageBoxW(None, text, title or t("app.name"), _MB_YESNO_Q) == _IDYES


def update_qt_form(
    text: str, title: Optional[str] = None, download_url: Optional[str] = None,
    release_url: Optional[str] = None,
) -> str:
    title = title or t("app.name")
    if not ensure_qt_thread(_config.get("appearance", "auto")):
        result = _u32.MessageBoxW(None, text, title, _MB_YESNOCANCEL_Q)
        if result == _IDYES:
            return "update"
        if result == _IDNO:
            return "open"
        return "close"

    result = {"value": "close"}

    def _build(done: threading.Event) -> None:
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget
        from ui.qt.qt_form import qt_schedule

        theme = qt_theme_for_platform()
        w = 310 if IS_FROZEN else 210
        h = 130 if IS_FROZEN else 100

        dlg = QtDialog(
            title=title, width=w, height=h, theme=theme,
            topmost=False, icon_path=ICON_PATH,
            on_close=lambda: done.set(),
        )
        lay = dlg.content_frame(padx=16, pady=14)

        msg = QLabel(text)
        msg.setWordWrap(True)
        msg.setStyleSheet("font-size: 12px;")
        lay.addWidget(msg)

        status_label = QLabel("")
        status_label.setWordWrap(True)
        status_label.setObjectName("Secondary")
        # Fixed: use orange secondary color instead of hardcoded blue/gray
        status_label.setStyleSheet("color: #C4A080; font-size: 11px;")
        lay.addWidget(status_label)

        btn_row = QWidget()
        bl = QHBoxLayout(btn_row)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        lay.addWidget(btn_row)

        btns: list = []

        def _set_status(msg: str) -> None:
            qt_schedule(lambda: status_label.setText(msg))

        def _close_with(value: str) -> None:
            result["value"] = value
            dlg.close()

        def _on_update() -> None:
            if not download_url:
                if release_url:
                    webbrowser.open(release_url)
                _close_with("open")
                return
            for b in btns:
                b.setEnabled(False)
            dlg._updating = True

            def _run():
                _perform_update(download_url, set_status=_set_status)
                qt_schedule(lambda: dlg.close())

            threading.Thread(target=_run, daemon=True).start()

        if IS_FROZEN:
            btn_upd = QPushButton(t("button.update"))
            btn_upd.setStyleSheet("QPushButton { padding: 0; }")
            btn_upd.setFixedSize(88, 34)
            btn_upd.clicked.connect(_on_update)
            bl.addWidget(btn_upd)
            btns.append(btn_upd)
        btn_pg = QPushButton(t("button.page"))
        btn_pg.setStyleSheet("QPushButton { padding: 0; }")
        btn_pg.setFixedSize(88, 34)
        btn_pg.clicked.connect(lambda: webbrowser.open(release_url or RELEASES_PAGE_URL))
        bl.addWidget(btn_pg)
        btns.append(btn_pg)
        btn_cl = QPushButton(t("button.close"))
        btn_cl.setStyleSheet("QPushButton { padding: 0; }")
        btn_cl.setFixedSize(88, 34)
        btn_cl.clicked.connect(lambda: _close_with("close"))
        bl.addWidget(btn_cl)
        btns.append(btn_cl)

        dlg._updating = False
        dlg.show()
        dlg.start_entrance()
        dlg.raise_()
        dlg.activateWindow()

    qt_run_dialog(_build)
    return result["value"]


def _perform_update(download_url: str, set_status=None) -> None:
    def _step(msg: str) -> None:
        log.info("Update: %s", msg)
        if set_status:
            set_status(msg)
            time.sleep(0.8)

    def _err(msg: str) -> None:
        log.error("Update error: %s", msg)
        if set_status:
            set_status(f"{t('update.error', msg=msg)}")
        else:
            _show_error(msg)

    _step(t("update.downloading"))
    cur_exe = Path(sys.executable)
    old_exe = cur_exe.with_name(cur_exe.stem + "_oldswift.exe")
    tmp_path = None
    try:
        fd, tmp_name = tempfile.mkstemp(dir=cur_exe.parent, suffix=".tmp")
        os.close(fd)
        tmp_path = Path(tmp_name)
        log.info("Downloading update from %s", download_url)
        opener = build_github_opener()
        with opener.open(download_url) as _resp:
            with open(str(tmp_path), "wb") as _fout:
                while True:
                    _chunk = _resp.read(65536)
                    if not _chunk:
                        break
                    _fout.write(_chunk)
    except Exception as exc:
        _err(t("update.download_fail", error=exc))
        if tmp_path:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        return

    _step(t("update.replacing"))
    try:
        if old_exe.exists():
            old_exe.unlink()
        cur_exe.rename(old_exe)
    except Exception as exc:
        _err(t("update.rename_fail", error=exc))
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return

    try:
        tmp_path.rename(cur_exe)
    except Exception as exc:
        _err(t("update.move_fail", error=exc))
        try:
            old_exe.rename(cur_exe)
        except OSError:
            pass
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return

    _step(t("update.restarting"))
    _release_win_mutex()
    stop_proxy()

    # Don't reuse existing _MEI* dir
    env = os.environ.copy()
    for _k in [k for k in env if k.startswith("_PYI_") or k == "_MEIPASS"]:
        del env[_k]
    if hasattr(sys, "_MEIPASS"):
        _mei = os.path.normcase(sys._MEIPASS.rstrip("\\/"))
        env["PATH"] = os.pathsep.join(
            p for p in env.get("PATH", "").split(os.pathsep)
            if os.path.normcase(p.rstrip("\\/")) != _mei
        )

    try:
        subprocess.Popen(
            [str(cur_exe)],
            env=env,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    except Exception as exc:
        log.error("Failed to launch updated exe: %s", exc)
    time.sleep(0.5)
    os._exit(0)


def _trigger_update_flow(icon=None, item=None) -> None:
    """Show the update dialog for an update already known to be available.

    Reused by the tray "Update" item and the settings dialog's "Update"
    button, so an update can still be started after the initial startup
    prompt was skipped/closed.
    """
    if not _update_flow_lock.acquire(blocking=False):
        return

    def _show() -> None:
        try:
            if _exiting:
                return
            st = get_status()
            if not st.get("has_update"):
                return
            url = (st.get("html_url") or "").strip() or RELEASES_PAGE_URL
            ver = st.get("latest") or "?"
            asset = get_update_asset(Path(sys.executable), __version__) if IS_FROZEN else None

            choice = update_qt_form(
                t("update.available", version=ver),
                download_url=asset[0] if asset else None,
                release_url=url,
            )
            if choice == "open":
                webbrowser.open(url)
        except Exception as exc:
            log.warning("Update flow failed: %s", repr(exc))
        finally:
            _update_flow_lock.release()

    threading.Thread(target=_show, daemon=True, name="manual-update").start()


def _maybe_do_update(cfg: dict, is_exiting) -> None:
    if not cfg.get("check_updates", True):
        return

    def _work():
        time.sleep(1.5)
        if is_exiting():
            return
        try:
            run_check(__version__)
            if _tray_icon is not None:
                _tray_icon.menu = _build_menu()
            if is_exiting():
                return
            _trigger_update_flow()
        except Exception as exc:
            log.warning("Update check failed: %s", repr(exc))

    threading.Thread(target=_work, daemon=True, name="update-check").start()


# autostart (registry)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _supports_autostart() -> bool:
    return IS_FROZEN


def _autostart_command() -> str:
    return f'"{sys.executable}"'


def is_autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, APP_NAME)
        return str(val).strip() == _autostart_command().strip()
    except (FileNotFoundError, OSError):
        return False


def set_autostart_enabled(enabled: bool) -> None:
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            if enabled:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _autostart_command())
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
    except OSError as exc:
        log.error("Failed to update autostart: %s", exc)
        _show_error(
            t("dialog.autostart_fail", error=exc)
        )


# tray callbacks

def _on_open_in_telegram(icon=None, item=None) -> None:
    url = tg_proxy_url(_config)
    log.info("Opening %s", url)
    try:
        if not webbrowser.open(url):
            raise RuntimeError
    except Exception:
        log.info("Browser open failed, copying to clipboard")
        if pyperclip is None:
            _show_error(
                t("dialog.open_tg_fail_manual", url=url)
            )
            return
        try:
            pyperclip.copy(url)
            _show_info(
                t("dialog.open_tg_fail_clipboard", url=url)
            )
        except Exception as exc:
            log.error("Clipboard copy failed: %s", exc)
            _show_error(t("dialog.copy_fail", error=exc))


def _on_copy_link(icon=None, item=None) -> None:
    url = tg_proxy_url(_config)
    log.info("Copying link: %s", url)
    if pyperclip is None:
        _show_error(t("dialog.pyperclip_missing"))
        return
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
        try:
            os.startfile(str(LOG_FILE))
        except Exception as exc:
            log.error("Failed to open log file: %s", exc)
            _show_error(t("dialog.log_open_fail", error=exc))
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
    cfg["autostart"] = is_autostart_enabled()
    if _supports_autostart() and not cfg["autostart"]:
        set_autostart_enabled(False)

    def _build(done: threading.Event) -> None:
        from PySide6.QtWidgets import QScrollArea
        from ui.qt.qt_form import tray_settings_scroll_and_footer

        theme = qt_theme_for_platform()
        w, h = CONFIG_DIALOG_SIZE
        if _supports_autostart():
            h += 100

        _skip_restore = {"v": False}

        def _restore() -> None:
            if _skip_restore["v"]:
                return
            apply_qt_appearance(_original_appearance)
            _restore_ui_locale()

        dlg = QtDialog(
            title=t("app.settings_title"), width=w, height=h, theme=theme,
            topmost=False, icon_path=ICON_PATH,
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
            show_autostart=_supports_autostart(),
            autostart_value=cfg.get("autostart", False),
            on_language_change=_refresh_tray_menu,
            on_update_click=_trigger_update_flow,
        )

        _original_appearance = cfg.get("appearance", "auto")
        from ui.qt.qt_runtime import apply_qt_appearance

        def _restore_ui_locale() -> None:
            set_language(_original_language)
            _refresh_tray_menu()

        def _finish() -> None:
            _skip_restore["v"] = True
            dlg.close()

        def _cancel() -> None:
            dlg.close()

        def on_save() -> None:
            merged = validate_config_form(widgets, DEFAULT_CONFIG, include_autostart=_supports_autostart())
            if isinstance(merged, str):
                show_qt_error(dlg, merged)
                return

            merged["force_test_dc"] = _config.get("force_test_dc", DEFAULT_CONFIG["force_test_dc"])

            _ui_only_keys = {"appearance", "autostart", "check_updates", "language"}
            config_changed = any(merged.get(k) != cfg.get(k) for k in merged)
            proxy_changed = any(merged.get(k) != _config.get(k) for k in merged if k not in _ui_only_keys)

            if not config_changed:
                _restore_ui_locale()
                _finish()
                return

            save_config(merged)
            _config.update(merged)
            set_language(merged.get("language", DEFAULT_CONFIG["language"]))
            log.info("Config saved: %s", merged)
            if _supports_autostart():
                set_autostart_enabled(bool(merged.get("autostart", False)))
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
            topmost=False, icon_path=ICON_PATH,
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
    if pystray is None:
        return None
    host = _config.get("host", DEFAULT_CONFIG["host"])
    port = _config.get("port", DEFAULT_CONFIG["port"])
    link_host = get_link_host(host)
    items = [
        pystray.MenuItem(t("tray.open_telegram", host=link_host, port=port), _on_open_in_telegram, default=True),
        pystray.MenuItem(t("tray.copy_link"), _on_copy_link),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(t("tray.restart"), _on_restart),
        pystray.MenuItem(t("tray.settings"), _on_edit_config),
        pystray.MenuItem(t("tray.logs"), _on_open_logs),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(t("tray.exit"), _on_exit),
    ]

    st = get_status()
    if st.get("has_update"):
        items[-2:-2] = [
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                t("tray.update", current=__version__, new=st.get("latest") or "?"),
                _trigger_update_flow,
            )
        ]
    return pystray.Menu(*items)


# entry point

def run_tray() -> None:
    global _tray_icon, _config

    _config = load_config()

    if is_windows_dark_theme():
        apply_windows_dark_theme()

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
    _maybe_do_update(_config, lambda: _exiting)
    _show_first_run()
    check_ipv6_warning(_show_info)

    _tray_icon = pystray.Icon(APP_NAME, load_icon(), t("app.name"), menu=_build_menu())
    log.info("Tray icon running")
    _tray_icon.run()

    stop_proxy()
    log.info("Tray app exited")


def main() -> None:
    if (mutex_result := _acquire_win_mutex()) is False or mutex_result is None and not acquire_lock():
        _show_info(t("dialog.already_running"), os.path.basename(sys.argv[0]))
        return

    if IS_FROZEN:
        def _cleanup_old_exes():
            exe_dir = Path(sys.executable).parent
            time.sleep(3)
            for _f in exe_dir.glob("*_oldswift.exe"):
                try:
                    _f.unlink()
                    log.info("Deleted leftover: %s", _f)
                except OSError:
                    pass
        threading.Thread(target=_cleanup_old_exes, daemon=True, name="cleanup-old").start()

    try:
        run_tray()
    finally:
        release_lock()
        _release_win_mutex()


if __name__ == "__main__":
    main()