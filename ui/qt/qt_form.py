"""Settings form and first-run content for the Qt (PySide6) SwiftProxy UI.

Pure-Qt port of the CustomTkinter form originally in ui/ctk_tray_ui.py.
Now with iOS 26 Liquid Glass styling and improved layout.
"""

from __future__ import annotations

import base64
import logging
import os
import socket as _socket
import ssl
import threading
import webbrowser
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from proxy import __version__, get_link_host, parse_dc_ip_list, coerce_domain_list
from proxy.balancer import balancer
from utils.update_check import RELEASES_PAGE_URL, get_status

from ui.i18n import (
    label_from_language,
    language_from_label,
    language_option_labels,
    set_language,
    t,
)

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger('swift-proxy')

_INNER_W = 396

# --------------------------------------------------------------------------
# small threaded-ui dispatcher (worker threads -> Qt main thread)
# --------------------------------------------------------------------------


class GuiSignal(QObject):
    fired = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._handlers: List[Callable[[], None]] = []
        self.fired.connect(lambda fn: fn())


_GUI_SIGNAL: Optional[GuiSignal] = None


def qt_schedule(fn: Callable[[], None]) -> None:
    """Schedule fn() to run on the Qt main thread from any thread."""
    global _GUI_SIGNAL
    if _GUI_SIGNAL is None:
        _GUI_SIGNAL = GuiSignal()
    _GUI_SIGNAL.fired.emit(fn)


# --------------------------------------------------------------------------
# appearance helpers
# --------------------------------------------------------------------------

_APPEARANCE_KEYS = ("auto", "light", "dark")


def _appearance_options() -> List[str]:
    return [t(f"appearance.{key}") for key in _APPEARANCE_KEYS]


def _appearance_from_cfg(value: str) -> str:
    if value in _APPEARANCE_KEYS:
        return t(f"appearance.{value}")
    return t("appearance.auto")


def _appearance_to_cfg(label: str) -> str:
    for key in _APPEARANCE_KEYS:
        if t(f"appearance.{key}") == label:
            return key
    return "auto"


# --------------------------------------------------------------------------
# docs
# --------------------------------------------------------------------------


def _get_doc_url(doc_name: str) -> str:
    from ui.i18n import get_language

    lang = get_language().value
    lang_folder = "EN" if lang == "en" else "RU"
    return f"https://github.com/Lil-KALINOV/SwiftProxy/blob/main/docs/{lang_folder}/{doc_name}.md"


# --------------------------------------------------------------------------
# connectivity tests (framework-agnostic)
# --------------------------------------------------------------------------

_CFPROXY_TEST_DCS = [1, 2, 3, 4, 5, 203]
_CFWORKER_TEST_DST = {
    1: '149.154.175.50',
    2: '149.154.167.51',
    3: '149.154.175.100',
    4: '149.154.167.91',
    5: '149.154.171.5',
    203: '91.105.192.100',
}


def _run_connectivity_test(cases: list) -> dict:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    results = {}
    for dc, connect_host, sni_host, req_host, path in cases:
        try:
            with _socket.create_connection((connect_host, 443), timeout=5) as raw:
                with ctx.wrap_socket(raw, server_hostname=sni_host) as ssock:
                    ws_key = base64.b64encode(os.urandom(16)).decode()
                    req = (
                        f"GET {path} HTTP/1.1\r\n"
                        f"Host: {req_host}\r\n"
                        f"Upgrade: websocket\r\n"
                        f"Connection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {ws_key}\r\n"
                        f"Sec-WebSocket-Version: 13\r\n"
                        f"Sec-WebSocket-Protocol: binary\r\n"
                        f"\r\n"
                    ).encode()
                    ssock.sendall(req)
                    ssock.settimeout(5)
                    buf = b""
                    while b"\r\n\r\n" not in buf:
                        chunk = ssock.recv(512)
                        if not chunk:
                            break
                        buf += chunk
                    first = buf.decode("utf-8", errors="replace").split("\r\n")[0]
                    if "101" in first:
                        results[dc] = True
                    else:
                        results[dc] = first or t("connectivity.no_response")
                    ssock.close()
                raw.close()
        except _socket.timeout:
            results[dc] = t("connectivity.timeout")
        except OSError as exc:
            msg = str(exc)
            results[dc] = msg[:60] if len(msg) > 60 else msg
    return results


def _run_cfproxy_connectivity_test(domain: str) -> dict:
    cases = []
    for dc in _CFPROXY_TEST_DCS:
        host = f"kws{dc}.{domain}"
        cases.append((dc, host, host, host, "/apiws"))
    return _run_connectivity_test(cases)


def _run_cfworker_connectivity_test(domain: str) -> dict:
    cases = []
    for dc in _CFPROXY_TEST_DCS:
        dst = _CFWORKER_TEST_DST[dc]
        path = f"/apiws?dst={dst}&dc={dc}&media=0"
        cases.append((dc, domain, domain, domain, path))
    return _run_connectivity_test(cases)


def _run_cfproxy_multi_test(domains: list) -> dict:
    return {domain: _run_cfproxy_connectivity_test(domain) for domain in domains}


def _run_cfworker_multi_test(domains: list) -> dict:
    return {domain: _run_cfworker_connectivity_test(domain) for domain in domains}


def _run_cfproxy_auto_test(domains: list) -> tuple:
    merged: dict = {}
    best_domain = None
    for domain in reversed(domains):
        res = _run_cfproxy_connectivity_test(domain)
        if all(v is True for v in res.values()):
            return domain, res
        for dc, v in res.items():
            if v is True:
                merged[dc] = True
                best_domain = domain
            elif dc not in merged:
                merged[dc] = v
    return best_domain, merged


