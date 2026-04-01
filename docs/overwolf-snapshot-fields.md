# Overwolf Snapshot Fields

这份文档描述 `overwolf-game-bridge` 当前会向 Python 侧 `src/overwolf_bridge` 发送的字段。

目标是说明两件事：
- 当前代码已经稳定结构化输出了哪些字段
- 哪些字段目前仍属于“先接住原始数据，等真机校准后再细化”的阶段

相关源码：
- `overwolf-game-bridge/src/background/gep/providers/tft.ts`
- `overwolf-game-bridge/src/background/gep/providers/lol.ts`
- `overwolf-game-bridge/src/background/gep/feature-map.ts`

## Envelope

无论是 `snapshot` 还是 `event`，桥接层外层协议都是统一的：

```json
{
  "source": "overwolf",
  "game_id": "tft",
  "timestamp": "2026-04-01T12:34:56.789Z",
  "data": {}
}
```

`snapshot` 会发送到：
- `POST /snapshot`

`event` 会发送到：
- `POST /event`

## TFT Snapshot

TFT provider 当前订阅这些 Overwolf features：
- `me`
- `match_info`
- `roster`
- `store`
- `board`
- `bench`
- `carousel`
- `live_client_data`

当前输出的 snapshot `data` 字段如下。

### 基础局面字段

- `mode: "TFT"`
- `game_time: string`
- `game_time_seconds: number`
- `hp: number`
- `gold: number`
- `level: number`
- `xp: number`
- `rank: number`
- `alive_players: number`
- `round: string`
- `round_type: string`
- `battle_state: string`
- `match_state: string`
- `round_outcome: string`
- `event_signature: string`

说明：
- `round` 当前本质上与 `round_type` 一致
- `game_time*` 主要从 `live_client_data.game_data.gameTime` 推导
- `alive_players` 当前主要通过 `roster.player_status` 里 `health > 0` 的人数估算

### 玩家与对手

- `me`
  - `name: string`

- `opponent`
  - `name: string`
  - `tag_line: string`

### 商店 / 棋盘 / 备战区 / 选秀

- `shop: Array<{ slot: string; name: string }>`
- `board: Array<{ slot: string; name: string; level?: number; items?: string[] }>`
- `bench: Array<{ slot: string; name: string; level?: number; items?: string[] }>`
- `carousel: Array<{ slot: string; name: string; item?: string }>`

说明：
- 名称会做简单标准化，去掉 `TFT_` / `TFTxxxx_` 这类前缀
- 装备会做简单标准化，去掉 `TFT_Item_` 前缀
- `shop` 会过滤掉空名字和 `Sold`

### 其他玩家与局内附加信息

- `roster: Array<{ name: string; health?: number; xp?: number; rank?: number; localplayer?: boolean }>`
- `local_player_damage: Array<{ name: string; damage?: number; level?: number }>`
- `item_select: string[]`

### 原始块透传

- `live_client_data: Record<string, unknown>`

这个字段当前保留的是 `live_client_data` feature 下收到的原始子块，用于后续：
- 真机调试
- 补字段
- Python 侧二次解析

### 当前明确忽略的字段

- `augments`

原因：当前代码显式忽略它，避免误用到 Riot TOS 明确敏感的强化符文数据。

## TFT Events

当前会向 Python 侧转发这些事件：
- `round_start`
- `round_end`
- `battle_start`
- `battle_end`
- `match_start`
- `match_end`
- `picked_item`

当前 event `data` 结构是：

```json
{
  "value": "原始 event.data"
}
```

补充行为：
- 当事件名是 `round_start` 且 `event.data` 是字符串时，provider 会同步更新 snapshot 里的 `round_type` 和 `round`

## LoL Snapshot

LoL provider 当前订阅这些 Overwolf features：
- `live_client_data`
- `matchState`
- `match_info`
- `abilities`
- `gold`
- `minions`
- `summoner_info`
- `teams`
- `team_frames`
- `damage`
- `heal`
- `jungle_camps`
- `level`
- `gameMode`

