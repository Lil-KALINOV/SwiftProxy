from __future__ import annotations

import math
import sys
import tkinter
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple, Union

_tk_variable_del_guard_installed = False


def install_tkinter_variable_del_guard() -> None:
    global _tk_variable_del_guard_installed
    if _tk_variable_del_guard_installed:
        return
    _orig = tkinter.Variable.__del__

    def _safe_variable_del(self: Any, _orig: Any = _orig) -> None:
        try:
            _orig(self)
        except (RuntimeError, tkinter.TclError):
            pass

    tkinter.Variable.__del__ = _safe_variable_del  # type: ignore[assignment]
    _tk_variable_del_guard_installed = True


CONFIG_DIALOG_SIZE: Tuple[int, int] = (460, 560)
CONFIG_DIALOG_FRAME_PAD: Tuple[int, int] = (20, 14)
FIRST_RUN_SIZE: Tuple[int, int] = (520, 480)
FIRST_RUN_FRAME_PAD: Tuple[int, int] = (28, 24)


@dataclass(frozen=True)
class CtkTheme:
    # SwiftProxy brand accent (matches icon gradient: #ff6a00 -> #ffac1c).
    accent: tuple = ("#ff7b00", "#ff7b00")
    accent_hover: tuple = ("#e56c00", "#e56c00")
    accent_soft: tuple = ("#ff9a3d", "#ff9a3d")

    # iOS-style system palettes: systemGroupedBackground, card fills and dividers.
    bg: tuple = ("#f2f2f7", "#000000")  # systemGroupedBackground
    field_bg: tuple = ("#ffffff", "#1c1c1e")  # card / inset group fill
    field_border: tuple = ("#e5e5ea", "#2c2c2e")  # separator hairline
    field_inset: tuple = ("#e9e9ee", "#2c2c2e")  # inset input track inside cards

    text_primary: tuple = ("#000000", "#ffffff")
    text_secondary: tuple = ("#6d6d72", "#98989f")

    # iOS-style switch / toggle green.
    switch_on: tuple = ("#34c759", "#30d158")
    switch_off: tuple = ("#e5e5ea", "#3a3a3c")
    switch_thumb: tuple = ("#ffffff", "#ffffff")

    # iOS-style tray menu accents.
    menu_active: tuple = ("#0a84ff", "#0a84ff")  # systemBlue
    menu_hover: tuple = ("#e5f2ff", "#1b3a5c")
    danger: tuple = ("#d70015", "#ff453a")

    corner_radius: int = 12
    inner_radius: int = 8

    ui_font_family: str = "Sans"
    mono_font_family: str = "Monospace"


def ctk_theme_for_platform() -> CtkTheme:
    if sys.platform == "win32":
        return CtkTheme(ui_font_family="Segoe UI", mono_font_family="Consolas")
    return CtkTheme()


_APPEARANCE_MODE_MAP = {"auto": "system", "light": "Light", "dark": "Dark"}


def apply_ctk_appearance(ctk: Any, mode: str = "auto") -> None:
    ctk.set_appearance_mode(_APPEARANCE_MODE_MAP.get(mode, "system"))
    ctk.set_default_color_theme("blue")


def _color_for(theme: CtkTheme, attr: str, appearance: str) -> str:
    """Pick the tuple's per-appearance color (light/dark/system fallback)."""
    value = getattr(theme, attr)
    if not isinstance(value, tuple):
        return str(value)
    if appearance == "dark":
        return value[1] if len(value) > 1 else value[0]
    return value[0]


def _appearance_now(ctk: Any) -> str:
    try:
        mode = str(ctk.get_appearance_mode())
        return "dark" if mode.lower().startswith("dark") else "light"
    except Exception:
        return "light"


def theme_css_colors(theme: CtkTheme, appearance: str) -> dict:
    """Helper mapping used by widgets that need explicit light/dark colors."""
    return {
        "bg": _color_for(theme, "bg", appearance),
        "field_bg": _color_for(theme, "field_bg", appearance),
        "field_border": _color_for(theme, "field_border", appearance),
        "text_primary": _color_for(theme, "text_primary", appearance),
        "text_secondary": _color_for(theme, "text_secondary", appearance),
        "switch_on": _color_for(theme, "switch_on", appearance),
        "switch_off": _color_for(theme, "switch_off", appearance),
    }