def _show_connectivity_results(parent: Any, title_base: str, results: dict,
                               domain: str = '', label_prefix: str = 'DC',
                               auto_mode: bool = False,
                               unavailable_message: str = '') -> None:
    ok = [dc for dc, v in results.items() if v is True]
    total = len(_CFPROXY_TEST_DCS)
    if auto_mode:
        if domain:
            title = t("connectivity.available", title=title_base)
            msg = t("connectivity.auto_ok", title=title_base, ok=len(ok), total=total)
        else:
            title = t("connectivity.unavailable", title=title_base)
            msg = unavailable_message
    else:
        fail = [(dc, v) for dc, v in results.items() if v is not True]
        if len(ok) == total:
            title = t("connectivity.all_ok", title=title_base)
            msg = t("connectivity.all_ok_domain", total=total, domain=domain)
        elif not ok:
            title = t("connectivity.unavailable", title=title_base)
            errors = "\n".join(
                t("connectivity.error_line", prefix=label_prefix, dc=dc, error=v)
                for dc, v in fail
            )
            msg = t("connectivity.none_ok", domain=domain, errors=errors)
        else:
            title = t("connectivity.partial", title=title_base)
            ok_list = ", ".join(f"{label_prefix}{dc}" for dc in ok)
            fail_list = "\n".join(
                t("connectivity.error_line", prefix=label_prefix, dc=dc, error=v)
                for dc, v in fail
            )
            msg = t("connectivity.partial_detail", domain=domain, ok_list=ok_list, fail_list=fail_list)

    QMessageBox.information(parent, title, msg)


def _show_multi_connectivity_results(parent: Any, title_base: str, per_domain: dict,
                                     label_prefix: str = 'DC') -> None:
    total = len(_CFPROXY_TEST_DCS)
    all_ok = True
    any_ok = False
    blocks = []
    for domain, results in per_domain.items():
        ok = [dc for dc, v in results.items() if v is True]
        fail = [(dc, v) for dc, v in results.items() if v is not True]
        if len(ok) == total:
            any_ok = True
            blocks.append(t("connectivity.multi_all_ok", domain=domain, total=total))
        elif not ok:
            all_ok = False
            blocks.append(t("connectivity.multi_fail", domain=domain))
        else:
            all_ok = False
            any_ok = True
            ok_list = ", ".join(f"{label_prefix}{dc}" for dc in ok)
            fail_list = ", ".join(f"{label_prefix}{dc}" for dc, _ in fail)
            blocks.append(
                t("connectivity.multi_partial", domain=domain, ok_list=ok_list, fail_list=fail_list)
            )

    if all_ok:
        title = t("connectivity.all_ok", title=title_base)
    elif any_ok:
        title = t("connectivity.partial", title=title_base)
    else:
        title = t("connectivity.unavailable", title=title_base)
    msg = "\n\n".join(blocks)

    QMessageBox.information(parent, title, msg)


# --------------------------------------------------------------------------
# building blocks
# --------------------------------------------------------------------------


def _q_label(text: str, *, primary: bool = False, size: int = 12) -> QLabel:
    lbl = QLabel(text)
    if primary:
        lbl.setProperty("primary", True)
    lbl.setStyleSheet(f"font-size: {size}px; background: transparent;")
    return lbl


def _icon_pixmap(size: int = 46) -> Any:
    """Return a QPixmap rendered from utils.icon, or None on failure."""
    try:
        from utils.icon import render_icon

        img = render_icon(size * 2)
        import io as _io
        from PIL import Image
        img = img.resize((size, size), Image.Resampling.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        from PySide6.QtGui import QPixmap
        pix = QPixmap()
        if pix.loadFromData(buf.read(), "PNG"):
            return pix
    except Exception:
        pass
    return None


def _refresh_icon_pixmap(size: int = 20, color: Any = None) -> Optional[Any]:
    """Crisp circular-arrow refresh icon, drawn with QPainter (anti-aliased)."""
    try:
        from PySide6.QtCore import QPointF, QRectF, Qt
        from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPolygonF, QPixmap

        if color is None:
            from PySide6.QtGui import QColor as _C
            color = _C("white")
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color) if isinstance(color, str) else color)
        pen.setWidthF(max(1.8, size * 0.14))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        c = size / 2.0
        r = c - size * 0.16
        rectf = QRectF(c - r, c - r, r * 2, r * 2)
        p.drawArc(rectf, 60 * 16, 360 * 16 - 70 * 16)
        hx = c + r * 0.62
        hy = c - r * 0.86
        p.setBrush(p.pen().color())
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF([QPointF(hx, hy - size * 0.22),
                                 QPointF(hx + size * 0.26, hy + size * 0.10),
                                 QPointF(hx - size * 0.26, hy + size * 0.10)]))
        p.end()
        return QIcon(pm)
    except Exception:
        return None


def _icon_label(parent: Any, size: int = 46) -> Optional[QLabel]:
    pix = _icon_pixmap(size)
    if pix is None:
        return None
    lbl = QLabel(parent)
    lbl.setPixmap(pix)
    return lbl


