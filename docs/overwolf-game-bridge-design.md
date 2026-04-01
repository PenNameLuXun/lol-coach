# Overwolf Game Bridge Design

## Goal

构建一个运行在 Overwolf 平台中的通用桥接应用：

- 从 Overwolf GEP 获取多个游戏的实时数据
- 统一转换成项目内部协议
- 通过本地 HTTP 推送给 Python 侧 `src/overwolf_bridge`

这个桥接 app 不直接做教练建议，只负责采集、整理、转发和调试可视化。

## Why A Shared Bridge

不要为每个游戏单独写一个 Overwolf app。

理由：

- Python 主程序已经是插件化架构
- `overwolf_bridge` 在 Python 侧也是共享基础设施
- Overwolf 侧也应该保持同样的“共享桥 + 游戏 provider”模式

## High-Level Architecture

```text
Overwolf GEP
  -> provider dispatcher
  -> game provider
  -> game store
  -> bridge client
  -> http://127.0.0.1:7799/snapshot|event
  -> Python overwolf_bridge
  -> plugin source adapter
  -> plugin rules / AI
```

## Directory Layout

```text
overwolf-game-bridge/
  manifest.json
  package.json
  tsconfig.json
  README.md

  src/
    background/
      index.ts
      app-controller.ts
      bridge/
        client.ts
        queue.ts
      gep/
        dispatcher.ts
        registry.ts
        providers/
          base.ts
          tft.ts
          lol.ts
      state/
        game-store.ts
        connection-store.ts
    desktop/
      index.html
      index.ts
      index.css
    shared/
      protocol.ts
      types.ts
      game-ids.ts
      consts.ts
```

## Provider Interface

```ts
interface GameProvider {
  gameId: string;
  onInfoUpdate(payload: unknown, ctx: ProviderContext): ProviderOutput | null;
  onNewEvent(payload: unknown, ctx: ProviderContext): ProviderOutput | null;
}
```

## Phases

### Phase 1
- 文档
- 目录骨架
- 协议类型定义
- 基础 bridge client
- TFT provider stub

### Phase 2
- 真正接 Overwolf GEP
- 完成 `tft` 数据映射
- 接入桌面调试页

### Phase 3
- 增加第二个游戏 provider
- 加入更完整的队列 / 节流 / 重试

## Notes

- 当前仓库里的 Python bridge 已经可用
- 当前文档和骨架的目标是“锁定结构”，不是宣称 Overwolf 侧已经完成
- 后续如果要真正运行，需要完成 Overwolf 开发环境、manifest 权限和 GEP 接线
