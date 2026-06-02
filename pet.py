from __future__ import annotations

import json
import sys
import textwrap
import traceback
from dataclasses import dataclass

import cv2
import requests
from PyQt5.QtCore import QEvent, QPoint, QRect, QSize, QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QIcon, QImage, QPainter, QPixmap
from PyQt5.QtWidgets import QAction, QApplication, QDialog, QLabel, QMenu, QMessageBox, QSystemTrayIcon

from character_runtime import (
    avatar_values_for_emotion,
    build_reply_messages,
    normalize_emotion,
    parse_reply_content,
    write_image_to_cache,
)
from character_workbench import API_BASE_URL, DESCRIPTION_MODEL, CharacterCreatorDialog, LocalCharacterGenerator
from Murasame import generate, utils

screen_worker = None
DEFAULT_CHARACTER_NAME = "丛雨"
DEFAULT_USER_NAME = "用户"
DEFAULT_FGIMAGE_TARGET = "ムラサメb"
DEFAULT_EXPRESSION_LAYERS = [1717, 1475, 1261]
GENERATED_AVATAR_SCALE = 5.0

DEFAULT_CHARACTER_OPTIONS = {
    "appearance_groups": {
        "发色": ["黑发", "棕发", "金发", "银白发", "粉发"],
        "瞳色": ["黑瞳", "棕瞳", "蓝瞳", "绿瞳", "紫瞳"],
        "发型": ["长直发", "短发", "中长发", "双马尾", "单马尾", "侧马尾", "波浪卷"],
        "服装": ["校服", "休闲私服", "针织衫", "衬衫短裙", "运动服", "连衣裙"],
        "整体风格": ["清纯", "可爱", "冷淡", "优雅", "活泼"],
    },
    "appearance_traits": [],
    "personality_traits": [
        "傲娇系",
        "三无冷淡系",
        "呆萌系",
        "元气少女系",
        "温柔治愈系",
        "毒舌系",
        "害羞内向系",
        "天然系",
        "认真优等生系",
        "慵懒系",
    ],
    "identity_traits": [
        "同班同学",
        "学妹",
        "学姐",
        "青梅竹马",
        "大小姐",
        "学生会成员",
        "社团同伴",
        "图书委员",
        "风纪委员",
        "偶像练习生",
        "便利店兼职",
        "咖啡店店员",
    ],
    "styles": ["anime_desktop_pet", "transparent_png", "live2d_like"],
    "defaults": {
        "appearance_traits": ["棕发", "蓝瞳", "中长发", "校服", "清纯"],
        "personality_traits": ["温柔治愈系", "认真优等生系"],
        "identity_traits": ["同班同学"],
        "style": "anime_desktop_pet",
    },
}

DEFAULT_CHARACTER_OPTIONS["appearance_traits"] = [
    trait
    for traits in DEFAULT_CHARACTER_OPTIONS["appearance_groups"].values()
    for trait in traits
]


def wrap_text(text: str, width: int = 12) -> str:
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=True, break_on_hyphens=False))


@dataclass
class PetResponse:
    text: str
    emotion: str | None = None
    session_id: str | None = None


@dataclass
class CharacterProfile:
    character_id: str | None = None
    name: str = DEFAULT_CHARACTER_NAME
    persona: str = ""
    greeting: str = "主人，你好呀！"
    display_image_url: str | None = None
    display_image_base64: str | None = None
    expression_layers: list[int] | None = None
    fgimage_target: str = DEFAULT_FGIMAGE_TARGET
    emotion_images: dict | None = None
    appearance_traits: list[str] | None = None
    personality_traits: list[str] | None = None
    identity_traits: list[str] | None = None
    style: str | None = None