def _section_frame(title: str, theme: Any) -> Tuple[QWidget, QVBoxLayout]:
    """Return (card frame, inner layout). Title shown above with accent bar.
    Cards use GlassCard widget for proper glass effect."""
    from ui.qt.qt_widgets import section_label, GlassCard

    wrap = QWidget()
    wrap.setObjectName("SectionParent")
    v = QVBoxLayout(wrap)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(8)

    # Title row with accent bar
    title_row = QWidget()
    tr = QHBoxLayout(title_row)
    tr.setContentsMargins(0, 0, 0, 0)
    tr.setSpacing(8)
    
    accent = QFrame(title_row)
    accent.setObjectName("AccentBar")
    accent.setFixedSize(4, 16)
    tr.addWidget(accent)
    tr.addWidget(section_label(theme, title))
    tr.addStretch(1)
    v.addWidget(title_row)

    # Glass card
    card = GlassCard()
    inner = QVBoxLayout(card)
    inner.setContentsMargins(16, 14, 16, 14)
    inner.setSpacing(12)
    v.addWidget(card)

    return wrap, inner


def _checkbox_row(parent_layout: Any, text: str, value: bool, *, tip: str = "",
                  on_toggle: Optional[Callable[[bool], None]] = None) -> Any:
    """Create a row with label on left and iOS toggle on right (iOS settings style).
    
    Uses QPalette-based colors so text automatically updates when theme changes.
    """
    from ui.qt.qt_widgets import IOSToggle

    row = QWidget()
    rlay = QHBoxLayout(row)
    rlay.setContentsMargins(0, 0, 0, 0)
    rlay.setSpacing(12)
    
    # Label on the left — use WindowText role so it auto-updates with palette
    label = QLabel(text)
    label.setStyleSheet("""
        QLabel {
            font-size: 14px;
            background: transparent;
        }
    """)
    # Use palette role instead of hardcoded color
    from PySide6.QtGui import QPalette
    label.setForegroundRole(QPalette.ColorRole.WindowText)
    rlay.addWidget(label, 1)  # Stretch to push toggle to the right
    
    # Toggle on the right (no built-in label)
    toggle_widget = IOSToggle(checked=value)
    if on_toggle:
        toggle_widget.toggled.connect(on_toggle)
    
    rlay.addWidget(toggle_widget, 0)  # Fixed size, no stretch
    
    parent_layout.addWidget(row)
    
    if tip:
        row.setToolTip(tip)
        toggle_widget.setToolTip(tip)
    
    return toggle_widget


# --------------------------------------------------------------------------
# form widgets
# --------------------------------------------------------------------------


@dataclass
class QtFormWidgets:
    host_edit: QLineEdit
    port_edit: QLineEdit
    secret_edit: QLineEdit
    dc_text: QPlainTextEdit
    verbose_cb: Any
    adv_entries: List[QLineEdit] = field(default_factory=list)
    adv_keys: Tuple[str, ...] = ()
    autostart_cb: Optional[Any] = None
    check_updates_cb: Optional[Any] = None
    cfproxy_cb: Optional[Any] = None
    cfproxy_user_domain_enabled_cb: Optional[Any] = None
    cfproxy_user_domain_edit: Optional[QLineEdit] = None
    cfproxy_worker_enabled_cb: Optional[Any] = None
    cfproxy_worker_domain_edit: Optional[QLineEdit] = None
    appearance_control: Optional[Any] = None
    language_combo: Optional[Any] = None