def ease_out_cubic(t: float) -> float:
    """Ease-out cubic curve (1 - (1-t)^3)."""
    return 1.0 - (1.0 - t) ** 3


def ease_out_back(t: float) -> float:
    """Ease-out with a slight overshoot (iOS-style bounce for reveal animation)."""
    c1 = 1.70158
    c3 = c1 + 1.0
    return 1.0 + c3 * (t - 1.0) ** 3 + c1 * (t - 1.0) ** 2


def fade_in_window(root: Any, step_ms: int = 12, steps: int = 14) -> None:
    """Animate window opacity from 0 to 1 (fast, low-resource fade-in)."""
    try:
        root.attributes("-alpha", 0.0)
    except Exception:
        return
    n = [0]

    def _tick():
        n[0] += 1
        t = n[0] / steps
        try:
            root.attributes("-alpha", min(1.0, ease_out_cubic(max(0.0, t))))
        except Exception:
            return
        if n[0] < steps:
            root.after(step_ms, _tick)

    root.after(step_ms, _tick)


def slide_in_window(
    root: Any,
    *,
    start_dy: int = 24,
    step_ms: int = 12,
    steps: int = 14,
    fade: bool = True,
) -> None:
    """iOS-style modal: window slides up from below while fading in."""
    geom = {}
    try:
        g = root.geometry()
        x, y = g.rsplit("+", 2)[1:] if "+" in g else ("0", "0")
        start_y = int(y) + start_dy
        root.geometry(f"+{x}+{start_y}")
        if fade:
            root.attributes("-alpha", 0.0)
    except Exception:
        return
    n = [0]

    def _tick():
        n[0] += 1
        tt = n[0] / steps
        ease = ease_out_cubic(tt)
        try:
            y = int(start_y) - int(start_dy * ease)
            root.geometry(f"+{x}+{y}")
            if fade:
                root.attributes("-alpha", min(1.0, ease))
        except Exception:
            return
        if n[0] < steps:
            root.after(step_ms, _tick)

    root.after(step_ms, _tick)


def animate_widget_reveal(
    root: Any,
    widget: Any,
    *,
    stagger_ms: int = 60,
    fade: bool = False,
) -> None:
    """Subtle iOS reveal: fade from low alpha (window-level) as widgets mount.

    tkinter can only alpha the whole window, so per-widget we animate a small
    vertical slide using geometry is not possible for children; instead we do
    a lightweight opacity ramp on the toplevel plus gentle stagger timing on
    when widgets are realized. This is kept minimal/cheap.
    """
    try:
        root.after(stagger_ms, lambda: fade_in_window(root, fade=fade))
    except Exception:
        pass


def ease_scroll_to(scrollable: Any, target_unit: int, *, duration_ms: int = 220) -> None:
    """Smoothly scroll a CTkScrollableFrame to a fractional target (0..1) using ease-out."""
    canvas = getattr(scrollable, "_parent_canvas", None)
    if canvas is None:
        return
    try:
        start = canvas.yview()[0]
    except Exception:
        return
    start_s = [start]
    anim = [None]

    def _tick(frame_i):
        t = frame_i / 18
        if t >= 1.0:
            try:
                canvas.yview_moveto(target_unit)
            except Exception:
                pass
            anim[0] = None
            return
        eased = ease_out_cubic(t)
        try:
            canvas.yview_moveto(start_s[0] + (target_unit - start_s[0]) * eased)
        except Exception:
            return
        try:
            anim[0] = scrollable.after(12, lambda: _tick(frame_i + 1))
        except Exception:
            pass

    anim[0] = scrollable.after(0, lambda: _tick(0))


