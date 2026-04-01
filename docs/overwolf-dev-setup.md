# Overwolf 开发联调步骤

## 目标

把 `overwolf-game-bridge/` 这套骨架真正跑起来，并和当前 Python 主程序联调：

```text
Overwolf App
  -> 本地 HTTP bridge
  -> Python overwolf_bridge
  -> TFT plugin
```

## 前置条件

需要同时具备：

1. Overwolf 客户端
2. Overwolf 开发者白名单 / 开发权限
3. 当前 Python 项目环境
4. TFT 或支持的目标游戏

说明：

- 如果没有 Overwolf 开发权限，通常无法正常加载和运行未发布 app
- Python 项目这边不需要额外改架构，当前已经具备 bridge 接收端

## 当前仓库相关位置

- Overwolf 设计文档：
  - `docs/overwolf-game-bridge-design.md`
- Python bridge：
  - `src/overwolf_bridge/`
- TFT Python 侧接入：
  - `src/game_plugins/tft/`
- Overwolf app 骨架：
  - `overwolf-game-bridge/`

## 第一步：准备 Python 侧

确保 `config.yaml` 至少具备：

```yaml
overwolf:
  enabled: true
  host: 127.0.0.1
  port: 7799
  stale_after_seconds: 5

plugin_settings:
  tft:
    data_source: overwolf
```

然后启动主程序：

```powershell
python main.py
```

这一步的目的不是先拿到真实 Overwolf 数据，而是先让本地 bridge 服务启动。

## 第二步：先验证 Python bridge 本身

在没有真实 Overwolf app 的情况下，可以先用模拟脚本验证：

```powershell
python scripts/simulate_overwolf_tft.py
```

如果一切正常，Python 侧应该能识别到：

- `matched plugin Teamfight Tactics (tft)`
- `TFT state:overwolf ...`

如果这里不通，先不要进入 Overwolf app 侧开发。

## 第三步：准备 Overwolf app 工程

当前骨架目录：

```text
overwolf-game-bridge/
```

建议下一步补齐：

1. 构建工具
   - `webpack` / `vite` / 其他你熟悉的 TS 打包方案
2. `dist/` 输出
3. 真正可被 Overwolf 加载的 html/js 产物

当前仓库里的 `package.json` 和 `tsconfig.json` 还是最小占位版本，需要你后续接上实际工具链。

## 第四步：确认 Overwolf runtime 能起来

目标：

- `manifest.json` 能被 Overwolf 正确识别
- `background` 窗口能启动
- `desktop` 窗口能打开
- 后台日志能看到：
  - app 初始化
  - game info 更新
  - `setRequiredFeatures(...)`

当前关键文件：

- `overwolf-game-bridge/manifest.json`
- `overwolf-game-bridge/src/background/index.ts`
- `overwolf-game-bridge/src/background/gep/runtime.ts`

## 第五步：接真实 GEP 数据

当前 `runtime.ts` 已经按真实方向写好了主流程：

1. `getRunningGameInfo`
2. `setRequiredFeatures`
3. `onInfoUpdates2`
4. `onNewEvents`

但你需要在真实环境下确认这些问题：

1. 当前游戏的 `classId` 是多少
2. `title` 是否稳定
3. `onInfoUpdates2` 的 payload 是否和样例一致
4. `onNewEvents` 的 payload 是否是：
   - 单事件
   - 还是 `{ events: [...] }`

如果和当前样例有偏差，就更新：

- `overwolf-game-bridge/src/background/gep/runtime.ts`
- `overwolf-game-bridge/src/background/gep/providers/tft.ts`

## 第六步：优先验证这些 TFT 字段

建议先验证最关键的一小组：

1. `gold`
2. `health`
3. `xp`
4. `rank`
5. `round_type`
6. `shop_pieces`
7. `board_pieces`
8. `bench_pieces`

也就是先把：

- `me`
- `match_info`
- `store`
- `board`
- `bench`

这五类跑通。

## 第七步：联调本地 Python bridge

Overwolf app 侧最终要把数据发到：

- `POST http://127.0.0.1:7799/snapshot`
- `POST http://127.0.0.1:7799/event`

当前发送客户端位置：

- `overwolf-game-bridge/src/background/bridge/client.ts`

当前统一协议定义：

- `overwolf-game-bridge/src/shared/protocol.ts`

要求是：

- 每次重要 `info update` 后都能生成一份可用 snapshot
- 每次关键 `new event` 也能同步发 event

## 第八步：再回到 Python 侧验收

当 Overwolf app 真正推送后，Python 侧应该出现：

- bridge 不再过期
- `tft` 插件持续命中
- `rules` 或 `ai` 能拿到 Overwolf 数据摘要

如果只出现短暂一次命中然后又 `not in game`，优先检查：

1. Overwolf app 是否持续推送
2. `stale_after_seconds`
3. `data_source` 是否设成 `overwolf` 或 `hybrid`

## 推荐联调顺序

1. Python bridge + 模拟脚本跑通
2. Overwolf app 能加载
3. `runtime.ts` 能收到真实回调
4. `tft.ts` 能正确映射字段
5. 本地 HTTP 推送成功
6. Python 插件持续命中

## 当前已知限制

1. 当前 `manifest.json` 还是骨架
2. 当前没有真实构建产物输出流程
3. `lol` provider 还是空实现
4. `tft` provider 虽然已经有字段映射，但还没用真实回调验证

## 建议下一步

最值得先做的不是继续扩功能，而是：

1. 选定构建方案
2. 让 Overwolf app 真正能加载
3. 打印真实 `onInfoUpdates2 / onNewEvents` payload

一旦拿到真实 payload，后面的映射会快很多。
