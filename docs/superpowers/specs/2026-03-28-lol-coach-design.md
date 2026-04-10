# LOL Coach — AI英雄联盟教练软件设计文档

**日期：** 2026-03-28
**技术栈：** Python + PyQt6
**状态：** 已批准

---

## 1. 项目概述

一款运行在 Windows 桌面的英雄联盟 AI 教练软件。软件在后台捕获游戏画面，将截图发送给可配置的 AI 大模型，获取实时对局建议，并通过语音朗读给玩家。默认以系统托盘形式静默运行，支持打开主窗口进行配置和查看历史。

---

## 2. 整体架构

单进程 + 线程池模型，所有功能运行在同一个 PyQt6 进程内，通过线程安全队列（Queue）进行通信。

```
┌─────────────────────────────────────────────────────┐
│                    PyQt6 主进程                       │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │  主窗口   │  │  托盘图标 │  │    悬浮覆盖窗     │  │
│  │(配置/日志/│  │(右键菜单) │  │  (游戏内字幕)    │  │
│  │  历史)   │  └──────────┘  └──────────────────┘  │
│  └──────────┘                                       │
│       │                                             │
│  ┌────▼────────────────────────────────────────┐   │
│  │              事件总线 (Queue)                 │   │
│  └────┬──────────────┬──────────────┬──────────┘   │
│       │              │              │               │
│  ┌────▼────┐   ┌─────▼────┐  ┌─────▼────┐         │
│  │ 截图线程 │   │  AI线程   │  │ TTS线程  │         │
│  │mss/PIL  │   │多Provider │  │多Backend │         │
│  │定时+热键 │   │Claude/GPT │  │系统/云端  │         │
│  └─────────┘   │/Gemini等  │  └──────────┘         │
│                └──────────┘                         │
│                                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │           配置管理 (config.yaml)              │  │
│  └──────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

**数据流：**
1. 截图线程 → 截图帧入 `capture_queue` → AI线程消费
2. AI线程 → 建议文本入 `advice_queue` → TTS线程消费（语音播放）
3. 建议文本同时通过 Qt Signal 推送给：实时日志面板、悬浮窗、历史记录模块

---

## 3. 核心组件

### 3.1 截图模块 `src/capturer.py`

- 使用 `mss` 库截取全屏或指定 LOL 进程窗口区域
- 支持两种触发模式（可同时启用）：
  - **定时模式**：每 N 秒自动截图，N 可配置（默认 5 秒）
  - **热键模式**：全局快捷键触发单次截图（使用 `keyboard` 库）
- 截图后使用 Pillow 压缩为 JPEG（质量可配置），减少 API token 消耗
- 运行在独立守护线程中，通过 `capture_queue` 向 AI 线程传递图像数据

### 3.2 AI 模块 `src/ai_provider.py`

- 抽象基类 `BaseProvider`，统一接口：`analyze(image_bytes: bytes, prompt: str) -> str`
- 内置 Provider 实现：
  - `ClaudeProvider`（`anthropic` SDK，支持视觉模型如 claude-opus-4-6）
  - `OpenAIProvider`（`openai` SDK，支持 gpt-4o 等视觉模型）
  - `GeminiProvider`（`google-generativeai` SDK，支持 gemini-1.5-pro 等）
- 每个 Provider 可独立配置：`api_key`、`model`、`max_tokens`、`temperature`
- System prompt 可在配置文件中自定义，默认为：
  `"你是一个英雄联盟教练，根据当前游戏截图，用简短的中文（不超过50字）给出最重要的一条对局建议。"`
- AI 线程从 `capture_queue` 取图，调用 Provider，将结果写入 `advice_queue`

### 3.3 TTS 模块 `src/tts_engine.py`

- 抽象基类 `BaseTTS`，统一接口：`speak(text: str)`
- 内置 Backend 实现：
  - `WindowsTTS`：基于 `pyttsx3`，免费，无需网络
  - `EdgeTTS`：基于 `edge-tts`，微软云端免费，质量较好，中文支持优秀
  - `OpenAITTS`：基于 OpenAI TTS API，质量最高，需付费
- TTS 线程从 `advice_queue` 取文本，调用当前 Backend 播放语音
- 支持"打断模式"（可配置）：新建议到来时停止当前播放，立即朗读新内容

### 3.4 配置管理 `src/config.py`

- 统一读写 `config.yaml`，提供类型化访问接口
- 支持运行时热重载：监听文件变化，无需重启即可生效
- `config.example.yaml` 作为带注释的模板随代码一起分发

### 3.5 事件总线 `src/event_bus.py`

- 封装两条 `queue.Queue`：`capture_queue`（图像）、`advice_queue`（文本）
- 提供 PyQt6 Signal 桥接，将后台线程事件安全地传递给 UI

### 3.6 历史记录 `src/history.py`

- 使用 SQLite（标准库）存储每条建议：时间戳、建议文本、触发方式
- 支持手动标记场次（开始/结束），按场次分组查询
- 支持导出为纯文本文件

---

## 4. UI 组件

### 4.1 主窗口 `src/ui/main_window.py`

默认隐藏，托盘图标双击打开。包含四个 Tab：

| Tab | 内容 |
|-----|------|
| **配置** | AI Provider 选择、API Key、模型名、TTS Backend、触发模式（定时间隔秒数 / 热键绑定）、截图区域（全屏 / LOL窗口）、System Prompt |
| **实时日志** | 滚动文本框，显示 `[时间戳] 建议内容`，一键清空 |
| **对局历史** | 按场次分组列表，支持导出，可手动标记场次开始/结束 |
| **关于** | 版本号、快捷键说明、开源协议 |

### 4.2 系统托盘 `src/ui/tray.py`

- 右键菜单：开始分析 / 暂停分析、打开主窗口、退出
- 图标颜色状态：
  - 灰色：已暂停
  - 绿色：运行中
  - 黄色：AI 请求处理中

### 4.3 悬浮覆盖窗 `src/ui/overlay.py`

- 无边框、始终置顶（`Qt.WindowStaysOnTopHint`）、半透明黑色背景
- 显示最新建议文本，N 秒后自动淡出（N 可配置）
- 可拖动重新定位，位置持久化到 `config.yaml`
- 热键可切换显示/隐藏

---

## 5. 项目结构

```
lol-coach/
├── main.py                 # 入口：初始化 PyQt6 App、托盘、主窗口
├── config.yaml             # 用户配置（gitignore 中排除 API key）
├── config.example.yaml     # 配置模板（含注释说明）
├── requirements.txt
├── .gitignore
├── src/
│   ├── capturer.py
│   ├── ai_provider.py
│   ├── tts_engine.py
│   ├── config.py
│   ├── event_bus.py
│   ├── history.py
│   └── ui/
│       ├── main_window.py
│       ├── tray.py
│       ├── overlay.py
│       └── tabs/
│           ├── config_tab.py
│           ├── log_tab.py
│           └── history_tab.py
├── assets/
│   └── icon.png
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-03-28-lol-coach-design.md
```

---

## 6. 关键依赖

| 用途 | 库 | 备注 |
|------|----|------|
| UI框架 | `PyQt6` | |
| 截图 | `mss` | 高性能跨平台截图 |
| 图片处理 | `Pillow` | 压缩、格式转换 |
| 全局热键 | `keyboard` | 需管理员权限或特定权限 |
| AI - Claude | `anthropic` | |
| AI - OpenAI | `openai` | GPT + TTS 共用 |
| AI - Gemini | `google-generativeai` | |
| TTS - 系统 | `pyttsx3` | |
| TTS - Edge | `edge-tts` | 异步，需 asyncio 适配 |
| 配置 | `pyyaml` | |
| 历史存储 | `sqlite3` | Python 标准库 |

---

## 7. 安全注意事项

- `config.yaml` 包含 API Key，必须加入 `.gitignore`
- `config.example.yaml` 中所有 Key 字段填写占位符如 `"your-api-key-here"`
- API Key 在 UI 中以密码框形式显示（masked）

---

## 8. 未来扩展方向（超出本期范围）

- 视频片段分析（替代截图帧）
- 迁移到 Electron + TypeScript 实现跨平台
- LOL 客户端 API 集成（获取英雄、物品等结构化数据）
- 自定义 AI 角色扮演（不同风格的教练人格）