class SmoothScrollMixin:
    """Attach buttery mouse-wheel scrolling to a CTkScrollableFrame.

    Binds wheel events on the canvas and all descendant widgets, and animates
    the yview with ease-out so scrolling feels iOS-smooth instead of jumpy.
    """

    def __init__(self, scrollable: Any, *, multiplier: float = 1.35) -> None:
        self.scrollable = scrollable
        self.canvas = getattr(scrollable, "_parent_canvas", None)
        self.multiplier = multiplier
        self._velocity = {"delta": 0.0, "active": False, "after": None}
        if self.canvas is not None:
            self._bind_wheel(self.canvas)
            self._bind_descendants(scrollable)
            self._bind_frame_children_later()

    def _bind_wheel(self, widget: Any) -> None:
        widget.bind("<MouseWheel>", self._on_wheel, add="+")
        widget.bind("<Button-4>", self._on_wheel_up, add="+")
        widget.bind("<Button-5>", self._on_wheel_down, add="+")

    def _bind_descendants(self, widget: Any) -> None:
        try:
            for child in widget.winfo_children():
                try:
                    if child is not self.canvas:
                        self._bind_wheel(child)
                except Exception:
                    pass
                self._bind_descendants(child)
        except Exception:
            pass

    def _bind_frame_children_later(self) -> None:
        for ms in (80, 300, 800):
            try:
                self.canvas.after(ms, self.rebind)
            except Exception:
                pass

    def rebind(self) -> None:
        if self.canvas is None:
            return
        try:
            self._bind_descendants(self.scrollable)
        except Exception:
            pass

    def _on_wheel(self, event: Any) -> None:
        delta = getattr(event, "delta", 120)
        self._scroll_units(-(delta / 120.0) * self.multiplier)
        return "break"

    def _on_wheel_up(self, _event: Any = None) -> None:
        self._scroll_units(-self.multiplier)
        return "break"

    def _on_wheel_down(self, _event: Any = None) -> None:
        self._scroll_units(self.multiplier)
        return "break"

    def _scroll_units(self, units: float) -> None:
        if self.canvas is None:
            return
        v = self._velocity
        v["delta"] += units * 14
        if not v["active"]:
            v["active"] = True
            try:
                v["after"] = self.canvas.after(10, self._animate)
            except Exception:
                v["active"] = False

    def _animate(self) -> None:
        v = self._velocity
        if not v["active"]:
            return
        delta = v["delta"]
        if abs(delta) < 0.5:
            v["delta"] = 0.0
            v["active"] = False
            v["after"] = None
            return
        try:
            self.canvas.yview_scroll(int(delta), "units")
        except Exception:
            v["active"] = False
            return
        v["delta"] *= 0.40
        try:
            v["after"] = self.canvas.after(14, self._animate)
        except Exception:
            v["active"] = False

    def detach(self) -> None:
        v = self._velocity
        if v["after"] is not None:
            try:
                self.canvas.after_cancel(v["after"])
            except Exception:
                pass
        v["active"] = False
        v["after"] = None


def attach_smooth_scroll(scrollable: Any, *, multiplier: float = 1.35) -> SmoothScrollMixin:
    """Attach iOS-style smooth scrolling to a CTkScrollableFrame."""
    return SmoothScrollMixin(scrollable, multiplier=multiplier)


def center_ctk_geometry(root: Any, width: int, height: int, *, dy: int = 0) -> None:
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = (sw - width) // 2
    y = (sh - height) // 2 + dy
    root.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")


def create_ctk_toplevel(
    ctk: Any,
    *,
    title: str,
    width: int,
    height: int,
    theme: CtkTheme,
    topmost: bool = True,
    after_create: Optional[Callable[[Any], None]] = None,
    fade_in: bool = True,
    slide_in: bool = True,
) -> Any:
    root = ctk.CTkToplevel()
    root.title(title)
    root.resizable(False, False)
    center_ctk_geometry(root, width, height, dy=-14)
    root.configure(fg_color=theme.bg)
    if topmost:
        root.attributes("-topmost", True)
    root.lift()
    root.focus_force()

    _anim_ids: list = []

    if fade_in or slide_in:
        if slide_in:
            _anim_ids.append(root.after(30, lambda: slide_in_window(root, fade=fade_in)))
        else:
            _anim_ids.append(root.after(30, lambda: fade_in_window(root)))

    if after_create:
        _after_id = root.after(300, lambda: after_create(root))
        _orig_destroy = root.destroy

        def _safe_destroy():
            for _id in _anim_ids + [_after_id]:
                try:
                    root.after_cancel(_id)
                except Exception:
                    pass
            _orig_destroy()

        root.destroy = _safe_destroy
    return root


def main_content_frame(
    ctk: Any,
    root: Any,
    theme: CtkTheme,
    *,
    padx: int,
    pady: int,
) -> Any:
    frame = ctk.CTkFrame(root, fg_color=theme.bg, corner_radius=0)
    frame.pack(fill="both", expand=True, padx=padx, pady=pady)
    return frame