class PetApiClient:
    def __init__(self) -> None:
        config = utils.get_config()
        client_config = config.get("client", {})
        character_config = config.get("character", {})
        self.session_id = client_config.get("session_id", "local-user")
        self.timeout = float(client_config.get("timeout_seconds", 120))
        self.character_id = character_config.get("character_id")
        self.user_name = character_config.get("user_name") or DEFAULT_USER_NAME
        self.character_profile = self._character_from_config(character_config)
        self.api_key: str | None = None
        self.history: list[dict[str, str]] = []

    def get_character_options(self) -> dict:
        return DEFAULT_CHARACTER_OPTIONS

    def respond(self, event: str, text: str, screenshot_base64: str | None = None) -> PetResponse:
        response = requests.post(
            f"{API_BASE_URL}/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self._get_api_key()}",
                "Content-Type": "application/json",
            },
            json={
                "model": DESCRIPTION_MODEL,
                "messages": build_reply_messages(
                    self.character_profile,
                    self.user_name,
                    self.history,
                    event,
                    text,
                    bool(screenshot_base64),
                ),
                "stream": False,
                "temperature": 0.85,
                "top_p": 1,
                "presence_penalty": 0,
                "frequency_penalty": 0,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        data = parse_reply_content(content)
        reply_text = data.get("text") or content.strip()
        emotion = normalize_emotion(data.get("emotion"))
        self._remember_turn(text or event, reply_text)
        return PetResponse(
            text=reply_text,
            emotion=emotion,
            session_id=self.session_id,
        )

    def download_image(self, image_url: str | None, image_base64: str | None, key: str) -> str | None:
        return write_image_to_cache(image_url, image_base64, key)

    def _get_api_key(self) -> str:
        if not self.api_key:
            self.api_key = LocalCharacterGenerator(timeout=int(self.timeout)).api_key
        return self.api_key

    def _remember_turn(self, user_text: str, reply_text: str) -> None:
        self.history.extend(
            [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": json.dumps({"text": reply_text}, ensure_ascii=False)},
            ]
        )
        self.history = self.history[-12:]

    def _character_from_config(self, data: dict) -> CharacterProfile:
        return CharacterProfile(
            character_id=data.get("character_id") or data.get("id") or self.character_id,
            name=data.get("name") or data.get("character_name") or DEFAULT_CHARACTER_NAME,
            persona=data.get("persona") or "",
            greeting=data.get("greeting") or "主人，你好呀！",
            display_image_url=data.get("display_image_url"),
            display_image_base64=data.get("display_image_base64"),
            expression_layers=data.get("expression_layers"),
            fgimage_target=data.get("fgimage_target") or DEFAULT_FGIMAGE_TARGET,
            emotion_images=data.get("emotion_images"),
            appearance_traits=data.get("appearance_traits"),
            personality_traits=data.get("personality_traits"),
            identity_traits=data.get("identity_traits"),
            style=data.get("style"),
        )

    def remember_character(self, profile: CharacterProfile, user_name: str) -> None:
        config = utils.get_config()
        character_config = config.setdefault("character", {})
        character_config["character_id"] = profile.character_id
        character_config["name"] = profile.name
        character_config["persona"] = profile.persona
        character_config["greeting"] = profile.greeting
        character_config["display_image_url"] = profile.display_image_url
        character_config["display_image_base64"] = profile.display_image_base64
        character_config["expression_layers"] = profile.expression_layers
        character_config["fgimage_target"] = profile.fgimage_target
        character_config["emotion_images"] = profile.emotion_images
        character_config["appearance_traits"] = profile.appearance_traits
        character_config["personality_traits"] = profile.personality_traits
        character_config["identity_traits"] = profile.identity_traits
        character_config["style"] = profile.style
        character_config["user_name"] = user_name or DEFAULT_USER_NAME
        utils.save_config(config)
        self.character_id = profile.character_id
        self.user_name = user_name or DEFAULT_USER_NAME
        self.character_profile = profile
        self.history.clear()


class DesktopPet(QLabel):
    DISPLAY_PRESETS = {
        "compact": {"visible_ratio": 0.35, "text_x_offset": 120, "text_y_offset": 15},
        "balanced": {"visible_ratio": 0.45, "text_x_offset": 140, "text_y_offset": 20},
        "standard": {"visible_ratio": 0.6, "text_x_offset": 150, "text_y_offset": 25},
        "full": {"visible_ratio": 1.0, "text_x_offset": 160, "text_y_offset": -100},
    }

    def __init__(self, api_client: PetApiClient, character: CharacterProfile) -> None:
        super().__init__()
        self.api_client = api_client
        self.character = character
        self.latest_response = character.greeting or "主人，你好呀！"
        self.input_mode = False
        self.input_buffer = ""
        self.preedit_text = ""
        self.display_text = ""
        self.full_text = ""
        self.typing_prefix = ""
        self._typing_index = 0
        self.offset: QPoint | None = None
        self.touch_head = False
        self.head_press_x: int | None = None
        self.llm_worker: ApiWorker | None = None

        config = utils.get_config()
        display_config = config.get("display", {})
        preset_name = display_config.get("preset", "balanced")
        if preset_name == "custom":
            preset = display_config.get("custom", {})
        else:
            preset = self.DISPLAY_PRESETS.get(preset_name, self.DISPLAY_PRESETS["balanced"])
        self.visible_ratio = float(preset.get("visible_ratio", 0.45))
        self.text_x_offset_default = int(preset.get("text_x_offset", 140))
        self.text_y_offset_default = int(preset.get("text_y_offset", 20))

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._setup_macos_window_level()

        self.text_font = QFont()
        self.text_font.setFamily("思源黑体 CN Bold")
        QFontDatabase.addApplicationFont("./思源黑体Bold.otf")
        self.text_font.setPointSize(self._scaled_value(24))
        self.text_x_offset = 0
        self.text_y_offset = 0

        self.typing_timer = QTimer()
        self.typing_timer.timeout.connect(self._typing_step)
        self.typing_interval = 40

        self.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.mousePressEvent = self.start_move
        self.mouseMoveEvent = self.on_move
        avatar_url, avatar_base64 = avatar_values_for_emotion(character, "happy")
        self._set_avatar(
            image_url=avatar_url,
            image_base64=avatar_base64,
            layers=character.expression_layers or DEFAULT_EXPRESSION_LAYERS,
            fgimage_target=character.fgimage_target,
        )

    def _setup_macos_window_level(self) -> None:
        if sys.platform != "darwin":
            return
        try:
            from AppKit import NSFloatingWindowLevel
            from objc import objc_object
            from ctypes import c_void_p

            def set_level() -> None:
                try:
                    view = objc_object(c_void_p=c_void_p(int(self.winId())))
                    window = view.window()
                    if window:
                        window.setLevel_(NSFloatingWindowLevel)
                except Exception as exc:
                    print(f"Failed to set macOS window level: {exc}")

            QTimer.singleShot(100, set_level)
        except Exception:
            pass

    def _scale_factor(self) -> float:
        app = QApplication.instance()
        if app and hasattr(app, "devicePixelRatio"):
            return float(app.devicePixelRatio())
        screen = app.primaryScreen() if app else None
        return float(screen.devicePixelRatio()) if screen else 1.0

    def _scaled_value(self, value: int) -> int:
        scale = self._scale_factor()
        return int(value / scale) if scale > 1.0 else value

    def event(self, event: QEvent) -> bool:
        global screen_worker
        if screen_worker is None:
            return super().event(event)
        if event.type() == QEvent.WindowActivate:
            screen_worker.should_capture = False
        elif event.type() == QEvent.WindowDeactivate:
            self.input_mode = False
            self.show_text(self.latest_response, typing=True)
            screen_worker.should_capture = True
        return super().event(event)

    def cvimg_to_qpixmap(self, cv_img) -> QPixmap:
        cv_img_bgra = cv2.cvtColor(cv_img, cv2.COLOR_RGBA2BGRA)
        height, width, _ = cv_img_bgra.shape
        qimg = QImage(cv_img_bgra.data, width, height, 4 * width, QImage.Format_RGBA8888)
        return QPixmap.fromImage(qimg)

    def _apply_pixmap(self, pixmap: QPixmap, scale_multiplier: float = 1.0) -> None:
        scale = self._scale_factor()
        divisor = int(scale * 2) if scale > 1.0 else 2
        target_width = max(1, int(pixmap.width() * scale_multiplier / divisor))
        target_height = max(1, int(pixmap.height() * scale_multiplier / divisor))
        pixmap = pixmap.scaled(
            target_width,
            target_height,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.setPixmap(pixmap)
        self.resize(pixmap.size())
        self.update()

    def _set_avatar(
        self,
        image_url: str | None = None,
        image_base64: str | None = None,
        layers: list[int] | None = None,
        fgimage_target: str = DEFAULT_FGIMAGE_TARGET,
    ) -> None:
        if image_url or image_base64:
            try:
                image_path = self.api_client.download_image(
                    image_url,
                    image_base64,
                    self.character.character_id or self.character.name,
                )
                if image_path:
                    pixmap = QPixmap(image_path)
                    if not pixmap.isNull():
                        self._apply_pixmap(pixmap, GENERATED_AVATAR_SCALE)
                        return
            except Exception as exc:
                print(f"Avatar image loading failed: {exc}")

        fallback_layers = layers or DEFAULT_EXPRESSION_LAYERS
        try:
            cv_img = generate.generate_fgimage(target=fgimage_target, embeddings_layers=fallback_layers)
            self._apply_pixmap(self.cvimg_to_qpixmap(cv_img))
        except Exception as exc:
            print(f"Local expression loading failed: {exc}")

    def set_character(self, character: CharacterProfile) -> None:
        self.character = character
        self.latest_response = character.greeting or self.latest_response
        avatar_url, avatar_base64 = avatar_values_for_emotion(character, "happy")
        self._set_avatar(
            image_url=avatar_url,
            image_base64=avatar_base64,
            layers=character.expression_layers or DEFAULT_EXPRESSION_LAYERS,
            fgimage_target=character.fgimage_target,
        )
        self.show_text(self.latest_response, typing=True)

    def start_move(self, event) -> None:
        if event.button() == Qt.LeftButton:
            visible_height = int(self.height() * self.visible_ratio)
            if event.y() < visible_height // 2:
                self.touch_head = True
                self.head_press_x = event.x()
                self.setCursor(Qt.OpenHandCursor)
            elif event.y() > int(visible_height * 0.7) or self._text_clicked(event.pos()):
                self.input_mode = True
                self.input_buffer = ""
                self.display_text = f"【 {self.api_client.user_name} 】\n  ..."
                self.update()
        if event.button() == Qt.MiddleButton:
            self.offset = event.pos()
            self.setCursor(Qt.SizeAllCursor)

    def _text_clicked(self, pos) -> bool:
        if not self.display_text:
            return False
        rect = self.rect().adjusted(
            self.text_x_offset,
            self.text_y_offset,
            self.text_x_offset,
            -self.rect().height() // 2 + self.text_y_offset,
        )
        return rect.adjusted(-20, -20, 20, 20).contains(pos)

    def on_move(self, event) -> None:
        if self.touch_head and self.head_press_x is not None and event.buttons() & Qt.LeftButton:
            if abs(event.x() - self.head_press_x) > 50:
                self.start_api_worker("head_touch", f"{self.api_client.user_name}摸了摸你的头")
                self.touch_head = False
                self.head_press_x = None
        if self.offset is not None and event.buttons() == Qt.MiddleButton:
            self.move(self.pos() + event.pos() - self.offset)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MiddleButton:
            self.offset = None
        if event.button() == Qt.LeftButton:
            self.touch_head = False
            self.head_press_x = None
        self.setCursor(Qt.ArrowCursor)

    def show_text(self, text: str, x_offset: int | None = None, y_offset: int | None = None, typing: bool = True) -> None:
        self.text_x_offset = self._scaled_value(x_offset if x_offset is not None else self.text_x_offset_default)
        self.text_y_offset = self._scaled_value(y_offset if y_offset is not None else self.text_y_offset_default)
        self.typing_prefix = f"【 {self.character.name} 】\n  "
        if typing:
            self.full_text = text
            self.display_text = self.typing_prefix
            self._typing_index = 0
            self.typing_timer.start(self.typing_interval)
        else:
            self.display_text = text
            self.typing_timer.stop()
            self.update()

    def _typing_step(self) -> None:
        if self._typing_index < len(self.full_text):
            self.display_text = self.typing_prefix + self.full_text[: self._typing_index + 1]
            self._typing_index += 1
            self.update()
        else:
            self.typing_timer.stop()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self.display_text:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setFont(self.text_font)
        rect = self.rect().adjusted(
            self.text_x_offset,
            self.text_y_offset,
            self.text_x_offset,
            -self.rect().height() // 2 + self.text_y_offset,
        )
        align_flag = Qt.AlignLeft | Qt.AlignBottom
        border_size = max(1, self._scaled_value(2))
        painter.setPen(QColor(44, 22, 28))
        for dx, dy in [
            (-border_size, 0),
            (border_size, 0),
            (0, -border_size),
            (0, border_size),
            (border_size, -border_size),
            (border_size, border_size),
            (-border_size, -border_size),
            (-border_size, border_size),
        ]:
            painter.drawText(rect.translated(dx, dy), align_flag, self.display_text)
        painter.setPen(Qt.white)
        painter.drawText(rect, align_flag, self.display_text)
        painter.end()

    def inputMethodQuery(self, query):
        if query == Qt.ImMicroFocus:
            rect = self.rect().adjusted(
                self.text_x_offset,
                self.text_y_offset,
                self.text_x_offset,
                -self.rect().height() // 2 + self.text_y_offset,
            )
            return QRect(self.mapToGlobal(rect.bottomLeft()), QSize(1, 30))
        return super().inputMethodQuery(query)

    def inputMethodEvent(self, event) -> None:
        if not self.input_mode:
            super().inputMethodEvent(event)
            return
        if event.commitString():
            self.input_buffer += event.commitString()
        self.preedit_text = event.preeditString()
        self.display_text = f"【 {self.api_client.user_name} 】\n  「{wrap_text(self.input_buffer + self.preedit_text)}」"
        self.update()

    def keyPressEvent(self, event) -> None:
        if not self.input_mode:
            super().keyPressEvent(event)
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            text = self.input_buffer.strip()
            self.input_mode = False
            if text:
                self.start_api_worker("user_text", text)
            return
        if event.key() == Qt.Key_Backspace and not self.preedit_text:
            self.input_buffer = self.input_buffer[:-1]
        elif event.text() and not self.preedit_text:
            self.input_buffer += event.text()
        wrapped = wrap_text(self.input_buffer)
        if not wrapped.strip():
            self.display_text = f"【 {self.api_client.user_name} 】\n  ..."
        else:
            self.display_text = f"【 {self.api_client.user_name} 】\n  「{wrapped}」"
        self.update()

    def start_api_worker(self, event: str, text: str, screenshot_base64: str | None = None) -> None:
        self.llm_worker = ApiWorker(self.api_client, event, text, screenshot_base64)
        self.llm_worker.finished.connect(self.on_api_result)
        self.llm_worker.start()

    def on_api_result(self, result: PetResponse | None, error: str | None) -> None:
        if error or result is None:
            self.show_text(f"【 系统错误 】\n  {error or 'unknown error'}", typing=False)
            return
        if result.session_id:
            self.api_client.session_id = result.session_id
        self.latest_response = f"「{wrap_text(result.text)}」"
        self.show_text(self.latest_response, typing=True)
        self.input_buffer = ""
        self.preedit_text = ""
        emotion_image_url, emotion_image_base64 = avatar_values_for_emotion(self.character, result.emotion)
        if emotion_image_url or emotion_image_base64:
            self._set_avatar(
                image_url=emotion_image_url,
                image_base64=emotion_image_base64,
                layers=self.character.expression_layers,
                fgimage_target=self.character.fgimage_target,
            )


class ScreenWorker(QThread):
    screen_result = pyqtSignal(str)

    def __init__(self, api_client: PetApiClient, parent=None) -> None:
        super().__init__(parent)
        self.api_client = api_client
        self.running = True
        self.should_capture = False

    def run(self) -> None:
        while self.running:
            if self.should_capture:
                self.screen_result.emit("")
            self.sleep(30)

    def stop(self) -> None:
        self.running = False


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


def clear_history(parent, api_client: PetApiClient) -> None:
    api_client.session_id = utils.get_config().get("client", {}).get("session_id", "local-user")
    api_client.history.clear()
    parent.latest_response = "记忆已经清空了。"
    parent.show_text(parent.latest_response, typing=True)


def load_initial_character(api_client: PetApiClient) -> CharacterProfile:
    if api_client.character_profile.character_id or api_client.character_profile.persona:
        return api_client.character_profile
    return CharacterProfile(expression_layers=DEFAULT_EXPRESSION_LAYERS)


def get_character_options(api_client: PetApiClient) -> dict:
    try:
        return api_client.get_character_options()
    except Exception as exc:
        print(f"Failed to load character options: {exc}")
        return DEFAULT_CHARACTER_OPTIONS


def open_character_settings(parent: DesktopPet, api_client: PetApiClient) -> None:
    dialog = CharacterCreatorDialog(
        get_character_options(api_client),
        api_client,
        DEFAULT_CHARACTER_OPTIONS,
        DEFAULT_USER_NAME,
        parent,
    )
    if dialog.exec_() != QDialog.Accepted:
        return
    if dialog.preview_profile is None:
        return
    api_client.remember_character(dialog.preview_profile, dialog.preview_user_name)
    parent.set_character(dialog.preview_profile)


def regenerate_character_image(parent: DesktopPet, api_client: PetApiClient) -> None:
    profile = api_client.character_profile
    if not (profile.appearance_traits and profile.personality_traits and profile.identity_traits and profile.style):
        QMessageBox.information(parent, "缺少角色设定", "请先在角色设置中生成并应用角色。")
        return
    try:
        regenerated = LocalCharacterGenerator(timeout=int(api_client.timeout)).generate(
            user_name=api_client.user_name,
            appearance_traits=profile.appearance_traits,
            personality_traits=profile.personality_traits,
            identity_traits=profile.identity_traits,
            style=profile.style,
        )
        api_client.remember_character(regenerated, api_client.user_name)
        parent.set_character(regenerated)
    except Exception as exc:
        traceback.print_exc()
        QMessageBox.warning(parent, "重新生成人设图失败", f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    api_client = PetApiClient()
    desktop_pet = DesktopPet(api_client, load_initial_character(api_client))

    screen = app.primaryScreen()
    screen_geometry = screen.availableGeometry()
    x = screen_geometry.width() - desktop_pet.width() - 20
    y = screen_geometry.height() - int(desktop_pet.height() * desktop_pet.visible_ratio)
    desktop_pet.move(x, y)
    desktop_pet.show()

    tray_icon = QSystemTrayIcon(QIcon("icon.png"), parent=app)
    tray_menu = QMenu()
    character_action = QAction("角色设置")
    character_action.triggered.connect(lambda: open_character_settings(desktop_pet, api_client))
    regenerate_image_action = QAction("重新生成人设图")
    regenerate_image_action.triggered.connect(lambda: regenerate_character_image(desktop_pet, api_client))
    clear_action = QAction("清空记忆")
    clear_action.triggered.connect(lambda: clear_history(desktop_pet, api_client))
    exit_action = QAction("退出")
    exit_action.triggered.connect(app.quit)
    tray_menu.addAction(character_action)
    tray_menu.addAction(regenerate_image_action)
    tray_menu.addAction(clear_action)
    tray_menu.addAction(exit_action)
    tray_icon.setContextMenu(tray_menu)
    tray_icon.show()

    desktop_pet.show_text(desktop_pet.latest_response, typing=True)
    if not api_client.character_profile.character_id and utils.get_config().get("character", {}).get("auto_open_creator", True):
        QTimer.singleShot(500, lambda: open_character_settings(desktop_pet, api_client))

    screen_worker = ScreenWorker(api_client)
    if utils.get_config().get("enable_vl", True):
        screen_worker.screen_result.connect(
            lambda screenshot: desktop_pet.start_api_worker("screen_context", "", screenshot)
        )
        screen_worker.start()

    sys.exit(app.exec_())
