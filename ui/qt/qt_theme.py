"""iOS 26 Liquid Glass theme for SwiftProxy Qt UI (PySide6).

Warm orange gradient tones with translucent glass surfaces, soft shadows
and frosted-glass borders. Inspired by the "Liquid Glass" design language.

Key improvements:
- Better spacing and alignment
- Proper glass effect simulation with inner shadows for inputs
- Consistent visual hierarchy
- Smooth animations and pill-shaped buttons
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Optional, Tuple


@dataclass(frozen=True)
class QtTheme:
    # brand accent (orange gradient) — primary CTA
    brand: Tuple[str, str] = ("#FF9500", "#FF5E3A")       # light, dark
    brand_hover: Tuple[str, str] = ("#FF8200", "#E5532F") # hover
    brand_pressed: Tuple[str, str] = ("#E57400", "#CC4A2A")

    # iOS system chrome (orange-tinted)
    accent: Tuple[str, str] = ("#FF9500", "#FF8A00")      # systemOrange
    accent_hover: Tuple[str, str] = ("#FF8200", "#FFA033")
    accent_soft: Tuple[str, str] = ("#FFE4CC", "#3D2A1A")

    # Warm glass surfaces
    bg: Tuple[str, str] = ("#FFF8F0", "#1C1814")          # warm grouped background (lighter)
    bg_bottom: Tuple[str, str] = ("#FFE8D6", "#241A12")
    card: Tuple[str, str] = ("#FFFFFF", "#2C2018")        # solid card base
    glass: Tuple[str, str] = ("#FFFFFFB3", "#2C2018B3")   # translucent glass (with alpha)
    field_inset: Tuple[str, str] = ("#FFF5EB", "#3D2A1E") # inset input fill (warmer)
    border: Tuple[str, str] = ("#FFD6A5", "#4A3526")      # hairlines / dividers
    separators: Tuple[str, str] = ("#FFD6A5", "#5A4030")

    text_primary: Tuple[str, str] = ("#1A1410", "#FFE8D6")
    text_secondary: Tuple[str, str] = ("#8B6914", "#C4A080")
    text_on_accent: Tuple[str, str] = ("#FFFFFF", "#FFFFFF")

    # Switches: orange instead of green
    switch_on: Tuple[str, str] = ("#FF9500", "#FF8A00")
    switch_off: Tuple[str, str] = ("#E5E5EA", "#3D3D3D")  # iOS-style gray
    switch_thumb: Tuple[str, str] = ("#FFFFFF", "#FFFFFF")

    menu_active: Tuple[str, str] = ("#FF9500", "#FF8A00")
    menu_hover: Tuple[str, str] = ("#FFF0E0", "#3D2A1E")
    danger: Tuple[str, str] = ("#D70015", "#FF453A")
    success: Tuple[str, str] = ("#FF9500", "#FF8A00")     # orange "success"

    radius: int = 16
    inner_radius: int = 12
    pill_radius: int = 20

    # Glass effect parameters
    glass_alpha: float = 0.75          # surface opacity for glass effect
    glass_border_alpha: float = 0.4    # border opacity
    glass_blur_radius: int = 24        # blur radius in px

    ui_font_family: str = "Segoe UI"
    mono_font_family: str = "Consolas"

    def color(self, attr: str, appearance: str) -> str:
        value = getattr(self, attr)
        if not isinstance(value, tuple):
            return str(value)
        idx = 1 if appearance == "dark" else 0
        return value[min(idx, len(value) - 1)]

    def css(self, attr: str, scheme: str) -> str:
        return self.color(attr, scheme)


def qt_theme_for_platform() -> QtTheme:
    if sys.platform == "win32":
        return QtTheme(ui_font_family="Segoe UI", mono_font_family="Consolas")
    return QtTheme(ui_font_family="Sans", mono_font_family="Monospace")


_APPEARANCE_MAP = {"auto": "system", "light": "light", "dark": "dark"}

_last_applied_theme: Optional[QtTheme] = None
_last_applied_appearance: str = "dark"


def current_appearance() -> str:
    """Return the appearance most recently applied via apply_qt_palette."""
    return _last_applied_appearance


def current_theme() -> QtTheme:
    if _last_applied_theme is not None:
        return _last_applied_theme
    return qt_theme_for_platform()


def resolve_appearance(mode: str, app: Optional[Any] = None) -> str:
    """Map config mode (auto/light/dark) to 'light'/'dark'."""
    key = _APPEARANCE_MAP.get(mode, "system")
    if key == "system":
        return qt_appearance_now(app)
    return key


def qt_appearance_now(app: Any = None) -> str:
    """Detect the current system appearance."""
    try:
        import sys as _sys
        from PySide6.QtGui import QGuiApplication

        if _sys.platform == "win32":
            from utils.win32_theme import is_windows_dark_theme
            if is_windows_dark_theme():
                return "dark"

        qapp = app or QGuiApplication.instance()
        if qapp is not None:
            is_dark = qapp.palette().color(QGuiApplication.ColorRole.Window).lightness() < 100
            if is_dark:
                return "dark"
            try:
                scheme = qapp.styleHints().colorScheme()
                from PySide6.QtCore import Qt
                if scheme == Qt.ColorScheme.Dark:
                    return "dark"
                if scheme == Qt.ColorScheme.Light:
                    return "light"
            except Exception:
                pass
        return "light"
    except Exception:
        return "light"


def apply_qt_palette(app: Any, theme: QtTheme, appearance: str) -> None:
    """Apply a Fusion-palette + QSS stylesheet with Liquid Glass styling."""
    global _last_applied_theme, _last_applied_appearance
    _last_applied_theme = theme
    _last_applied_appearance = appearance

    def c(attr: str) -> str:
        return theme.css(attr, appearance)

    # Determine scheme before install so QPalette picks sensible base colors.
    if c("bg") == "#1C1814":
        app.setStyle("Fusion")

    app.setPalette(_build_palette(theme, appearance))
    app.setStyleSheet(_build_stylesheet(theme, appearance))


def _build_palette(theme: QtTheme, appearance: str) -> Any:
    from PySide6.QtGui import QColor, QPalette

    pal = QPalette()
    bg = QColor(theme.css("bg", appearance))
    card = QColor(theme.css("card", appearance))
    inset = QColor(theme.css("field_inset", appearance))
    text = QColor(theme.css("text_primary", appearance))
    sub = QColor(theme.css("text_secondary", appearance))
    accent = QColor(theme.css("accent", appearance))

    pal.setColor(QPalette.ColorRole.Window, bg)
    pal.setColor(QPalette.ColorRole.WindowText, text)
    pal.setColor(QPalette.ColorRole.Base, card)
    pal.setColor(QPalette.ColorRole.AlternateBase, inset)
    pal.setColor(QPalette.ColorRole.Text, text)
    pal.setColor(QPalette.ColorRole.Button, inset)
    pal.setColor(QPalette.ColorRole.ButtonText, text)
    pal.setColor(QPalette.ColorRole.Highlight, accent)
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor("#000000"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, sub)
    pal.setColor(QPalette.ColorRole.Link, accent)
    return pal


def _build_stylesheet(theme: QtTheme, appearance: str) -> str:
    def c(attr: str) -> str:
        return theme.css(attr, appearance)

    radius = theme.radius
    inner = theme.inner_radius
    pill = theme.pill_radius

    def rgba(hex_color: str, alpha: float) -> str:
        """Convert hex (#RRGGBB or #RRGGBBAA) to rgba()."""
        h = hex_color.lstrip("#")
        if len(h) == 8:
            return f"rgba({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}, {alpha})"
        return f"rgba({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}, {alpha})"

    # Glass surface colors (semi-transparent)
    glass_card = rgba(c("card"), theme.glass_alpha)
    glass_inset = rgba(c("field_inset"), 0.7)
    glass_border = rgba(c("border"), theme.glass_border_alpha)
    glass_card_hover = rgba(c("card"), theme.glass_alpha + 0.08)

    # Gradient stops for orange accent
    grad_brand = f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c('brand')}, stop:1 {c('brand_hover')})"
    grad_accent_bar = f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {c('accent')}, stop:1 {c('accent_soft')})"
    grad_ver_badge = f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c('accent')}, stop:1 {c('brand_hover')})"

    fmt = {
        "bg": c("bg"),
        "bg_bottom": c("bg"),
        "card": c("card"),
        "inset": c("field_inset"),
        "border": c("border"),
        "sep": c("separators"),
        "text": c("text_primary"),
        "sub": c("text_secondary"),
        "accent": c("accent"),
        "accent_hover": c("accent_hover"),
        "brand": c("brand"),
        "brand_hover": c("brand_hover"),
        "brand_pressed": c("brand_pressed"),
        "accent_text": c("text_on_accent"),
        "accent_soft": c("accent_soft"),
        "switch_on": c("switch_on"),
        "switch_off": c("switch_off"),
        "switch_thumb": c("switch_thumb"),
        "danger": c("danger"),
        "radius": radius,
        "inner": inner,
        "pill": pill,
        "menu_active": c("menu_active"),
        "menu_hover": c("menu_hover"),
        # Glass surfaces
        "glass_card": glass_card,
        "glass_card_hover": glass_card_hover,
        "glass_inset": glass_inset,
        "glass_border": glass_border,
        # Gradients
        "grad_brand": grad_brand,
        "grad_accent_bar": grad_accent_bar,
        "grad_ver_badge": grad_ver_badge,
        # Shadows / highlights
        "shadow": rgba("#000000", 0.08),
        "highlight_edge": rgba("#FFFFFF", 0.3),
        "text_dim": rgba(c("text_secondary"), 0.7),
        # Ice border for buttons (soft orange glow)
        "ice_border": rgba(c("accent"), 0.3),
        "seg_track": rgba(c("field_inset"), 0.5),
        "seg_pill": rgba(c("card"), 0.95),
        "ghost_fill": rgba(c("field_inset"), 0.4),
    }

    qss = f"""
/* ========================================================================
   iOS 26 Liquid Glass Theme — Orange Gradient
   Refined version with better spacing, alignment, and glass effects
   ======================================================================== */

QWidget {{
    background: transparent;
    /* Color from palette(WindowText) — auto-updates on theme change */
    font-family: "{theme.ui_font_family}";
    font-size: 13px;
}}

QMainWindow, QDialog {{
    background: {fmt['bg']};
}}

/* --- Main window background with subtle gradient --- */
QDialog {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
        stop:0 {fmt['bg']}, 
        stop:1 {fmt['bg_bottom']});
}}

/* --- Glass card surface (handled by GlassCard widget) --- */
QFrame {{
    background: transparent;
}}

QFrame#Card {{
    background: transparent;
    border: none;
}}

/* --- header / labels --- */
QLabel {{
    background: transparent;
    /* Color inherited from palette(WindowText) */
}}

QLabel#Title {{
    font-size: 24px;
    font-weight: 700;
    color: {fmt['text']};
    letter-spacing: -0.3px;
}}

QLabel#Subtitle {{
    color: {fmt['sub']};
    font-size: 13px;
    font-weight: 500;
}}

QLabel#SectionTitle {{
    font-size: 12px;
    font-weight: 600;
    color: {fmt['accent']};
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 4px 0;
}}

QLabel#Secondary {{
    color: {fmt['sub']};
    font-size: 12px;
    font-weight: 400;
}}

QLabel#FirstRunText {{
    font-size: 13px;
    line-height: 1.6;
}}

/* --- Buttons (Liquid Glass) --- */
QPushButton {{
    background: {fmt['glass_card']};
    color: {fmt['text']};
    border: 1px solid {fmt['glass_border']};
    border-radius: {fmt['inner']}px;
    padding: 8px 16px;
    font-weight: 500;
    font-size: 13px;
    min-height: 32px;
}}

QPushButton:hover {{
    background: {fmt['glass_card_hover']};
    border-color: {rgba(c('accent'), 0.5)};
}}

QPushButton:pressed {{
    background: {rgba(c('accent_soft'), 0.6)};
    border-color: {c('accent')};
}}

QPushButton:disabled {{
    color: {fmt['text_dim']};
    background: {rgba(c('card'), 0.3)};
    border-color: {rgba(c('border'), 0.2)};
}}

/* Primary button: orange gradient */
QPushButton#Primary {{
    background: {fmt['grad_brand']};
    color: {fmt['accent_text']};
    border: none;
    border-radius: {fmt['pill']}px;
    font-weight: 600;
    font-size: 14px;
    padding: 10px 24px;
    min-height: 40px;
}}

QPushButton#Primary:hover {{
    background: {c('brand_hover')};
}}

QPushButton#Primary:pressed {{
    background: {c('brand_pressed')};
}}

QPushButton#Primary:disabled {{
    background: {rgba(c('brand'), 0.4)};
    color: {rgba('#FFFFFF', 0.6)};
}}

/* Danger button */
QPushButton#Danger {{
    background: {fmt['danger']};
    color: #ffffff;
    border: none;
    border-radius: {fmt['pill']}px;
    font-weight: 600;
}}

QPushButton#Danger:hover {{
    background: #ff453a;
}}

/* Ghost button (glass fill) */
QPushButton#Ghost, QPushButton#GhostButton {{
    background: {fmt['ghost_fill']};
    border: 1px solid {fmt['glass_border']};
    color: {fmt['text']};
    border-radius: {fmt['pill']}px;
    font-weight: 500;
}}

QPushButton#Ghost:hover, QPushButton#GhostButton:hover {{
    background: {fmt['glass_card_hover']};
    border-color: {c('accent')};
    color: {fmt['accent']};
}}

/* Quiet button (text-only, no background) */
QPushButton#Quiet {{
    background: transparent;
    border: none;
    color: {fmt['accent']};
    font-weight: 500;
    padding: 4px 8px;
}}

QPushButton#Quiet:hover {{
    color: {fmt['brand_hover']};
}}

/* --- Line edits / text inputs (glass inset with inner shadow) --- */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background: {fmt['glass_inset']};
    color: {fmt['text']};
    border: 1px solid {fmt['glass_border']};
    border-radius: {fmt['inner']}px;
    padding: 6px 12px;
    font-size: 13px;
    selection-background-color: {fmt['accent']};
    selection-color: #ffffff;
    qproperty-alignment: 'AlignVCenter';
}}

QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover {{
    border-color: {rgba(c('accent'), 0.5)};
}}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 2px solid {fmt['accent']};
    padding: 7px 11px;
    background: {rgba(c('field_inset'), 0.9)};
}}

/* Combo box — iOS 26 Liquid Glass style dropdown */
QComboBox {{
    background: {fmt['glass_inset']};
    border: 1px solid {fmt['glass_border']};
    border-radius: {fmt['inner']}px;
    padding: 6px 14px;
    min-height: 24px;
    font-weight: 500;
}}

QComboBox:hover {{
    border-color: {rgba(c('accent'), 0.5)};
    background: {fmt['glass_card_hover']};
}}

QComboBox::drop-down {{
    border: none;
    width: 28px;
    subcontrol-origin: padding;
    subcontrol-position: top right;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {fmt['accent']};
    margin-right: 12px;
}}

QComboBox QAbstractItemView {{
    background: {fmt['glass_card']};
    border: 1px solid {fmt['glass_border']};
    selection-background-color: {fmt['accent']};
    selection-color: #ffffff;
    outline: none;
    border-radius: {fmt['inner']}px;
    padding: 6px;
}}

QComboBox QAbstractItemView::item {{
    padding: 8px 14px;
    border-radius: 8px;
    min-height: 20px;
}}

QComboBox QAbstractItemView::item:hover {{
    background: {rgba(c('accent_soft'), 0.5)};
}}

QComboBox QAbstractItemView::item:selected {{
    background: {fmt['accent']};
    color: #ffffff;
}}

/* --- Segmented control --- */
QFrame#Segmented {{
    background: {fmt['seg_track']};
    border: 1px solid {fmt['glass_border']};
    border-radius: {fmt['pill']}px;
    padding: 3px;
}}

QFrame#Segmented QPushButton {{
    background: transparent;
    border: none;
    color: {fmt['text_dim']};
    border-radius: {(fmt['pill'] - 3)}px;
    padding: 6px 16px;
    font-weight: 500;
    font-size: 12px;
    min-height: 28px;
}}

QFrame#Segmented QPushButton:hover {{
    color: {fmt['text']};
    background: {rgba(c('accent_soft'), 0.3)};
}}

QFrame#Segmented QPushButton:checked {{
    background: {fmt['seg_pill']};
    color: {fmt['text']};
    font-weight: 600;
    border: 1px solid {rgba(c('border'), 0.3)};
}}

QFrame#Segmented QPushButton:checked:hover {{
    background: {fmt['glass_card_hover']};
}}

QFrame#Segmented QPushButton:checked:disabled {{
    background: {rgba(c('card'), 0.4)};
    color: {fmt['text_dim']};
}}

/* --- Small round action buttons (Test, Doc, Regen) --- */
QPushButton#TestButton {{
    background: {fmt['grad_brand']};
    color: #ffffff;
    border: none;
    border-radius: {fmt['inner']}px;
    font-size: 12px;
    font-weight: 600;
    min-height: 28px;
    max-height: 28px;
    padding: 4px 14px;
}}

QPushButton#TestButton:disabled {{
    background: {fmt['glass_inset']};
    color: {fmt['text_dim']};
}}

QPushButton#TestButton:hover {{
    background: {c('brand_hover')};
}}

/* Doc button: glass circle */
QPushButton#DocButton {{
    background: {fmt['glass_card']};
    color: {fmt['accent']};
    border: 1px solid {fmt['glass_border']};
    border-radius: 18px;
    font-size: 16px;
    font-weight: 700;
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
    padding: 0;
    qproperty-alignment: 'AlignCenter';
}}

QPushButton#DocButton:hover {{
    background: {fmt['glass_card_hover']};
    border-color: {c('accent')};
    color: {fmt['brand_hover']};
}}

/* Regen button: glass circle */
QPushButton#RegenButton {{
    background: {fmt['glass_card']};
    color: {fmt['accent']};
    border: 1px solid {fmt['glass_border']};
    border-radius: 16px;
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
    padding: 0;
    qproperty-alignment: 'AlignCenter';
}}

QPushButton#RegenButton:hover {{
    background: {fmt['glass_card_hover']};
    border-color: {c('accent')};
    color: {fmt['brand_hover']};
}}

/* Fund button (heart): glass circle with gradient */
QPushButton#FundButton {{
    background: {fmt['grad_brand']};
    color: #ffffff;
    border: none;
    border-radius: 20px;
    font-size: 18px;
    font-weight: 700;
    min-width: 40px;
    max-width: 40px;
    min-height: 40px;
    max-height: 40px;
    padding: 0;
}}

QPushButton#FundButton:hover {{
    background: {c('brand_hover')};
}}

/* --- Accent bar (section divider) --- */
QFrame#AccentBar {{
    background: {fmt['grad_accent_bar']};
    border-radius: 2px;
}}

/* --- Version badge (orange gradient pill) --- */
QLabel#VerBadge {{
    background: {fmt['grad_ver_badge']};
    color: #ffffff;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
    padding: 3px 10px;
}}

/* --- Monospace label --- */
QLabel#Monospace {{
    font-family: "{theme.mono_font_family}";
    font-size: 12px;
}}

/* --- Transparent containers --- */
QWidget#ScrollContent, QWidget#SectionParent, QWidget#Footer {{
    background: transparent;
}}

/* --- Scrollbars (minimal, translucent) --- */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
    border-radius: 4px;
}}

QScrollBar::handle:vertical {{
    background: {rgba(c('accent'), 0.3)};
    border-radius: 4px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{
    background: {rgba(c('accent'), 0.5)};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal {{
    background: {rgba(c('accent'), 0.3)};
    border-radius: 4px;
    min-width: 24px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {rgba(c('accent'), 0.5)};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* --- Tooltips (dark glass) --- */
QToolTip {{
    background: {rgba("#1C1814", 0.95)};
    color: #FFE8D6;
    border: 1px solid {rgba(c('accent'), 0.4)};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 12px;
}}

/* --- Message boxes (glass fallback) --- */
QMessageBox {{
    background: {fmt['glass_card']};
}}

QMessageBox QLabel {{
    color: {fmt['text']};
    font-size: 13px;
}}

QMessageBox QPushButton {{
    min-width: 80px;
}}

/* --- Tab bars (if used) --- */
QTabBar::tab {{
    background: {fmt['glass_inset']};
    border: 1px solid {fmt['glass_border']};
    border-radius: {fmt['inner']}px;
    padding: 8px 16px;
    margin-right: 4px;
    font-weight: 500;
    color: {fmt['sub']};
}}

QTabBar::tab:selected {{
    background: {fmt['grad_brand']};
    color: #ffffff;
    border: none;
}}

QTabBar::tab:hover:!selected {{
    background: {fmt['glass_card_hover']};
    color: {fmt['text']};
}}

/* --- Group boxes (if used) --- */
QGroupBox {{
    background: {fmt['glass_card']};
    border: 1px solid {fmt['glass_border']};
    border-radius: {fmt['radius']}px;
    margin-top: 12px;
    padding: 16px 12px 12px 12px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: {fmt['accent']};
    font-weight: 600;
    font-size: 12px;
}}

/* --- Progress bars (orange gradient) --- */
QProgressBar {{
    background: {fmt['glass_inset']};
    border: 1px solid {fmt['glass_border']};
    border-radius: {fmt['inner']}px;
    text-align: center;
    color: {fmt['text']};
    font-weight: 500;
}}

QProgressBar::chunk {{
    background: {fmt['grad_brand']};
    border-radius: {fmt['inner']}px;
}}

/* --- Radio buttons --- */
QRadioButton {{
    background: transparent;
    color: {fmt['text']};
    spacing: 8px;
}}

QRadioButton::indicator {{
    width: 20px;
    height: 20px;
    border: 2px solid {fmt['glass_border']};
    border-radius: 10px;
    background: {fmt['glass_inset']};
}}

QRadioButton::indicator:hover {{
    border-color: {c('accent')};
}}

QRadioButton::indicator:checked {{
    background: {c('accent')};
    border-color: {c('accent')};
}}

/* --- Scroll area --- */
QScrollArea {{
    background: transparent;
    border: none;
}}
"""
    return qss


def anim_opacity(widget: Any, start: float, end: float, ms: int = 240) -> Any:
    """Return a running QPropertyAnimation on the widget's opacity (window)."""
    from PySide6.QtCore import QPropertyAnimation

    anim = QPropertyAnimation(widget, b"windowOpacity")
    anim.setDuration(ms)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.start()
    return anim


def anim_geometry(
    widget: Any, start: Tuple[int, int, int, int], end: Tuple[int, int, int, int], ms: int = 220
) -> Any:
    """Animate widget geometry (used for .move based slide)."""
    from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect

    anim = QPropertyAnimation(widget, b"geometry")
    anim.setDuration(ms)
    anim.setStartValue(QRect(*start))
    anim.setEndValue(QRect(*end))
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.start()
    return anim