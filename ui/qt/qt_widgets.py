"""Reusable iOS 26 Liquid Glass widgets for the Qt (PySide6) UI.

Features:
- Pixel-perfect iOS-style toggle switches (51x31px) with smooth thumb animation
- Advanced glass card widgets with layered translucent surfaces and refraction highlights
- Proper blur simulation using gradient overlays and inner shadows
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.qt.qt_theme import QtTheme


# =============================================================================
# iOS-Style Animated Toggle Switch (Pixel-perfect 51x31px)
# =============================================================================


class IOSToggle(QWidget):
    """Beautiful iOS-style toggle switch with smooth animation.
    
    Features:
    - Exact iOS dimensions: 51x31px
    - Smooth thumb animation (spring-like easing)
    - Orange gradient when ON, subtle glass-gray when OFF
    - White thumb with radial gradient for 3D volume and inner highlight
    - NO built-in label — use separate QLabel next to toggle
    """

    toggled = Signal(bool)

    def __init__(
        self,
        checked: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._checked = checked
        self._thumb_pos = 1.0 if checked else 0.0  # 0.0 = left, 1.0 = right
        self._hovered = False
        self._pressed = False

        # Animation: 250ms with OutBack for that signature iOS "spring" feel
        self._anim = QPropertyAnimation(self, b"thumbPos")
        self._anim.setDuration(250)
        self._anim.setEasingCurve(QEasingCurve.Type.OutBack)

        # Exact iOS toggle dimensions — NO layout, just the toggle
        self.setFixedSize(51, 31)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Initial state
        self._update_thumb_position()

    def _update_thumb_position(self) -> None:
        """Update internal thumb position without animation."""
        self._thumb_pos = 1.0 if self._checked else 0.0

    @Property(float)
    def thumbPos(self) -> float:
        return self._thumb_pos

    @thumbPos.setter
    def thumbPos(self, value: float) -> None:
        self._thumb_pos = value
        self.update()

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        if self._checked == checked:
            return
        self._checked = checked
        self._animate_toggle()
        self.toggled.emit(checked)

    def toggle(self) -> None:
        self.setChecked(not self._checked)

    def _animate_toggle(self) -> None:
        """Animate the thumb to the new position."""
        self._anim.stop()
        self._anim.setStartValue(self._thumb_pos)
        self._anim.setEndValue(1.0 if self._checked else 0.0)
        self._anim.start()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            self.toggle()
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        is_dark = self._is_dark_mode()

        # --- Draw Track ---
        track_rect = QRectF(0, 0, 51, 31)
        track_path = QPainterPath()
        track_path.addRoundedRect(track_rect, 15.5, 15.5)  # Half of height

        if self._checked:
            # ON state: vibrant orange gradient
            track_gradient = QLinearGradient(track_rect.topLeft(), track_rect.bottomRight())
            track_gradient.setColorAt(0, QColor("#FF9500"))
            track_gradient.setColorAt(1, QColor("#FF6B35"))
            
            if self._pressed:
                track_gradient.setColorAt(0, QColor("#E58600"))
                track_gradient.setColorAt(1, QColor("#E55F2F"))
            elif self._hovered:
                track_gradient.setColorAt(0, QColor("#FFA520"))
                track_gradient.setColorAt(1, QColor("#FF7B45"))
                
            painter.fillPath(track_path, QBrush(track_gradient))
        else:
            # OFF state: subtle glass-gray
            if is_dark:
                track_gradient = QLinearGradient(track_rect.topLeft(), track_rect.bottomRight())
                track_gradient.setColorAt(0, QColor("#3D3D3D"))
                track_gradient.setColorAt(1, QColor("#2A2A2A"))
            else:
                track_gradient = QLinearGradient(track_rect.topLeft(), track_rect.bottomRight())
                track_gradient.setColorAt(0, QColor("#E5E5EA"))
                track_gradient.setColorAt(1, QColor("#D1D1D6"))
                
            painter.fillPath(track_path, QBrush(track_gradient))
            
            # Inner shadow for OFF state depth
            inner_shadow = QColor(0, 0, 0, 15) if not is_dark else QColor(0, 0, 0, 30)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(inner_shadow)
            inner_path = QPainterPath()
            inner_path.addRoundedRect(track_rect.adjusted(1, 1, -1, -1), 14.5, 14.5)
            painter.drawPath(inner_path)

        # --- Draw Thumb ---
        thumb_size = 27
        thumb_margin = 2
        # Calculate X position based on animation value
        thumb_x = track_rect.left() + thumb_margin + (self._thumb_pos * (track_rect.width() - thumb_size - 2 * thumb_margin))
        thumb_y = track_rect.top() + thumb_margin
        thumb_rect = QRectF(thumb_x, thumb_y, thumb_size, thumb_size)

        # Thumb shadow (soft, offset down)
        painter.setPen(Qt.PenStyle.NoPen)
        shadow_color = QColor(0, 0, 0, 25)
        painter.setBrush(shadow_color)
        shadow_path = QPainterPath()
        shadow_path.addEllipse(thumb_rect.adjusted(0, 1.5, 0, 1.5))
        painter.drawPath(shadow_path)

        # Thumb body: Radial gradient for 3D volume
        thumb_gradient = QRadialGradient(thumb_rect.center().x(), thumb_rect.center().y() - 2, thumb_size / 2)
        thumb_gradient.setColorAt(0, QColor("#FFFFFF"))
        thumb_gradient.setColorAt(0.7, QColor("#F2F2F7"))
        thumb_gradient.setColorAt(1, QColor("#E5E5EA"))

        painter.setBrush(QBrush(thumb_gradient))
        painter.setPen(QPen(QColor(0, 0, 0, 8), 0.5))
        thumb_path = QPainterPath()
        thumb_path.addEllipse(thumb_rect)
        painter.drawPath(thumb_path)

        # Subtle highlight on thumb (top edge refraction)
        highlight_path = QPainterPath()
        highlight_rect = thumb_rect.adjusted(3, 2, -3, -thumb_size / 2)
        highlight_path.addEllipse(highlight_rect)
        painter.setBrush(QColor(255, 255, 255, 120))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(highlight_path)

        painter.end()

    def _is_dark_mode(self) -> bool:
        try:
            from ui.qt.qt_theme import current_appearance
            return current_appearance() == "dark"
        except Exception:
            return False

    def sizeHint(self) -> QSize:
        return QSize(51, 31)


# =============================================================================
# Glass Card Widget
# =============================================================================


class GlassCard(QFrame):
    """A glass-effect card with layered translucent surfaces.
    
    Simulates iOS Liquid Glass using:
    - Semi-transparent background with warm tint
    - Top-edge highlight (simulating light refraction)
    - Soft outer shadow
    - Subtle border
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._apply_shadow()

    def _apply_shadow(self) -> None:
        """Apply a soft drop shadow for depth."""
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(255, 149, 0, 20))  # Warm orange-tinted shadow
        shadow.setOffset(0, 6)
        self.setGraphicsEffect(shadow)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        is_dark = self._is_dark_mode()
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # Main glass surface
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)

        if is_dark:
            # Dark mode: warm dark glass
            base_color = QColor(44, 32, 24, 160)  # 63% opacity
            border_color = QColor(255, 149, 0, 40)
            highlight_color = QColor(255, 232, 214, 12)
        else:
            # Light mode: warm white glass
            base_color = QColor(255, 255, 255, 180)  # 70% opacity
            border_color = QColor(255, 149, 0, 35)
            highlight_color = QColor(255, 255, 255, 80)

        # Fill with glass color
        painter.fillPath(path, QBrush(base_color))

        # Top-edge highlight (glass refraction effect)
        highlight_path = QPainterPath()
        highlight_rect = rect.adjusted(1, 1, -1, -rect.height() * 0.65)
        highlight_path.addRoundedRect(highlight_rect, 15, 15)

        highlight_gradient = QLinearGradient(
            highlight_rect.topLeft(),
            highlight_rect.bottomLeft()
        )
        highlight_gradient.setColorAt(0, highlight_color)
        highlight_gradient.setColorAt(1, QColor(255, 255, 255, 0))

        painter.fillPath(highlight_path, QBrush(highlight_gradient))

        # Border
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        painter.end()

    def _is_dark_mode(self) -> bool:
        try:
            from ui.qt.qt_theme import current_appearance
            return current_appearance() == "dark"
        except Exception:
            return False