def install_tray_config_form(
    content: QWidget,
    theme: Any,
    cfg: dict,
    default_config: dict,
    *,
    show_autostart: bool = False,
    autostart_value: bool = False,
    on_language_change: Optional[Callable[[], None]] = None,
    on_update_click: Optional[Callable[[], None]] = None,
) -> QtFormWidgets:
    lang_cfg = cfg.get("language", default_config["language"])
    set_language(lang_cfg)

    from ui.qt.qt_widgets import SegmentedControl

    root = content
    lay = QVBoxLayout(root)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(16)

    # header ------------------------------------------------
    header = QWidget()
    hlay = QHBoxLayout(header)
    hlay.setContentsMargins(0, 0, 0, 0)
    hlay.setSpacing(12)

    pix = _icon_pixmap(48)
    if pix is not None:
        lbl = QLabel(header)
        lbl.setPixmap(pix)
        hlay.addWidget(lbl)
    else:
        hlay.addWidget(QLabel("◆"))

    title_col = QWidget()
    tl = QVBoxLayout(title_col)
    tl.setContentsMargins(0, 0, 0, 0)
    tl.setSpacing(2)
    title = QLabel("SwiftProxy")
    title.setObjectName("Title")
    tl.addWidget(title)
    badge = QLabel(f" v{__version__} ")
    badge.setObjectName("VerBadge")
    tl.addWidget(badge)
    hlay.addWidget(title_col, 1)

    def _fund() -> None:
        dlg = header.window()
        if dlg is not None:
            dlg.hide()
        webbrowser.open(_get_doc_url("Funding"))

    # Fund button: glass circle with heart
    fund_btn = QPushButton("♥")
    fund_btn.setObjectName("FundButton")
    fund_btn.setFixedSize(40, 40)
    fund_btn.setToolTip(t("tip.funding"))
    fund_btn.clicked.connect(_fund)
    hlay.addWidget(fund_btn)
    lay.addWidget(header)

    # Helper function for iOS-style dropdowns (theme-aware via palette roles)
    def _ios_combo_box(items: list, current: str, on_change: Optional[Callable[[str], None]] = None) -> Any:
        from PySide6.QtWidgets import QComboBox
        
        combo = QComboBox()
        combo.addItems(items)
        combo.setCurrentText(current)
        combo.setFixedHeight(36)
        combo.setMinimumWidth(150)
        # Use palette roles so colors auto-update when theme changes
        combo.setStyleSheet("""
            QComboBox {
                border-radius: 12px;
                padding: 6px 14px;
                font-size: 13px;
                font-weight: 500;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
                subcontrol-origin: padding;
                subcontrol-position: top right;
            }
            QComboBox::down-arrow {
                width: 0;
                height: 0;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid palette(Highlight);
                margin-right: 12px;
            }
            QComboBox QAbstractItemView {
                selection-background-color: palette(Highlight);
                selection-color: palette(HighlightedText);
                padding: 6px;
                border-radius: 12px;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                padding: 8px 14px;
                border-radius: 8px;
                min-height: 20px;
            }
            QComboBox QAbstractItemView::item:selected {
                background: palette(Highlight);
                color: palette(HighlightedText);
            }
        """)
        
        if on_change:
            combo.currentTextChanged.connect(on_change)
        
        return combo

    # interface ---------------------------------------------
    sec, sec_lay = _section_frame(t("section.interface"), theme)
    lay.addWidget(sec)

    # Language dropdown (iOS-style combobox)
    lang_labels = [label for _, label in language_option_labels()]
    current_lang_label = label_from_language(lang_cfg)
    
    def _on_language_change(label: str) -> None:
        set_language(language_from_label(label).value)
        if on_language_change is not None:
            on_language_change()
    
    language_combo = _ios_combo_box(lang_labels, current_lang_label, _on_language_change)
    
    lang_row = QWidget()
    lr = QHBoxLayout(lang_row)
    lr.setContentsMargins(0, 0, 0, 0)
    lr.setSpacing(12)
    
    lang_label = QLabel(t("settings.language"))
    lang_label.setStyleSheet("font-size: 14px; background: transparent;")
    from PySide6.QtGui import QPalette as _QP
    lang_label.setForegroundRole(_QP.ColorRole.WindowText)
    lr.addWidget(lang_label, 1)
    lr.addWidget(language_combo, 0)
    
    sec_lay.addWidget(lang_row)

    # Theme dropdown (iOS-style combobox)
    appearance_var = _appearance_from_cfg(cfg.get("appearance", "auto"))
    appearance_labels = _appearance_options()
    
    def _on_appearance_change(choice: str) -> None:
        cfg_val = _appearance_to_cfg(choice)
        from ui.qt.qt_runtime import apply_qt_appearance
        apply_qt_appearance(cfg_val)
        cfg["appearance"] = cfg_val
    
    theme_combo = _ios_combo_box(appearance_labels, appearance_var, _on_appearance_change)
    
    theme_row = QWidget()
    tr2 = QHBoxLayout(theme_row)
    tr2.setContentsMargins(0, 0, 0, 0)
    tr2.setSpacing(12)
    
    theme_label = QLabel(t("settings.theme"))
    theme_label.setStyleSheet("font-size: 14px; background: transparent;")
    theme_label.setForegroundRole(_QP.ColorRole.WindowText)
    tr2.addWidget(theme_label, 1)
    tr2.addWidget(theme_combo, 0)
    
    sec_lay.addWidget(theme_row)

    # mtproto -------------------------------------------------
    sec, sec_lay = _section_frame(t("section.mtproto"), theme)
    lay.addWidget(sec)

    host_row = QWidget()
    hr = QHBoxLayout(host_row)
    hr.setContentsMargins(0, 0, 0, 0)
    hr.setSpacing(12)
    host_tag = _q_label(t("label.host"), size=11)
    host_edit = QLineEdit(str(cfg.get("host", default_config["host"])))
    host_edit.setObjectName("FieldEntry")
    host_edit.setFixedHeight(36)
    host_col = QWidget()
    hc = QVBoxLayout(host_col)
    hc.setContentsMargins(0, 0, 0, 0)
    hc.setSpacing(6)
    hc.addWidget(host_tag)
    hc.addWidget(host_edit)
    hr.addWidget(host_col, 1)

    port_tag = _q_label(t("label.port"), size=11)
    port_edit = QLineEdit(str(cfg.get("port", default_config["port"])))
    port_edit.setObjectName("FieldEntry")
    port_edit.setFixedHeight(36)
    port_col = QWidget()
    pc = QVBoxLayout(port_col)
    pc.setContentsMargins(0, 0, 0, 0)
    pc.setSpacing(6)
    pc.addWidget(port_tag)
    pc.addWidget(port_edit)
    hr.addWidget(port_col, 1)
    sec_lay.addWidget(host_row)
    host_edit.setToolTip(t("tip.host"))
    port_edit.setToolTip(t("tip.port"))

    secret_tag = _q_label(t("label.secret"), size=11)
    secret_edit = QLineEdit(str(cfg.get("secret", default_config["secret"])))
    secret_edit.setObjectName("FieldEntry")
    secret_edit.setFixedHeight(36)
    secret_edit.setToolTip(t("tip.secret"))

    regen_btn = QPushButton()
    regen_btn.setObjectName("RegenButton")
    regen_btn.setFixedSize(32, 32)
    regen_btn.setToolTip(t("tip.secret"))
    _reload = _refresh_icon_pixmap(16, "#FF9500")
    if _reload is not None:
        from PySide6.QtCore import QSize as _QSize
        regen_btn.setIcon(_reload)
        regen_btn.setIconSize(_QSize(16, 16))
    else:
        regen_btn.setText("↺")
    regen_btn.clicked.connect(lambda: secret_edit.setText(os.urandom(16).hex()))

    secret_row = QWidget()
    srow = QHBoxLayout(secret_row)
    srow.setContentsMargins(0, 0, 0, 0)
    srow.setSpacing(12)
    srow.addWidget(secret_tag)
    edit_btn_row = QWidget()
    ebr = QHBoxLayout(edit_btn_row)
    ebr.setContentsMargins(0, 0, 0, 0)
    ebr.setSpacing(10)
    ebr.addWidget(secret_edit, 1)
    ebr.addWidget(regen_btn, 0, Qt.AlignmentFlag.AlignVCenter)
    srow.addWidget(edit_btn_row, 1)
    sec_lay.addWidget(secret_row)

    # dc --------------------------------------------------
    sec, sec_lay = _section_frame(t("section.dc"), theme)
    lay.addWidget(sec)
    sec_lay.addWidget(_q_label(t("label.dc_hint"), size=11))
    dc_text = QPlainTextEdit()
    dc_text.setObjectName("Monospace")
    dc_text.setMinimumHeight(100)
    dc_text.setPlainText("\n".join(cfg.get("dc_ip", default_config["dc_ip"])))
    dc_text.setToolTip(t("tip.dc"))
    sec_lay.addWidget(dc_text)

    # cfproxy --------------------------------------------
    sec, sec_lay = _section_frame(t("section.cfproxy"), theme)
    lay.addWidget(sec)

    cfproxy_cb = _checkbox_row(
        sec_lay, t("label.cf_enable"),
        bool(cfg.get("cfproxy", default_config.get("cfproxy", True))),
        tip=t("tip.cfproxy"),
    )
    cfproxy_cb.setChecked(bool(cfg.get("cfproxy", default_config.get("cfproxy", True))))

    cf_test_btn = QPushButton(t("button.test"))
    cf_test_btn.setObjectName("TestButton")
    cf_test_btn.setFixedSize(72, 28)  # Compact iOS size
    cf_test_btn.setToolTip(t("tip.cf_test"))
    # Glow effect when enabled (ready to test)
    _apply_test_glow(cf_test_btn, enabled=True)

    # custom domain checkbox
    saved_user_domains = coerce_domain_list(
        cfg.get("cfproxy_user_domain", default_config.get("cfproxy_user_domain", ""))
    )
    cfproxy_user_domain_enabled_cb = _checkbox_row(
        sec_lay, t("label.cf_custom_domain"), bool(cfg.get("cfproxy_user_domain_enabled", False))
        or bool(saved_user_domains),
        tip=t("tip.cfproxy_user_domain_cb"),
    )
    cfproxy_user_domain_edit = QLineEdit(", ".join(saved_user_domains))
    cfproxy_user_domain_edit.setObjectName("FieldEntry")
    cfproxy_user_domain_edit.setFixedHeight(36)
    cfproxy_user_domain_edit.setToolTip(t("tip.cfproxy_domain"))
    sec_lay.addWidget(cfproxy_user_domain_edit)

    doc_btn = QPushButton("?")
    doc_btn.setObjectName("DocButton")
    doc_btn.setFixedSize(36, 36)
    doc_btn.clicked.connect(lambda: webbrowser.open(_get_doc_url("CfProxy")))
    host_cf_row = QWidget()
    hcr = QHBoxLayout(host_cf_row)
    hcr.setContentsMargins(0, 0, 0, 0)
    hcr.setSpacing(8)
    hcr.addWidget(cf_test_btn)
    hcr.addWidget(doc_btn)
    hcr.addStretch(1)
    sec_lay.addWidget(host_cf_row)

    def _sync_domain_entry():
        state = cfproxy_user_domain_enabled_cb.isChecked()
        cfproxy_user_domain_edit.setEnabled(state)

    cfproxy_user_domain_enabled_cb.toggled.connect(lambda _v: _sync_domain_entry())
    _sync_domain_entry()

    # cfworker --------------------------------------------
    sec, sec_lay = _section_frame(t("section.cfworker"), theme)
    lay.addWidget(sec)

    saved_worker_domains = coerce_domain_list(
        cfg.get("cfproxy_worker_domain", default_config.get("cfproxy_worker_domain", ""))
    )
    cfproxy_worker_enabled_cb = _checkbox_row(
        sec_lay, t("label.cf_custom_domain"), bool(cfg.get("cfproxy_worker_enabled", False))
        or bool(saved_worker_domains),
        tip=t("tip.cfworker_domain"),
    )
    cfproxy_worker_domain_edit = QLineEdit(", ".join(saved_worker_domains))
    cfproxy_worker_domain_edit.setObjectName("FieldEntry")
    cfproxy_worker_domain_edit.setFixedHeight(36)
    cfproxy_worker_domain_edit.setToolTip(t("tip.cfworker_domain"))
    sec_lay.addWidget(cfproxy_worker_domain_edit)

    worker_ctrl_row = QWidget()
    wcr = QHBoxLayout(worker_ctrl_row)
    wcr.setContentsMargins(0, 0, 0, 0)
    wcr.setSpacing(8)
    cfworker_test_btn = QPushButton(t("button.test"))
    cfworker_test_btn.setObjectName("TestButton")
    cfworker_test_btn.setFixedSize(72, 28)  # Compact iOS size
    cfworker_test_btn.setToolTip(t("tip.cf_test"))
    # Glow effect when enabled (ready to test)
    _apply_test_glow(cfworker_test_btn, enabled=False)
    wcr.addWidget(cfworker_test_btn)
    doc_btn2 = QPushButton("?")
    doc_btn2.setObjectName("DocButton")
    doc_btn2.setFixedSize(36, 36)
    doc_btn2.clicked.connect(lambda: webbrowser.open(_get_doc_url("CfWorker")))
    wcr.addWidget(doc_btn2)
    wcr.addStretch(1)
    sec_lay.addWidget(worker_ctrl_row)

    def _sync_cfworker():
        state = cfproxy_worker_enabled_cb.isChecked()
        cfproxy_worker_domain_edit.setEnabled(state)
        has_domain = bool(coerce_domain_list(cfproxy_worker_domain_edit.text()))
        ready = state and has_domain
        cfworker_test_btn.setEnabled(ready)
        _apply_test_glow(cfworker_test_btn, enabled=ready)

    cfproxy_worker_enabled_cb.toggled.connect(lambda _v: _sync_cfworker())
    cfproxy_worker_domain_edit.textChanged.connect(lambda _v: _sync_cfworker())
    _sync_cfworker()

    cf_test_btn.clicked.connect(lambda _=False: _on_cf_test(cfproxy_user_domain_enabled_cb,
                                                            cfproxy_user_domain_edit,
                                                            cf_test_btn))
    cfworker_test_btn.clicked.connect(lambda _=False: _on_cfworker_test(cfproxy_worker_enabled_cb,
                                                                        cfproxy_worker_domain_edit,
                                                                        cfworker_test_btn))

    # logs -------------------------------------------------
    sec, sec_lay = _section_frame(t("section.logs"), theme)
    lay.addWidget(sec)

    verbose_cb = _checkbox_row(
        sec_lay, t("label.verbose"), bool(cfg.get("verbose", False)), tip=t("tip.verbose")
    )

    adv_rows = [
        (t("label.buf_kb"), "buf_kb", t("tip.buf_kb")),
        (t("label.pool_size"), "pool_size", t("tip.pool")),
        (t("label.log_max_mb"), "log_max_mb", t("tip.log_mb")),
    ]
    adv_entries: List[QLineEdit] = []
    adv_keys = ("buf_kb", "pool_size", "log_max_mb")
    for label_text, key, tip in adv_rows:
        sec_lay.addWidget(_q_label(label_text, size=11))
        adv_e = QLineEdit(str(cfg.get(key, default_config[key])))
        adv_e.setObjectName("FieldEntry")
        adv_e.setFixedHeight(36)
        adv_e.setToolTip(tip)
        sec_lay.addWidget(adv_e)
        adv_entries.append(adv_e)

    # updates ---------------------------------------------
    sec, sec_lay = _section_frame(t("section.updates"), theme)
    lay.addWidget(sec)

    check_updates_cb = _checkbox_row(
        sec_lay, t("label.check_updates"),
        bool(cfg.get("check_updates", default_config.get("check_updates", True))),
        tip=t("tip.check_updates"),
    )

    st = get_status()
    if st.get("error"):
        upd_status = t("updates.status_error")
    elif not st.get("checked"):
        upd_status = t("updates.status_pending")
    elif st.get("has_update") and st.get("latest"):
        upd_status = t("updates.status_available", latest=st["latest"], current=__version__)
    elif st.get("ahead_of_release") and st.get("latest"):
        upd_status = t("updates.status_ahead", current=__version__, latest=st["latest"])
    else:
        upd_status = t("updates.status_latest")
    sec_lay.addWidget(_q_label(upd_status, size=11))

    rel_url = (st.get("html_url") or "").strip() or RELEASES_PAGE_URL

    update_btn_row = QWidget()
    ubr = QHBoxLayout(update_btn_row)
    ubr.setContentsMargins(0, 0, 0, 0)
    ubr.setSpacing(10)
    open_btn = QPushButton(t("button.open_release"))
    open_btn.setObjectName("GhostButton")
    open_btn.setMinimumHeight(38)
    open_btn.clicked.connect(lambda u=rel_url: webbrowser.open(u))
    ubr.addWidget(open_btn, 1)
    if st.get("has_update") and on_update_click is not None:
        upd_btn = QPushButton(t("button.update"))
        upd_btn.setObjectName("Primary")
        upd_btn.setMinimumHeight(38)
        upd_btn.clicked.connect(on_update_click)
        ubr.addWidget(upd_btn, 1)
    sec_lay.addWidget(update_btn_row)

    autostart_cb = None
    if show_autostart:
        sec, sec_lay = _section_frame(t("section.windows_startup"), theme)
        lay.addWidget(sec)
        autostart_cb = _checkbox_row(
            sec_lay, t("label.autostart"), bool(autostart_value), tip=t("tip.autostart")
        )
        sec_lay.addWidget(_q_label(t("label.autostart_hint"), size=11))

    lay.addStretch(1)

    return QtFormWidgets(
        host_edit=host_edit, port_edit=port_edit, secret_edit=secret_edit,
        dc_text=dc_text, verbose_cb=verbose_cb,
        adv_entries=adv_entries, adv_keys=adv_keys,
        autostart_cb=autostart_cb, check_updates_cb=check_updates_cb,
        cfproxy_cb=cfproxy_cb,
        cfproxy_user_domain_enabled_cb=cfproxy_user_domain_enabled_cb,
        cfproxy_user_domain_edit=cfproxy_user_domain_edit,
        cfproxy_worker_enabled_cb=cfproxy_worker_enabled_cb,
        cfproxy_worker_domain_edit=cfproxy_worker_domain_edit,
        appearance_control=theme_combo,
        language_combo=language_combo,
    )


