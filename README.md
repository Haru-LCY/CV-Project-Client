# MurasamePet Client

这是一个 PyQt 桌宠客户端。项目不再调用本地 MurasamePet Server；角色生成和对话回复都由客户端直接调用外部 API。

## 功能

- PyQt 桌宠窗口、置顶、拖拽、托盘菜单。
- 文本输入、摸头事件和桌面上下文定时事件。
- HTML/CSS/JS 角色生成工作台，通过 PyQt WebEngine 承载。
- 直接调用 `deepseek-v4-flash` 生成人设描述和桌宠回复。
- 启用 `enable_vl` 时，低频截取桌面并调用 `qwen3-vl-flash` 生成桌面观察回复。
- 本地长期记忆/RAG：对文字对话和桌面观察摘要做检索，跨会话保留偏好、任务和上下文。
- 直接调用 `gemini-3.1-flash-image-preview` 生成角色立绘和情感图。
- 角色卡、人设图 base64 和用户称呼保存到 `config.json`。
- 没有生成图时，使用 `fgimages` 本地图层合成立绘兜底。

项目不再包含或依赖：

- 本地 MurasamePet Server。
- FastAPI 服务。
- GPT-SoVITS 或服务端音频接口。
- 本地服务端角色和对话接口。

## 运行

准备 API key，二选一：

```bash
export API_KEY="your_api_key"
```

或在用户数据目录创建 `apikey.md`，写入 API key。

安装依赖并启动：

```bash
uv sync
uv run python -m scripts.pet_app
```

Windows 下也可以直接使用本地 uv 环境运行：

```powershell
.\.venv\Scripts\python.exe -m scripts.pet_app
```

首次运行会在 macOS 的 `~/Library/Application Support/MurasamePet/` 下创建或复制运行配置。打包后的 `.app` 也从这个目录读取用户数据：

- `config.json`
- `apikey.md`
- `.memory/`
- `character_cards/`

如果使用 `.app` 且不想设置环境变量，请创建 `~/Library/Application Support/MurasamePet/apikey.md`，写入 API key。开发模式下如果项目根目录还保留旧的 `apikey.md`，第一次运行会自动拷贝到这个位置。

首次没有角色卡时，客户端会打开角色生成工作台。选择外貌、性格、身份、画风和称呼后点击“生成预览”，确认后点击“应用角色”，角色卡会保存到 `config.json`，后续对话会按该角色卡的语气回复。

## 打包

使用 `scripts.build_executable` 生成当前平台的可执行文件。Windows 会生成 `.exe`，macOS 会生成 `.app`：

```bash
uv sync --extra build
uv run python -m scripts.build_executable
```

Windows 下如果已经同步了 `build` extra，也可以直接使用本地 uv 环境运行：

```powershell
.\.venv\Scripts\python.exe -m scripts.build_executable
```

默认输出位置：

- macOS: `dist/MurasamePet.app`
- Windows: `dist/MurasamePet/MurasamePet.exe`

可选参数：

```bash
python -m scripts.build_executable --onefile
python -m scripts.build_executable --console
python -m scripts.build_executable --dry-run
```

打包不会内置 `apikey.md`。如需让打包后的应用调用外部 API，请使用环境变量 `API_KEY`，或把 `apikey.md` 放到应用数据目录：

- macOS: `~/Library/Application Support/MurasamePet/apikey.md`
- Windows: `%APPDATA%\MurasamePet\apikey.md`

如果启用桌面视觉观察，macOS 可能会在首次运行时请求屏幕录制权限。

## 配置

`config.json` 示例：