# =============================================================================
# Helper Functions
# =============================================================================


def apply_glass_effect(widget: Any, *, blur_radius: int = 24, opacity: float = 0.85) -> None:
    """Apply a frosted-glass effect (blur + translucency) to a widget."""
    try:
        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(blur_radius)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setOffset(0, 4)
        widget.setGraphicsEffect(shadow)
    except Exception:
        pass
    if opacity < 1.0:
        try:
            widget.setWindowOpacity(opacity)
        except Exception:
            pass


def apply_glass_card_effect(widget: Any, *, blur_radius: int = 20, shadow_opacity: float = 0.15) -> None:
    """Apply a subtle glass-card shadow effect (soft orange-tinted glow)."""
    try:
        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(blur_radius)
        shadow.setColor(QColor(255, 149, 0, int(255 * shadow_opacity)))
        shadow.setOffset(0, 2)
        widget.setGraphicsEffect(shadow)
    except Exception:
        pass


class Card:
    """A rounded iOS card widget (QFrame with objectName Card)."""

    def __new__(cls, scroll, theme: QtTheme) -> Any:
        frame = GlassCard(scroll)
        return frame


def card(theme: QtTheme, parent: Any = None) -> Any:
    return GlassCard(parent)


def section_label(theme: QtTheme, text: str) -> Any:
    lbl = QLabel(text)
    lbl.setObjectName("SectionTitle")
    lbl.setContentsMargins(0, 0, 0, 0)
    return lbl


