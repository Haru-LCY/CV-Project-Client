# Moe Traits to Desktop Companions 使用说明书

Moe Traits to Desktop Companions 是一个 PyQt 桌面宠物客户端。它直接调用外部 OpenAI 兼容接口完成角色对话、角色生成、角色立绘后处理、桌面视觉观察、长期记忆和本地工具调用，不依赖本地服务端。

桌宠的核心体验是：在桌面上显示一个透明背景的二次元角色，用户可以直接和她说话、摸头、拖动位置、生成新角色，让她观察屏幕内容、记住对话和桌面活动，并在需要时调用本地工具完成搜索、整理桌面、识别图片、读取屏幕或拍照。

在线功能演示：[MurasamePet Demo Website](https://haru-lcy.github.io/CV-Project-Client/)

本地预览 Demo 网站：

```bash
python -m http.server 8000 --directory docs
```

## 1. 快速开始

需要 Python `>=3.10,<3.13`。推荐使用 `uv`：

```bash
uv sync
uv run python -m scripts.pet_app
```

Windows 下也可以直接使用项目虚拟环境：

```powershell
.\.venv\Scripts\python.exe -m scripts.pet_app
```

项目也注册了命令行入口：

```bash
uv run murasame-pet
```

## 2. API Key 配置

应用需要外部 API key。支持两种方式：

```bash
export API_KEY="your_api_key"
```

或在应用数据目录放置 `apikey.md`，文件内容直接写 API key。

开发模式下，如果项目根目录存在 `apikey.md`，首次读取时会复制到用户数据目录。打包发布时不会内置 `apikey.md`，发布版本需要用户自己通过环境变量或应用数据目录提供。

用户数据目录：

- macOS: `~/Library/Application Support/MurasamePet/`
- Windows: `%APPDATA%\MurasamePet\`
- Linux: `$XDG_DATA_HOME/MurasamePet/`，没有 `XDG_DATA_HOME` 时为 `~/.local/share/MurasamePet/`

可以用环境变量 `MURASAMEPET_DATA_DIR` 覆盖数据目录。

## 3. 首次启动流程

1. 启动 `scripts.pet_app`。
2. 应用读取或创建用户数据目录下的 `config.json`。
3. 如果当前没有已应用的角色卡，默认自动打开“角色生成工坊”。
4. 在工坊里选择外貌、性格、风格和自定义设定。
5. 点击“生成预览”，等待生成角色资料和四张情绪立绘。
6. 满意后点击“应用角色”，桌宠会切换到新角色并保存配置。
7. 可点击“保存角色卡”，以后从历史角色中重新加载。

## 4. 桌宠日常操作

桌宠窗口是无边框、透明背景、置顶显示的 PyQt 窗口。

- 左键拖动角色：移动桌宠位置，释放后保存窗口坐标。
- 鼠标滚轮配合 `Ctrl` 或 `Command`：缩放角色大小，缩放值会保存到配置。
- 左键点击下半部分：进入文字输入模式。
- 回车：开始输入；输入完成后再次回车发送。
- 输入法候选：窗口支持 IME 预编辑文本。
- 左键在上半部分横向拖动：触发摸头事件。
- 中键拖动：直接移动窗口。
- 角色设置按钮：打开角色生成工坊。
- 退出按钮：关闭应用。
- 文本显示：角色回复以打字机效果显示。

系统托盘菜单：

- `角色设置`: 打开角色生成工坊。
- `重新生成人设图`: 用当前角色设定重新生成角色立绘和情绪图。
- `清空本轮对话`: 清空短期上下文，不清空长期记忆。
- `清空长期记忆`: 清空当前用户的长期记忆。
- `退出`: 退出应用。

当工具需要确认时，桌宠会显示“同意 / 拒绝”：

- 鼠标点击选项可确认。
- 上下键切换选项。
- 回车确认当前选项。
- `Esc` 拒绝。

## 5. 角色生成工坊

角色生成工坊是一个 PyQtWebEngine + WebChannel 驱动的本地 HTML 工作台，入口在 `ui/character_workbench.html`，桥接逻辑在 `scripts/workbench/bridge.py`。

可以设置：

- 用户称呼：角色在对话中如何称呼你。
- 立绘风格：例如 `anime_desktop_pet`、`live2d_like`。
- 外貌设定：发色、瞳色、发型、服装、整体风格。
- 性格设定：傲娇系、三无冷淡系、呆萌系、元气少女系、温柔治愈系、毒舌系、害羞内向系、天然系、认真优等生系、慵懒系。
- 自定义设定：性格、外貌、世界观或其他补充设定。自定义设定优先级最高，会覆盖上方冲突选项。

点击“生成预览”后，生成器会完成两类任务：

1. 使用文本模型生成角色名、人设描述和初始问候语。
2. 使用图片模型生成 `happy`、`angry`、`shy`、`sad` 四种情绪立绘。

生成成功后可以：

- 在右侧预览四种情绪图。
- 查看角色资料卡、外貌摘要、性格组合、人设描述和问候语。
- 点击“保存角色卡”写入用户数据目录下的 `character_cards/*.json`。
- 点击“应用角色”写入当前 `config.json`，桌宠立即切换角色。
- 从“历史角色”下拉框加载已保存角色卡。

角色卡保存的主要内容包括：

- `character_id`
- `name`
- `persona`
- `greeting`
- `appearance_traits`
- `personality_traits`
- `identity_traits`
- `personality_dimensions`
- `appearance_style_dimensions`
- `advanced_settings`
- `custom_attributes`
- `style`
- `display_image_base64`
- `emotion_images`

## 6. CV 相关能力

本项目里和 CV 直接相关的能力有四类：角色立绘后处理、桌面截图观察、桌面图片识别、摄像头拍照分析。

### 6.1 角色立绘白底转透明底

角色生成时，图片提示词会要求模型输出“纯白色背景”的角色立绘。模型不直接生成透明底，而是先生成白底图，再由本地后处理把白底抠掉，变成适合桌宠窗口显示的透明 PNG。

实现位置：`scripts/workbench/image_processing.py`

处理流程：

1. 解码图片模型返回的 base64 图片。
2. 转成 `RGBA`。
3. 从图片四条边开始做 flood fill，只把和边缘相连的近白色区域识别为背景。
4. 白色背景判定条件是：RGB 三通道最小值不低于 `235`，且最大/最小通道差不超过 `42`。
5. 对背景 mask 做 `MaxFilter(3)` 扩张，再做 `GaussianBlur(1.0)` 柔化边缘。
6. 反相背景 mask，得到角色主体 alpha。
7. 把 alpha 写回原图，让角色保留、不属于角色的白底变透明。
8. 按 alpha 有效区域裁剪，并保留 `28px` padding。
9. 为角色加桌宠立牌效果：
   - 基于 alpha 扩张生成外轮廓。
   - 添加半透明阴影。
   - 添加白色外描边。
   - 添加浅粉色内描边。
   - 最后把角色主体叠回描边上。
10. 输出透明 PNG，再编码为 base64，写入角色档案。

这个流程的好处是桌宠窗口可以使用 `WA_TranslucentBackground` 透明显示，不会带白色方块背景；同时保留柔和描边和阴影，让角色在不同桌面壁纸上都能看清。

### 6.2 情绪立绘生成

生成器先生成一张 `happy` 源图，再以这张图作为参考生成其他情绪图：

- `happy`: 角色主图。
- `angry`: 生气/吐槽。
- `shy`: 害羞/被夸/心虚。
- `sad`: 难过/担心。

参考图生成时会要求保持服装、发型、发色、瞳色、配饰、画风和比例一致，只允许表情和轻微姿态变化。每张情绪图都会走同样的白底转透明底和立牌描边后处理。

对话模型返回 JSON：

```json
{
  "text": "回复文本",
  "emotion": "happy"
}
```

桌宠会根据 `emotion` 切换对应立绘。

### 6.3 桌面截图观察

启用 `enable_vl` 后，`ScreenWorker` 会按配置间隔读取屏幕，默认每 `30` 秒一次，最低 `5` 秒一次。

截图处理流程：

1. 使用 `PIL.ImageGrab.grab()` 截取桌面。
2. 转成 RGB。
3. 如果宽度超过 `vl.max_width`，按比例缩放。
4. 用 `vl.jpeg_quality` 压缩为 JPEG。
5. 编码成 `data:image/jpeg;base64,...`。
6. 交给 `read_screen` 工具，由多模态模型生成屏幕观察摘要。

`read_screen` 要求模型只描述截图中明确可见的内容，不转录大段文字，不输出密码、密钥、身份证号等敏感内容，不猜测截图外信息。

返回 JSON 形态：

```json
{
  "observation": "给角色看的简短可见内容摘要",
  "desktop_summary": "值得长期记住的一句话，没有则为空字符串"
}
```

`observation` 用于当前回复，`desktop_summary` 可写入长期记忆。

### 6.4 桌面图片识别与删除确认

当用户要求查找并删除桌面上的某类图片时，模型可以调用 `find_desktop_images_for_trash`。

工具流程：

1. 只枚举 `agent_tools.desktop_root` 下的直接图片文件。
2. 支持扩展名：`.png`、`.jpg`、`.jpeg`、`.webp`、`.gif`、`.bmp`、`.heic`。
3. 为候选图片生成缩略图 contact sheet，每张图标注编号。
4. 把缩略图表和文件元数据交给视觉模型。
5. 视觉模型返回符合描述的图片编号和置信度。
6. 只有置信度 `>= 0.65` 的匹配会进入待确认列表。
7. 工具不会直接删除，只返回 `trash_files` 待确认动作。
8. 用户在桌宠界面确认后，才会移动到废纸篓。

### 6.5 摄像头拍照分析

当用户要求“看看摄像头”“拍照”“自拍”或类似操作时，模型可以调用 `take_camera_shot`。

工具使用 OpenCV 打开默认摄像头，预热若干帧后保存一张照片到 `~/Pictures/shot.jpg`，再把照片交给多模态模型继续分析和回复。摄像头只会在模型明确调用工具时启动。

## 7. 对话与角色回复

对话请求由 `scripts/pet_api.py` 发起，角色提示词由 `scripts/character_runtime.py` 构造。

每次回复会组合以下信息：

- 当前角色卡：角色名、人设、问候语、外貌标签、性格标签、身份标签。
- 用户称呼。
- 最近短期上下文，最多保留最近 12 条消息。
- 长期记忆检索结果。
- 当前事件类型，例如 `user_text`、`head_touch`、`screen_context`。
- 用户输入或截图事件说明。

模型必须只输出 JSON，不输出 Markdown：

```json
{
  "text": "角色实际说的话",
  "emotion": "happy|angry|shy|sad",
  "desktop_summary": "可选，仅桌面观察时使用"
}
```

如果模型输出不是严格 JSON，客户端会尝试从文本中提取 JSON 对象；提取失败时，把原始内容当成回复文本。

## 8. 长期记忆实现

长期记忆由 `scripts/memory_runtime.py` 实现，默认开启。

### 8.1 记忆提供者

默认配置：

```json
{
  "memory": {
    "enabled": true,
    "provider": "mem0_local",
    "user_id": null,
    "top_k": 5,
    "store_screenshots": false,
    "desktop_summary_enabled": true,
    "storage_path": ".memory/local_memory.jsonl"
  }
}
```

`user_id` 为空时，会使用 `client.session_id`，默认是 `local-user`。

当 `provider` 是 `mem0_local` 时，应用会尝试创建 mem0 本地记忆：

- history DB 默认路径：`.memory/mem0_history.db`
- 向量库默认路径：`.memory/qdrant`
- 可通过 `memory.mem0.llm` 和 `memory.mem0.embedder` 传入 mem0 配置

如果 mem0 不可用、初始化失败、检索失败或写入失败，应用不会中断对话，会保留 JSONL 本地兜底记忆。

### 8.2 JSONL 本地兜底

兜底记忆写入 `memory.storage_path`，相对路径会解析到用户数据目录。

每条记录形态：

```json
{
  "user_id": "local-user",
  "kind": "conversation",
  "text": "用户：...\n角色：...",
  "metadata": {
    "event": "user_text",
    "session_id": "local-user",
    "user_id": "local-user"
  },
  "created_at": 1710000000
}
```

`kind` 主要有：

- `conversation`: 普通对话。
- `desktop`: 桌面观察摘要。

写入前会清洗文本：

- 去掉多余空白。
- 把 base64 图片 data URI 替换为 `[image omitted]`。

默认不会保存截图原图，`store_screenshots` 当前只作为配置项保留。

### 8.3 记忆写入时机

普通对话：

- 用户文本和角色回复会写入长期记忆。
- 格式为 `用户：...\n角色：...`。

摸头事件：

- 作为事件文本写入记忆。

桌面观察：

- 如果启用 `desktop_summary_enabled`，会写入桌面摘要。
- 格式为 `桌面观察：...\n角色回应：...`。
- 如果模型没有返回 `desktop_summary`，会用工具返回的观察摘要或角色回复做兜底。

工具确认：

- 用户确认删除后，会写入一次 `desktop_tool` 事件结果。

### 8.4 记忆检索与注入

每次回复前都会构造检索 query：

- 普通用户输入：使用清洗后的用户文本。
- 桌面观察：固定使用 `桌面观察 当前任务 应用 文档`。
- 其他事件：使用事件名。

本地 JSONL 检索逻辑：

1. 将 query 和记忆文本分词。
2. 中文文本会额外拆出单字和相邻二字词。
3. 用词频向量计算 cosine similarity。
4. 过滤当前 `user_id`。
5. 按相似度和创建时间排序。
6. 返回前 `memory.top_k` 条，默认 `5` 条。

检索到的记忆会写入系统提示中的“长期记忆参考”。提示词明确规定：长期记忆只作为参考；如果和角色卡冲突，必须以角色卡为准。

### 8.5 清空记忆

托盘菜单的“清空长期记忆”会清理当前用户：

- 如果 mem0 可用，优先尝试 `delete_all(user_id=...)`，失败后尝试 `reset()`。
- JSONL 兜底会重写文件，只保留其他用户的记录。

“清空本轮对话”只清空短期 `history`，不会删除长期记忆文件。

## 9. Native Tools

工具定义在 `scripts/pet_tools.py`。当 `agent_tools.enabled` 为 `true` 时，对话模型会收到 OpenAI 兼容的 `tools` schema。模型返回 `tool_calls` 后，客户端执行本地工具，再把工具结果继续回传给模型，最多连续 6 轮，避免无限循环。

当前工具：

- `open_google_search`: 用浏览器打开 Google 搜索结果页。
- `organize_desktop`: 整理桌面直接文件，移动到固定白名单分类文件夹。
- `find_desktop_images_for_trash`: 查找桌面上符合描述的图片，返回待确认的废纸篓计划。
- `read_screen`: 读取当前屏幕截图并生成观察摘要。
- `take_camera_shot`: 使用 OpenCV 从摄像头拍照，再交给多模态模型分析。

安全边界：

- 桌面工具只处理 `agent_tools.desktop_root` 下的直接文件。
- 不递归处理文件夹。
- 隐藏文件和系统文件会跳过。
- 整理目标文件夹必须来自固定白名单。
- 删除类操作不会直接执行，必须用户在桌宠界面确认。
- 确认删除时只允许移动仍位于桌面根目录下的直接文件。
- 摄像头只在工具明确调用时启动。

桌面整理白名单分类：

- `图片`
- `文档`
- `视频`
- `音频`
- `压缩包`
- `安装包`
- `代码`
- `数据表格`
- `快捷方式`
- `其他`

## 10. 配置说明

默认配置来自 `Murasame/utils.py` 的 `DEFAULT_CONFIG`。运行时会合并到用户数据目录的 `config.json`，相对路径会解析到用户数据目录。

关键字段：

- `enable_vl`: 是否启用定时桌面视觉观察。
- `client.session_id`: 当前会话/用户标识，默认 `local-user`。
- `client.timeout_seconds`: 外部 API 超时时间。
- `vl.model`: 多模态观察模型，默认 `qwen3-vl-flash`。
- `vl.interval_seconds`: 屏幕观察间隔，最低 5 秒，默认 30 秒。
- `vl.max_width`: 截图上传前最大宽度。
- `vl.jpeg_quality`: 截图 JPEG 质量，范围 35-95。
- `display.preset`: 显示预设，可选 `compact`、`balanced`、`standard`、`full`、`custom`。
- `display.custom.visible_ratio`: 自定义可见高度比例。
- `display.custom.text_x_offset`: 自定义文字横向偏移。
- `display.custom.text_y_offset`: 自定义文字纵向偏移。
- `display.avatar_scale`: 角色缩放值，运行时保存。
- `display.window_position`: 窗口位置，拖动后保存。
- `memory.enabled`: 是否启用长期记忆。
- `memory.provider`: 记忆提供者，默认 `mem0_local`。
- `memory.user_id`: 记忆用户 ID；为空时使用 `client.session_id`。
- `memory.top_k`: 每次回复检索的记忆条数。
- `memory.store_screenshots`: 是否保存截图原图；当前不保存，仅保留配置。
- `memory.desktop_summary_enabled`: 是否保存桌面观察摘要。
- `memory.storage_path`: 本地 JSONL 兜底记忆路径。
- `memory.mem0.history_db_path`: mem0 history DB 路径。
- `memory.mem0.vector_path`: mem0 本地向量库路径。
- `memory.mem0.llm`: 可选 mem0 LLM 配置。
- `memory.mem0.embedder`: 可选 mem0 embedder 配置。
- `agent_tools.enabled`: 是否启用本地工具。
- `agent_tools.desktop_root`: 桌面工具允许操作的根目录，默认 `~/Desktop`。
- `agent_tools.delete_requires_confirmation`: 删除类操作是否要求用户确认。
- `character.character_id`: 当前角色 ID。
- `character.name`: 当前角色名。
- `character.persona`: 当前角色人设。
- `character.greeting`: 当前初始问候语。
- `character.display_image_base64`: 当前主立绘。
- `character.expression_layers`: 本地兜底立绘图层。
- `character.fgimage_target`: 本地兜底立绘目标，可选 `ムラサメa`、`ムラサメb`。
- `character.emotion_images`: 四种情绪图。
- `character.appearance_traits`: 外貌标签。
- `character.personality_traits`: 性格标签。
- `character.identity_traits`: 身份标签。
- `character.style`: 立绘风格。
- `character.user_name`: 用户称呼。
- `character.auto_open_creator`: 没有角色卡时是否自动打开角色工坊。

## 11. API 模型

模型常量在 `scripts/workbench/constants.py`：

- `API_BASE_URL`: 外部 API 基址。
- `DESCRIPTION_MODEL`: 普通文本对话、整理计划和角色描述模型。
- `IMAGE_MODEL`: 角色图片生成模型。

普通对话使用 `DESCRIPTION_MODEL`。屏幕读取、桌面图片匹配和摄像头照片分析使用 `vl.model`。接口请求使用 OpenAI 兼容的 chat completions 格式，包括多模态 `image_url` 和 native `tools`。

角色图片生成使用 `generateContent` 风格接口，图片从响应里的 `inlineData` 或 `inline_data` 中提取。

## 12. 本地兜底立绘

如果当前角色没有生成图片，或生成图片加载失败，应用会使用 `Murasame/generate.py` 合成本地 `fgimages` 图层。

默认配置：

- `fgimage_target`: `ムラサメb`
- `expression_layers`: `[1717, 1475, 1261]`

图层元数据来自 `fgimages/ムラサメa.txt` 或 `fgimages/ムラサメb.txt`，编码为 `utf-16 le`。合成时使用 OpenCV 读取 PNG alpha，并按图层坐标叠加到透明画布上。

## 13. 打包

同步 build extra 后运行：

```bash
uv sync --extra build
uv run python -m scripts.build_executable
```

Windows 下可使用：

```powershell
.\.venv\Scripts\python.exe -m scripts.build_executable
```

常用参数：

```bash
python -m scripts.build_executable --onefile
python -m scripts.build_executable --console
python -m scripts.build_executable --dry-run
```

默认输出：

- Windows: `dist/MurasamePet/MurasamePet.exe`
- macOS: `dist/MurasamePet.app`

打包不会内置 `apikey.md`。发布版本需要用户通过环境变量或应用数据目录提供 API key。

## 14. 项目结构

- `scripts/pet_app.py`: 应用入口、窗口、托盘、屏幕 worker 启动。
- `scripts/pet_widget.py`: 桌宠窗口、输入、绘制、拖拽、缩放、工具确认交互。
- `scripts/pet_api.py`: API client、对话流程、工具循环、记忆写入。
- `scripts/pet_tools.py`: native tool schema 和本地工具执行。
- `scripts/desktop_tools.py`: 桌面文件、安全路径、截图、缩略图和浏览器搜索辅助函数。
- `scripts/memory_runtime.py`: 长期记忆、mem0 接入和 JSONL 兜底检索。
- `scripts/character_runtime.py`: 角色提示词、回复 JSON 解析、情绪图选择和图片缓存。
- `scripts/workbench/`: 角色生成工坊、角色卡、图片后处理、生成器和 WebChannel bridge。
- `ui/`: 角色生成工坊 HTML/CSS/JS。
- `Murasame/`: 本地图层合成立绘、配置路径和平台窗口辅助。
- `fgimages/`: 本地兜底角色图层资源。
- `logo/`: 项目 logo 资源。
