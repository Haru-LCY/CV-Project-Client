from __future__ import annotations

import sys
from ctypes import c_void_p
from typing import Any


def apply_top_layer(widget: Any, level: str = "screensaver") -> bool:
    if sys.platform != "darwin":
        return False
    if not _is_cocoa_widget(widget):
        return False
    try:
        import AppKit
        import objc
    except Exception as exc:
        print(f"macOS top layer unavailable: {type(exc).__name__}: {exc}")
        return False

    try:
        view = objc.objc_object(c_void_p=c_void_p(int(widget.winId())))
        window = view.window()
        if window is None:
            return False

        window.setLevel_(_window_level(AppKit, level))
        window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
            | AppKit.NSWindowCollectionBehaviorStationary
            | AppKit.NSWindowCollectionBehaviorIgnoresCycle
        )
        window.setHidesOnDeactivate_(False)
        window.setCanHide_(False)
        return True
    except Exception as exc:
        print(f"Failed to apply macOS top layer: {type(exc).__name__}: {exc}")
        return False


def _window_level(appkit: Any, level: str) -> int:
    if level == "status":
        return int(appkit.NSStatusWindowLevel)
    if level == "floating":
        return int(appkit.NSFloatingWindowLevel)
    return int(appkit.NSScreenSaverWindowLevel)


def _is_cocoa_widget(widget: Any) -> bool:
    try:
        from PyQt5.QtWidgets import QApplication

        return QApplication.platformName().lower() == "cocoa"
    except Exception:
        return False