def _apply_test_glow(btn: QPushButton, *, enabled: bool) -> None:
    """Apply or remove an orange glow effect on a Test button.
    
    When enabled=True, adds a pulsing orange glow shadow to indicate
    the button is ready to test (similar to CF Worker section behavior).
    """
    from PySide6.QtWidgets import QGraphicsDropShadowEffect
    from PySide6.QtGui import QColor
    
    if enabled:
        glow = QGraphicsDropShadowEffect(btn)
        glow.setBlurRadius(18)
        glow.setColor(QColor(255, 149, 0, 120))  # Orange glow
        glow.setOffset(0, 0)  # Centered glow (no offset = aura)
        btn.setGraphicsEffect(glow)
    else:
        btn.setGraphicsEffect(None)


def _on_cf_test(enabled_cb: Any, domain_edit: QLineEdit, btn: QPushButton) -> None:
    user_domains = coerce_domain_list(domain_edit.text()) if enabled_cb.isChecked() else []
    btn.setText(t("button.test_loading"))
    btn.setEnabled(False)

    if user_domains:
        def _worker():
            try:
                per = _run_cfproxy_multi_test(user_domains)
                qt_schedule(lambda: _show_multi_connectivity_results(
                    btn.window(), t("connectivity.cfproxy_title"), per, label_prefix='kws',
                ))
            except Exception as exc:
                log.error("CF proxy test failed: %s", exc)
            finally:
                qt_schedule(lambda: _restore_test_btn(btn, t("button.test")))

        threading.Thread(target=_worker, daemon=True).start()
    else:
        def _worker_auto():
            try:
                ok_domain, res = _run_cfproxy_auto_test(balancer.domains)
                qt_schedule(lambda: _show_connectivity_results(
                    btn.window(), t("connectivity.cfproxy_title"), res,
                    domain=ok_domain or '', auto_mode=True,
                    unavailable_message=t("connectivity.cf_auto_fail"),
                ))
            except Exception as exc:
                log.error("CF proxy auto-test failed: %s", exc)
            finally:
                qt_schedule(lambda: _restore_test_btn(btn, t("button.test")))

        threading.Thread(target=_worker_auto, daemon=True).start()