当前输出的 snapshot `data` 字段如下。

### 基础局面字段

- `mode: "LOL"`
- `game_time: string`
- `game_time_seconds: number`
- `event_signature: string`

说明：
- `game_time*` 当前主要从 `live_client_data.game_data.gameTime` 推导

### 召唤师信息

- `summoner`
  - `name?: string`
  - `region?: string`
  - `champion?: string`
  - `id?: string`

来源主要是：
- `summoner_info`
- `live_client_data.active_player.summonerName` 作为兜底补充

### 对局信息

- `match`
  - `started?: boolean`
  - `match_id?: string`
  - `queue_id?: string`
  - `pseudo_match_id?: string`
  - `game_mode?: string`
  - `match_paused?: boolean`
  - `players_tagline?: Array<{ playerName?: string; tagline?: string }>`

来源主要是：
- `matchState`
- `match_info`

### 资源字段

- `gold: number`
- `level: number`
- `minions: number`
- `neutral_minions: number`

来源主要是：
- `gold.gold`
- `level.level`
- `minions.minionKills`
- `minions.neutralMinionKills`

### 技能与战斗相关原始块

- `abilities: Record<string, unknown>`
- `teams: Record<string, unknown>`
- `team_frames: Record<string, unknown>`
- `damage: Record<string, unknown>`
- `heal: Record<string, unknown>`
- `jungle_camps: Record<string, unknown>`
- `live_client_data: Record<string, unknown>`

说明：
- 这部分当前属于“先广接入，再逐步收 schema”的状态
- 也就是说，代码已经会接收并转发这些 feature，但很多字段还没有在 provider 中做最终精细化定义
- 当前最适合把它们视作“供 Python 侧实验和真机校准用的原始映射块”

### 当前结构化成熟度

相对来说：
- `summoner`
- `match`
- `gold`
- `level`
- `minions`
- `neutral_minions`
- `game_time*`

这些字段当前更接近稳定结构。

而下面这些还属于待真机收口阶段：
- `abilities`
- `teams`
- `team_frames`
- `damage`
- `heal`
- `jungle_camps`
- `live_client_data`

## LoL Events

当前会向 Python 侧转发这些事件：
- `matchStart`
- `levelUp`
- `goldUpdate`
- `kill`
- `assist`
- `death`
- `respawn`
- `minions`
- `jungle_camps`
- `damage`
- `heal`

当前 event `data` 结构是：
- 直接透传事件原始对象的浅层 record 结果

也就是说，LoL event 目前不像 TFT 那样再包一层 `{ value: ... }`，而是更偏原始地保留字段，以便后续根据真机 payload 继续细化。

## 当前限制

这份文档描述的是“当前 bridge 代码准备接和准备发的字段”，不代表：
- Overwolf 真机环境里所有字段都已经被实测确认
- 所有 feature 的实际 payload 形状都已稳定定稿

尤其 LoL 这边，很多 feature 目前属于：
- 已接入
- 已落桥
- 但仍需真机校准字段名和层级

## 推荐接入策略

如果 Python 侧要消费这些 snapshot，建议：

### TFT

优先信任这些字段：
- `hp`
- `gold`
- `level`
- `rank`
- `alive_players`
- `round_type`
- `battle_state`
- `shop`
- `board`
- `bench`
- `roster`

### LoL

优先信任这些字段：
- `summoner`
- `match`
- `gold`
- `level`
- `minions`
- `neutral_minions`
- `game_time_seconds`

而对这些字段建议先按“实验输入”使用：
- `abilities`
- `teams`
- `team_frames`
- `damage`
- `heal`
- `jungle_camps`
- `live_client_data`

## Related Files

- `docs/overwolf-game-bridge-design.md`
- `docs/overwolf-dev-setup.md`
- `overwolf-game-bridge/samples/`