```json
{
    "enable_vl": true,
    "client": {
        "session_id": "local-user",
        "timeout_seconds": 120
    },
    "vl": {
        "model": "qwen3-vl-flash",
        "interval_seconds": 30,
        "max_width": 1280,
        "jpeg_quality": 75
    },
    "display": {
        "preset": "balanced"
    },
    "memory": {
        "enabled": true,
        "provider": "mem0_local",
        "user_id": null,
        "top_k": 5,
        "store_screenshots": false,
        "desktop_summary_enabled": true,
        "storage_path": ".memory/local_memory.jsonl",
        "mem0": {
            "history_db_path": ".memory/mem0_history.db",
            "vector_path": ".memory/qdrant",
            "llm": null,
            "embedder": null
        }
    },
    "character": {
        "character_id": null,
        "name": "丛雨",
        "persona": "",
        "greeting": "主人，你好呀！",
        "display_image_base64": null,
        "emotion_images": null,
        "appearance_traits": null,
        "personality_traits": null,
        "identity_traits": null,
        "personality_dimensions": null,
        "appearance_style_dimensions": null,
        "trait_dimensions": null,
        "style": null,
        "user_name": "用户",
        "auto_open_creator": true
    }
}
```

字段说明：

- `enable_vl`: 是否启用桌面视觉观察。启用后会低频截取桌面并上传到视觉模型接口。
- `client.session_id`: 本地会话标识。
- `client.timeout_seconds`: 外部 API 请求超时时间。
- `vl.model`: 桌面视觉观察使用的模型，默认 `qwen3-vl-flash`。
- `vl.interval_seconds`: 桌面观察间隔秒数，最低按 5 秒处理。
- `vl.max_width`: 截图上传前的最大宽度，超过会等比压缩。
- `vl.jpeg_quality`: 截图 JPEG 压缩质量，范围按 35-95 处理。
- `display.preset`: 桌宠显示预设，可选 `compact`、`balanced`、`standard`、`full`、`custom`。
- `memory.enabled`: 是否启用长期记忆/RAG。
- `memory.provider`: 记忆提供方，默认 `mem0_local`。安装并配置好 `mem0ai` 时会优先使用 Mem0，否则使用本地 JSONL 检索兜底。
- `memory.user_id`: 长期记忆用户标识。为空时使用 `client.session_id`。
- `memory.top_k`: 每次回复注入的长期记忆条数。
- `memory.store_screenshots`: 是否保存原始截图。默认 `false`，当前实现不会把截图 base64 写入长期记忆。
- `memory.desktop_summary_enabled`: 是否保存桌面观察摘要。
- `memory.storage_path`: 本地兜底记忆文件路径。
- `memory.mem0`: Mem0 本地路径和可选 LLM/embedding 配置；不填 `llm`/`embedder` 时使用 Mem0 默认配置，失败会自动退回 JSONL。
- `character.*`: 当前角色卡、图片、情感图和生成选项。
- `character.personality_dimensions`: 性格维度图，保存性格标签到 1-5 内部强弱值的映射；生成 prompt 会把它作为控制信息使用，不会要求模型写出数值。
- `character.appearance_style_dimensions`: 外貌中“整体风格”的维度图，保存风格标签到 1-5 内部倾向值的映射。
- `character.trait_dimensions`: 维度图的分组形式，当前包含 `personality` 和 `appearance_style`，用于角色卡兼容和后续扩展。
- `character.user_name`: 用户称呼，会显示在输入气泡中，也会传给回复 API。
- `character.auto_open_creator`: 没有角色卡时是否自动打开角色设置窗口。

## API 使用

角色生成和对话回复共用 `scripts/workbench/constants.py` 中的：

- `API_BASE_URL`
- `DESCRIPTION_MODEL`
- `IMAGE_MODEL`

普通对话会使用 `DESCRIPTION_MODEL`。桌面视觉观察会沿用同一个 `API_BASE_URL` 和 API key，使用 `vl.model`，并按 OpenAI 兼容多模态格式发送截图 `image_url`。

对话回复会把当前角色名、人设、问候语、用户称呼和最近对话历史放入提示词，并要求 API 返回：

```json
{
    "text": "回复文本",
    "emotion": "happy"
}
```

`emotion` 可为 `happy`、`angry`、`shy`、`sad`。桌面视觉回复可以额外返回 `desktop_summary`，用于长期记忆，不显示给用户。如果当前角色卡保存了对应情感图，桌宠会切换到对应图片。

长期记忆会在每次回复前检索相关内容并注入提示词，但角色卡优先级更高；如果记忆和角色设定冲突，以角色卡为准。托盘菜单中“清空本轮对话”只清最近上下文，“清空长期记忆”会清除当前用户的本地长期记忆。