def _restore_test_btn(btn: QPushButton, text: str) -> None:
    if btn is not None:
        btn.setText(text)
        btn.setEnabled(True)


def _on_cfworker_test(enabled_cb: Any, domain_edit: QLineEdit, btn: QPushButton) -> None:
    domains = coerce_domain_list(domain_edit.text())
    if not enabled_cb.isChecked() or not domains:
        return
    btn.setText(t("button.test_loading"))
    btn.setEnabled(False)

    def _worker():
        try:
            per = _run_cfworker_multi_test(domains)
            qt_schedule(lambda: _show_multi_connectivity_results(
                btn.window(), t("connectivity.cfworker_title"), per, label_prefix='DC',
            ))
        except Exception as exc:
            log.error("CF worker test failed: %s", exc)
        finally:
            qt_schedule(lambda: _restore_test_btn(btn, t("button.test")))

    threading.Thread(target=_worker, daemon=True).start()


# --------------------------------------------------------------------------
# footer + scroll
# --------------------------------------------------------------------------


def tray_settings_scroll_and_footer(theme: Any) -> Tuple[Any, Any]:
    """Return (content_widget, footer_widget) for the settings scroll area."""
    from PySide6.QtWidgets import QWidget as _QW

    content = _QW()
    content.setObjectName("ScrollContent")

    footer = _QW()
    footer.setObjectName("Footer")

    return content, footer


