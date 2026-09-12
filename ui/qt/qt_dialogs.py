"""Qt dialog host and message-box helpers for SwiftProxy.

Replaces the CustomTkinter toplevel helpers used by the old UI, keeping the
same look (centered, resizable, fade+slide entrance) on top of PySide6.
Now with iOS 26 Liquid Glass appearance.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QRectF
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QDialog,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)


class QtDialog(QDialog):
    """Resizable, centered modal-less dialog with fade+slide entrance.

    Now features Liquid Glass styling: translucent warm-tinted surface,
    soft orange glow border, and frosted-glass appearance.
    
    Key improvements:
    - Resizable window (not fixed size)
    - Better glass effect with layered painting and enhanced refraction
    - Smoother animations
    """

    _CORNER_RADIUS: int = 20

    def __init__(
        self,
        *,
        title: str,
        width: int,
        height: int,
        theme: Any,
        topmost: bool = False,
        icon_path: Optional[str] = None,
        on_close: Optional[Callable[[], None]] = None,
        min_width: int = 400,
        min_height: int = 300,
    ) -> None:
        super().__init__()
        self._on_close = on_close
        self.setWindowTitle(title)
        
        # Set initial size but allow resizing
        self.resize(width, height)
        self.setMinimumSize(min_width, min_height)
        
        # Frameless with translucent background for glass effect
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        if icon_path:
            self.setWindowIcon(QIcon(icon_path))

        if topmost:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        # Liquid Glass: make the window translucent so the glass effect shows through
        self.setWindowOpacity(0.96)  # Slight translucency for glass feel

        self._drag_pos: Any = None
        self._resizing = False
        self._resize_edge = None

        # Center on the primary screen
        screen = self.screen() or None
        if screen is not None:
            geo = screen.availableGeometry()
            x = geo.x() + (geo.width() - width) // 2
            y = geo.y() + (geo.height() - height) // 2 - 14
            self.move(x, y)

        # Entrance animations
        self._anim_fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim_fade.setDuration(280)
        self._anim_fade.setStartValue(0.0)
        self._anim_fade.setEndValue(0.96)
        self._anim_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        start_rect = self.geometry()
        end_rect = start_rect
        start_rect.moveTop(start_rect.top() - 20)
        self._anim_slide = QPropertyAnimation(self, b"geometry", self)
        self._anim_slide.setDuration(280)
        self._anim_slide.setStartValue(start_rect)
        self._anim_slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_slide.setEndValue(end_rect)

    def start_entrance(self) -> None:
        self._anim_fade.start()
        self._anim_slide.start()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Determine if we're in dark or light mode
        is_dark = self._is_dark_mode()

        # --- Glass surface (translucent, warm-tinted) ---
        if is_dark:
            base_fill = QColor(28, 24, 20, 220)   # Dark warm brown, 86% opacity
            border_color = QColor(255, 149, 0, 60) # Orange glow border
            highlight = QColor(255, 232, 214, 15)  # Subtle inner highlight
        else:
            base_fill = QColor(255, 248, 240, 230) # Warm white glass, 90% opacity
            border_color = QColor(255, 149, 0, 45) # Orange glow border
            highlight = QColor(255, 255, 255, 70)  # Subtle inner highlight

        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, self._CORNER_RADIUS, self._CORNER_RADIUS)

        # Fill with translucent warm-tinted glass
        painter.fillPath(path, QBrush(base_fill))

        # --- Inner gradient overlay (top-to-bottom for depth) ---
        inner_gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        if is_dark:
            inner_gradient.setColorAt(0, QColor(255, 255, 255, 6))
            inner_gradient.setColorAt(0.4, QColor(255, 255, 255, 0))
            inner_gradient.setColorAt(1, QColor(0, 0, 0, 12))
        else:
            inner_gradient.setColorAt(0, QColor(255, 255, 255, 20))
            inner_gradient.setColorAt(0.4, QColor(255, 255, 255, 0))
            inner_gradient.setColorAt(1, QColor(255, 200, 150, 6))

        painter.fillPath(path, QBrush(inner_gradient))

        # --- Top-edge highlight (glass refraction effect) ---
        # This creates the signature "Liquid Glass" shine at the top
        highlight_path = QPainterPath()
        highlight_rect = rect.adjusted(2, 2, -2, -rect.height() * 0.75)
        highlight_path.addRoundedRect(highlight_rect, self._CORNER_RADIUS - 2, self._CORNER_RADIUS - 2)

        highlight_gradient = QLinearGradient(
            highlight_rect.topLeft(),
            highlight_rect.bottomLeft()
        )
        highlight_gradient.setColorAt(0, highlight)
        highlight_gradient.setColorAt(0.5, QColor(255, 255, 255, 0))

        painter.fillPath(highlight_path, QBrush(highlight_gradient))

        # --- Outer border (soft orange glow) ---
        painter.setPen(QPen(border_color, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        border_path = QPainterPath()
        border_path.addRoundedRect(rect, self._CORNER_RADIUS, self._CORNER_RADIUS)
        painter.drawPath(border_path)

        # --- Inner subtle border (for depth) ---
        inner_border_path = QPainterPath()
        inner_border_rect = rect.adjusted(1, 1, -1, -1)
        inner_border_path.addRoundedRect(inner_border_rect, self._CORNER_RADIUS - 1, self._CORNER_RADIUS - 1)
        painter.setPen(QPen(QColor(255, 255, 255, 12 if is_dark else 25), 0.5))
        painter.drawPath(inner_border_path)

        painter.end()

    def _is_dark_mode(self) -> bool:
        """Check if the current theme appearance is dark."""
        try:
            from ui.qt.qt_theme import current_appearance
            return current_appearance() == "dark"
        except Exception:
            return False

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            # Check if clicking on title bar area (top 40px)
            if pos.y() < 40:
                self._drag_pos = self.frameGeometry().topLeft() - event.globalPosition().toPoint()
                event.accept()
                return
            # Check for resize edges
            edge = self._get_resize_edge(pos)
            if edge:
                self._resizing = True
                self._resize_edge = edge
                self._drag_pos = event.globalPosition().toPoint()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if self._resizing and self._resize_edge:
                # Handle resizing
                delta = event.globalPosition().toPoint() - self._drag_pos
                geo = self.geometry()
                
                if "right" in self._resize_edge:
                    geo.setRight(geo.right() + delta.x())
                if "bottom" in self._resize_edge:
                    geo.setBottom(geo.bottom() + delta.y())
                if "left" in self._resize_edge:
                    geo.setLeft(geo.left() + delta.x())
                if "top" in self._resize_edge:
                    geo.setTop(geo.top() + delta.y())
                
                # Enforce minimum size
                if geo.width() >= self.minimumWidth() and geo.height() >= self.minimumHeight():
                    self.setGeometry(geo)
                
                self._drag_pos = event.globalPosition().toPoint()
            else:
                # Handle dragging
                self.move(event.globalPosition().toPoint() + self._drag_pos)
            event.accept()
            return
        
        # Update cursor for resize edges
        pos = event.position()
        edge = self._get_resize_edge(pos)
        if edge:
            if "left" in edge and "top" in edge:
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif "right" in edge and "bottom" in edge:
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif "right" in edge and "top" in edge:
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif "left" in edge and "bottom" in edge:
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif "left" in edge or "right" in edge:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif "top" in edge or "bottom" in edge:
                self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()
        
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        self._resizing = False
        self._resize_edge = None
        self.unsetCursor()
        super().mouseReleaseEvent(event)

    def _get_resize_edge(self, pos) -> Optional[str]:
        """Determine which edge/corner the position is near for resizing."""
        margin = 8
        edges = []
        
        if pos.x() < margin:
            edges.append("left")
        elif pos.x() > self.width() - margin:
            edges.append("right")
        
        if pos.y() < margin:
            edges.append("top")
        elif pos.y() > self.height() - margin:
            edges.append("bottom")
        
        return "".join(edges) if edges else None

    def closeEvent(self, event) -> None:
        if self._on_close is not None:
            try:
                self._on_close()
            except Exception:
                pass
        super().closeEvent(event)

    def content_frame(self, *, padx: int, pady: Optional[int] = None) -> "PaddedLayout":
        """Return a padded vertical layout installed as the dialog's layout."""
        if pady is None:
            pady = padx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(padx, pady, padx, pady)
        lay.setSpacing(12)
        return lay


PaddedLayout = Any


def show_qt_error(parent: Optional[QWidget], text: str, title: Optional[str] = None) -> None:
    from ui.i18n import t
    from ui.qt.qt_runtime import on_qt_blocking

    def _show() -> None:
        QMessageBox.critical(parent, title or t("app.error_title"), text)

    on_qt_blocking(_show)


def show_qt_info(parent: Optional[QWidget], text: str, title: Optional[str] = None) -> None:
    from ui.i18n import t
    from ui.qt.qt_runtime import on_qt_blocking

    def _show() -> None:
        QMessageBox.information(parent, title or t("app.name"), text)

    on_qt_blocking(_show)


def ask_qt_yes_no(parent: Optional[QWidget], text: str, title: Optional[str] = None) -> bool:
    from ui.i18n import t
    from ui.qt.qt_runtime import on_qt_blocking

    def _ask() -> bool:
        resp = QMessageBox.question(
            parent, title or t("app.name"), text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return resp == QMessageBox.StandardButton.Yes

    result = on_qt_blocking(_ask)
    return bool(result)