def title_label(theme: QtTheme, text: str) -> Any:
    lbl = QLabel(text)
    lbl.setObjectName("Title")
    return lbl


def subtitle_label(theme: QtTheme, text: str) -> Any:
    lbl = QLabel(text)
    lbl.setObjectName("Subtitle")
    return lbl


def secondary_label(theme: QtTheme, text: str, wrappable: bool = False) -> Any:
    lbl = QLabel(text)
    lbl.setObjectName("Secondary")
    if wrappable:
        lbl.setWordWrap(True)
    return lbl


def primary_button(theme: QtTheme, text: str, on_click: Optional[Callable[[], None]] = None, *, height: int = 38) -> Any:
    btn = QPushButton(text)
    btn.setObjectName("Primary")
    btn.setMinimumHeight(height)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click is not None:
        btn.clicked.connect(on_click)
    return btn


def ghost_button(theme: QtTheme, text: str, on_click: Optional[Callable[[], None]] = None, *, height: int = 38) -> Any:
    btn = QPushButton(text)
    btn.setObjectName("Ghost")
    btn.setMinimumHeight(height)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click is not None:
        btn.clicked.connect(on_click)
    return btn


def quiet_button(theme: QtTheme, text: str, on_click: Optional[Callable[[], None]] = None) -> Any:
    btn = QPushButton(text)
    btn.setObjectName("Quiet")
    btn.setFlat(True)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click is not None:
        btn.clicked.connect(on_click)
    return btn


def toggle(theme: QtTheme, text: str, value: bool = False, on_change: Optional[Callable[[bool], None]] = None) -> Any:
    """iOS 26 animated toggle switch with text label (label is separate from toggle)."""
    cb = IOSToggle(checked=value)
    if on_change is not None:
        cb.toggled.connect(on_change)
    return cb


def labeled_entry(theme: QtTheme, label: str, value: str = "", *, password: bool = False) -> Any:
    """Vertical group: small caption above an inset QLineEdit."""
    from PySide6.QtWidgets import QLineEdit

    col = _V(labels=[secondary_label(theme, label)])
    edit = QLineEdit(value)
    if password:
        edit.setEchoMode(QLineEdit.EchoMode.Password)
    edit.setMinimumHeight(36)
    col.addWidget(edit)
    return col, edit


def _V(labels=(), *widgets) -> Any:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    for lbl in labels:
        lay.addWidget(lbl)
    for wt in widgets:
        lay.addWidget(wt)
    return w


def vertical(parent: Any = None) -> Any:
    w = QWidget(parent)
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    return w, lay


def hrow(parent: Any = None) -> Any:
    w = QWidget(parent)
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    return w, lay


class SegmentedControl:
    """iOS-style segmented control (a row of connected checkable buttons)."""

    def __init__(self, theme: QtTheme, values, checked: str = "", on_change: Optional[Callable[[str], None]] = None) -> Any:
        self.theme = theme
        self.values = list(values)
        self.buttons = []
        self._on_change = on_change

        self.widget = QFrame()
        self.widget.setObjectName("Segmented")
        self._group = QButtonGroup(self.widget)
        self._group.setExclusive(True)

        lay = QHBoxLayout(self.widget)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(0)

        for i, v in enumerate(self.values):
            btn = QPushButton(v)
            btn.setCheckable(True)
            btn.setProperty("segIndex", i)
            if v == checked:
                btn.setChecked(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, vv=v: self._emit(vv))
            self.buttons.append(btn)
            lay.addWidget(btn, 1)
            self._group.addButton(btn, i)

    def _emit(self, value: str) -> None:
        if self._on_change is not None:
            self._on_change(value)

    def current(self) -> str:
        checked_idx = self._group.checkedId()
        if 0 <= checked_idx < len(self.values):
            return self.values[checked_idx]
        return ""

    def set_current(self, value: str) -> None:
        for v, btn in zip(self.values, self.buttons):
            if v == value:
                btn.setChecked(True)
                return

    def set_enabled(self, enabled: bool) -> None:
        for btn in self.buttons:
            btn.setEnabled(enabled)


# Import QButtonGroup at module level for SegmentedControl
from PySide6.QtWidgets import QButtonGroup