def install_tray_config_buttons(
    footer: Any,
    theme: Any,
    *,
    on_save: Callable[[], None],
    on_cancel: Callable[[], None],
) -> None:
    if footer.layout() is not None:
        while footer.layout().count():
            item = footer.layout().takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        from PySide6.QtWidgets import QLayout
        QLayout().deleteLater()

    fl = QHBoxLayout(footer)
    fl.setContentsMargins(0, 12, 0, 0)
    fl.setSpacing(12)

    save_btn = QPushButton(t("button.save"))
    save_btn.setObjectName("Primary")
    save_btn.setMinimumHeight(42)
    save_btn.setToolTip(t("tip.save"))
    save_btn.clicked.connect(on_save)
    # Equal width: both buttons stretch equally
    fl.addWidget(save_btn, 1)

    cancel_btn = QPushButton(t("button.cancel"))
    cancel_btn.setObjectName("GhostButton")
    cancel_btn.setMinimumHeight(42)
    # Match Primary button padding for equal visual width
    cancel_btn.setStyleSheet("""
        QPushButton#GhostButton {
            padding: 10px 24px;
            font-size: 14px;
            font-weight: 600;
            min-height: 42px;
        }
    """)
    cancel_btn.clicked.connect(on_cancel)
    fl.addWidget(cancel_btn, 1)


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def _dc_validation_message(error: ValueError) -> str:
    exc_entry = getattr(error, "entry", None)
    if exc_entry is None:
        return str(error)
    kind = getattr(error, "kind", "invalid")
    if kind == "format":
        return t("validation.dc_format", entry=exc_entry)
    return t("validation.dc_invalid", entry=exc_entry)


def merge_adv_from_form(widgets: QtFormWidgets, base: Dict[str, Any], default_config: dict) -> None:
    for i, key in enumerate(widgets.adv_keys):
        entry = widgets.adv_entries[i]
        try:
            val = float(entry.text().strip())
            if key in ("buf_kb", "pool_size"):
                val = int(val)
            base[key] = val
        except ValueError:
            base[key] = default_config[key]


