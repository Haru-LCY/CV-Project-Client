from __future__ import annotations

import traceback

from PyQt5.QtCore import QThread, pyqtSignal

from Murasame import utils
from scripts.desktop_tools import capture_desktop_data_uri
from scripts.pet_api import PetApiClient
from scripts.profile import PetResponse


class ScreenWorker(QThread):
    screen_result = pyqtSignal(str)

    def __init__(self, api_client: PetApiClient, parent=None) -> None:
        super().__init__(parent)
        self.api_client = api_client
        config = utils.get_config().get("vl", {})
        self.interval_seconds = max(5, int(config.get("interval_seconds", 30)))
        self.max_width = max(320, int(config.get("max_width", 1280)))
        self.jpeg_quality = max(35, min(95, int(config.get("jpeg_quality", 75))))
        self.running = True
        self.should_capture = False

    def run(self) -> None:
        while self.running:
            if self.should_capture:
                self.screen_result.emit(self._capture_desktop_data_uri())
            self.sleep(self.interval_seconds)

    def stop(self) -> None:
        self.running = False

    def _capture_desktop_data_uri(self) -> str:
        return capture_desktop_data_uri(self.max_width, self.jpeg_quality)


class ApiWorker(QThread):
    finished = pyqtSignal(object, object)

    def __init__(self, api_client: PetApiClient, event: str, text: str, screenshot_base64: str | None = None) -> None:
        super().__init__()
        self.api_client = api_client
        self.event = event
        self.text = text
        self.screenshot_base64 = screenshot_base64

    def run(self) -> None:
        try:
            result = self.api_client.respond(self.event, self.text, self.screenshot_base64)
            self.finished.emit(result, None)
        except Exception as exc:
            traceback.print_exc()
            self.finished.emit(None, f"{type(exc).__name__}: {exc}")


class ToolActionWorker(QThread):
    finished = pyqtSignal(object, object)

    def __init__(self, api_client: PetApiClient, action: dict, parent=None) -> None:
        super().__init__(parent)
        self.api_client = api_client
        self.action = action

    def run(self) -> None:
        try:
            result = self.api_client.confirm_tool_action(self.action)
            self.finished.emit(result, None)
        except Exception as exc:
            traceback.print_exc()
            self.finished.emit(None, f"{type(exc).__name__}: {exc}")
