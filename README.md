# LOL Coach — AI 英雄联盟实时教练

实时截取游戏画面，发送给 AI 大模型分析，语音播报对局建议。后台托盘运行，不影响游戏体验。

## 功能

- **多 AI 提供商**：支持 Claude、OpenAI GPT-4o、Gemini，可随时切换
- **多 TTS 后端**：Windows 系统语音（免费）、Edge TTS 微软云端（免费，中文效果好）、OpenAI TTS（付费，质量最高）
- **灵活触发**：定时自动截图 + 全局热键手动触发，均可配置
- **游戏内悬浮窗**：半透明字幕叠加，自动淡出，可拖动位置
- **系统托盘**：后台静默运行，绿色/黄色/灰色图标显示运行状态
- **对局历史**：SQLite 本地存储，按场次分组，支持导出文本
- **热重载配置**：修改 `config.yaml` 无需重启立即生效

## 环境要求

- Windows 10 / 11
- Python 3.10+

## 安装

```bash
git clone git@github.com:PenNameLuXun/lol-coach.git
cd lol-coach
pip install -r requirements.txt
```

## 配置

首次运行会自动从模板生成 `config.yaml`，也可以手动复制：

```bash
copy config.example.yaml config.yaml
```

打开 `config.yaml`，**只需填写你要使用的 AI 提供商的 API Key**，其余留空即可：

```yaml
ai:
  provider: gemini        # 选择：claude | openai | gemini

  claude:
    api_key: "sk-ant-..."         # 使用 Claude 时填写

  openai:
    api_key: "sk-..."             # 使用 OpenAI 时填写

  gemini:
    api_key: "AIzaSy..."          # 使用 Gemini 时填写

capture:
  interval: 30            # 建议 30 秒，避免 API 限流
```

### API Key 申请

| 提供商 | 搜索关键词 |
|--------|-----------|
| Claude | `Anthropic Console API key` |
| OpenAI | `OpenAI Platform API key` |
| Gemini | `Google AI Studio API key`（有免费额度） |

> TTS 默认使用 `edge`（微软 Edge TTS），**无需任何 Key，开箱即用**。

## 运行

```bash
python main.py
```

启动后程序最小化到系统托盘：

- **双击托盘图标** — 打开主窗口
- **右键托盘图标** — 开始/暂停分析、打开窗口、退出
- **Ctrl+C**（终端）— 退出程序

## 截图触发方式

| 方式 | 配置项 | 说明 |
|------|--------|------|
| 定时 | `capture.interval` | 每 N 秒自动截图，0 表示禁用 |
| 热键 | `capture.hotkey` | 默认 `ctrl+shift+a`，空字符串表示禁用 |

## 项目结构

```
lol-coach/
├── main.py                  # 入口，线程调度与 UI 集成
├── config.yaml              # 运行时配置（不提交到 git）
├── config.example.yaml      # 配置模板
├── requirements.txt
└── src/
    ├── config.py            # 配置管理，支持热重载
    ├── event_bus.py         # 线程间通信队列
    ├── history.py           # SQLite 历史记录
    ├── ai_provider.py       # AI 多提供商抽象（Claude/OpenAI/Gemini）
    ├── capturer.py          # 截图模块
    ├── tts_engine.py        # TTS 多后端抽象
    └── ui/
        ├── overlay.py       # 游戏内悬浮字幕窗口
        ├── tray.py          # 系统托盘图标
        ├── main_window.py   # 主窗口（4 个 Tab）
        └── tabs/
            ├── config_tab.py
            ├── log_tab.py
            └── history_tab.py
```

## 注意事项

- `config.yaml` 包含 API Key，已加入 `.gitignore`，不会被提交
- 全局热键功能在 Windows 上可能需要以管理员权限运行
- Gemini 免费套餐有每日请求次数限制，建议将 `capture.interval` 设置为 30 秒以上
- 遇到 429 限流错误时程序会自动等待后重试

## 未来计划

- 视频片段分析（替代截图帧）
- LOL 客户端 API 集成（获取实时对局数据）
- 迁移到 Electron + TypeScript 跨平台版本