def validate_config_form(widgets: QtFormWidgets, default_config: dict, *,
                         include_autostart: bool) -> Union[dict, str]:
    host_val = widgets.host_edit.text().strip()
    try:
        _socket.inet_aton(host_val)
    except OSError:
        return t("validation.bad_host")

    try:
        port_val = int(widgets.port_edit.text().strip())
        if not (1 <= port_val <= 65535):
            raise ValueError
    except ValueError:
        return t("validation.bad_port")

    lines = [
        line.strip()
        for line in widgets.dc_text.toPlainText().strip().splitlines()
        if line.strip()
    ]
    try:
        parse_dc_ip_list(lines)
    except ValueError as e:
        return _dc_validation_message(e)

    secret_val = widgets.secret_edit.text().strip()
    if len(secret_val) != 32:
        return t("validation.bad_secret_len")
    try:
        bytes.fromhex(secret_val)
    except ValueError:
        return t("validation.bad_secret_hex")

    new_cfg: Dict[str, Any] = {
        "host": host_val,
        "port": port_val,
        "secret": secret_val,
        "dc_ip": lines,
        "verbose": bool(widgets.verbose_cb.isChecked()),
    }
    if include_autostart:
        new_cfg["autostart"] = (
            bool(widgets.autostart_cb.isChecked())
            if widgets.autostart_cb is not None
            else False
        )

    merge_adv_from_form(widgets, new_cfg, default_config)
    if widgets.check_updates_cb is not None:
        new_cfg["check_updates"] = bool(widgets.check_updates_cb.isChecked())
    if widgets.cfproxy_cb is not None:
        new_cfg["cfproxy"] = bool(widgets.cfproxy_cb.isChecked())
    if widgets.cfproxy_user_domain_enabled_cb is not None:
        new_cfg["cfproxy_user_domain_enabled"] = bool(widgets.cfproxy_user_domain_enabled_cb.isChecked())
    if widgets.cfproxy_user_domain_edit is not None:
        new_cfg["cfproxy_user_domain"] = coerce_domain_list(widgets.cfproxy_user_domain_edit.text())
    if widgets.cfproxy_worker_enabled_cb is not None:
        new_cfg["cfproxy_worker_enabled"] = bool(widgets.cfproxy_worker_enabled_cb.isChecked())
    if widgets.cfproxy_worker_domain_edit is not None:
        new_cfg["cfproxy_worker_domain"] = coerce_domain_list(widgets.cfproxy_worker_domain_edit.text())
    if widgets.appearance_control is not None:
        new_cfg["appearance"] = _appearance_to_cfg(widgets.appearance_control.currentText())
    if widgets.language_combo is not None:
        new_cfg["language"] = language_from_label(widgets.language_combo.currentText()).value
    return new_cfg


# --------------------------------------------------------------------------
# first run
# --------------------------------------------------------------------------


def populate_first_run_window(
    content: QWidget,
    theme: Any,
    *,
    host: str,
    port: int,
    secret: str,
    on_done: Callable[[bool], None],
) -> None:
    link_host = get_link_host(host)
    tg_url = f"tg://proxy?server={link_host}&port={port}&secret=dd{secret}"

    from PySide6.QtCore import Qt

    lay = QVBoxLayout(content)
    lay.setContentsMargins(24, 20, 24, 20)
    lay.setSpacing(16)

    header = QWidget()
    hlay = QHBoxLayout(header)
    hlay.setContentsMargins(0, 0, 0, 0)
    hlay.setSpacing(12)
    title_lbl = QLabel("SwiftProxy")
    title_lbl.setObjectName("Title")

    pix = _icon_pixmap(48)
    if pix is not None:
        pix_lbl = QLabel(header)
        pix_lbl.setPixmap(pix)
        hlay.addWidget(pix_lbl)
    else:
        hlay.addWidget(QLabel("◆"))
    hlay.addWidget(title_lbl, 1)
    lay.addWidget(header)

    sections = [
        (t("first_run.how_to"), True),
        (t("first_run.auto"), True),
        (t("first_run.auto_hint"), False),
        (t("first_run.auto_link", url=tg_url), False),
        ("\n" + t("first_run.manual"), True),
        (t("first_run.manual_path"), False),
        (t("first_run.manual_mtproto", host=link_host, port=port), False),
        (t("first_run.manual_secret", secret=secret), False),
    ]

    text_lbl = QLabel()
    text_lbl.setObjectName("FirstRunText")
    text_lbl.setWordWrap(True)
    text_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

    html_parts = []
    for text, bold in sections:
        if text.startswith("\n"):
            if html_parts:
                html_parts.append("<br/><br/>")
            text = text[1:]
        styled = f"<b>{html_escape(text)}</b>" if bold else html_escape(text)
        html_parts.append(styled)
    text_lbl.setText("<br/>".join(html_parts))
    lay.addWidget(text_lbl, 1)

    from ui.qt.qt_widgets import IOSToggle
    from PySide6.QtWidgets import QLabel as _QLabel

    # Auto-open toggle with separate label (palette-aware)
    auto_row = QWidget()
    ar = QHBoxLayout(auto_row)
    ar.setContentsMargins(0, 0, 0, 0)
    ar.setSpacing(12)
    
    from PySide6.QtWidgets import QLabel as _QLabel
    from PySide6.QtGui import QPalette as _QPal
    auto_label = _QLabel(t("first_run.open_now"))
    auto_label.setStyleSheet("font-size: 14px; background: transparent;")
    auto_label.setForegroundRole(_QPal.ColorRole.WindowText)
    ar.addWidget(auto_label, 1)
    
    auto_toggle = IOSToggle(checked=True)
    auto_toggle.setToolTip(t("tip.autostart"))
    ar.addWidget(auto_toggle, 0)
    
    lay.addWidget(auto_row)

    def on_ok() -> None:
        on_done(auto_toggle.isChecked())

    start_btn = QPushButton(t("button.start"))
    start_btn.setObjectName("Primary")
    start_btn.setMinimumHeight(44)
    start_btn.clicked.connect(on_ok)
    lay.addWidget(start_btn, 0, alignment=Qt.AlignmentFlag.AlignHCenter)


def html_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))