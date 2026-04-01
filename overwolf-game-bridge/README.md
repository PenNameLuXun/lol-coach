# Overwolf Game Bridge

通用 Overwolf 侧桥接应用骨架。

目标：

- 从 Overwolf GEP 获取实时游戏数据
- 转换成 Python 主程序可消费的本地桥接协议
- 支持多个游戏 provider，而不是只服务 TFT

## 当前状态

当前已经具备：

- 通用目录结构
- bridge 协议类型定义
- `AppController`
- `BridgeClient`
- `GepDispatcher`
- `tft` / `lol` provider 骨架
- Overwolf runtime 接线草稿
- 可输出 `dist/` 的最小构建链

当前仍未完成：

- 真实 Overwolf 环境验证
- 最终 `manifest.json` 权限与字段确认
- `lol` provider 实现
- `tft` provider 基于真实回调 payload 的最终校准

## 本地构建

在 `overwolf-game-bridge/` 目录下：

```bash
npm install
npm run build
```

输出目录：

```text
dist/
  background/
    index.html
    index.js
  desktop/
    index.html
    index.js
    index.css
```

开发模式：

```bash
npm run dev
```

清理输出：

```bash
npm run clean
```

## 目录说明

- `src/background/`
  - 后台控制器、runtime、bridge client、provider dispatcher
- `src/desktop/`
  - 桌面调试窗口
- `src/shared/`
  - 通用类型和协议
- `samples/`
  - TFT 的样例 Overwolf payload

## 下一步

1. 在真实 Overwolf 开发环境中加载 app
2. 检查 `runtime.ts` 收到的真实回调
3. 根据真实 payload 微调 `tft` provider
4. 再决定是否启用第二个游戏 provider

设计文档见：

- `docs/overwolf-game-bridge-design.md`
- `docs/overwolf-dev-setup.md`
