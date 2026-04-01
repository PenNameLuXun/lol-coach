# Overwolf Bridge Protocol

这个项目内置了一个本地 `Overwolf bridge` 接收端，默认监听：

- `host`: `127.0.0.1`
- `port`: `7799`

当前支持两个端点：

- `POST /snapshot`
- `POST /event`
- `GET /health`

## 用途

`snapshot` 用来推送某个游戏的最新全量或准全量状态。  
`event` 用来推送离散事件，例如回合开始、选秀开始、商店刷新。

桥接层本身不理解 TFT / LoL 业务语义，只做：

- 按 `game_id` 缓存最新快照
- 按 `game_id` 记录最近事件
- 提供给具体插件的 source adapter 消费

## Snapshot Payload

请求：

```http
POST /snapshot
Content-Type: application/json
```

示例：

```json
{
  "source": "overwolf",
  "game_id": "tft",
  "timestamp": "2026-04-01T12:34:56.789Z",
  "data": {
    "mode": "TFT",
    "game_time": "18:20",
    "game_time_seconds": 1100,
    "hp": 72,
    "gold": 34,
    "level": 7,
    "alive_players": 5,
    "round": "4-2",
    "event_signature": "round_start",
    "me": {
      "name": "TestPlayer"
    },
    "shop": [
      {"name": "安妮", "cost": 2},
      {"name": "妮蔻", "cost": 3}
    ],
    "traits": [
      {"name": "法师", "tier_current": 3},
      {"name": "堡垒卫士", "tier_current": 2}
    ],
    "board": [],
    "bench": []
  }
}
```

要求：

- `game_id` 必填，例如 `tft`
- `data` 必须是对象
- `timestamp` 可选，不传时服务端会使用当前 UTC 时间

## Event Payload

请求：

```http
POST /event
Content-Type: application/json
```

示例：

```json
{
  "source": "overwolf",
  "game_id": "tft",
  "event": "round_start",
  "timestamp": "2026-04-01T12:35:01.000Z",
  "data": {
    "round": "4-2"
  }
}
```

要求：

- `game_id` 必填
- `event` 必填
- `data` 可为空对象

## Health Check

请求：

```http
GET /health
```

响应示例：

```json
{
  "ok": true,
  "connected_games": ["tft"]
}
```

## 当前集成状态

目前已经接入：

- `TFT`
  - `plugin_settings.tft.data_source = riot_live_client | overwolf | hybrid`

未来如果有其他插件想接 Overwolf，建议做法是：

1. 保持 `overwolf_bridge` 不带业务语义
2. 在对应插件目录下新增 `overwolf_source.py`
3. 由该 source 把通用快照转换成插件自己的 `raw_data`

## 本地模拟

仓库里提供了一个最小脚本：

```powershell
python scripts/simulate_overwolf_tft.py
```

它会向本地 bridge 推送一份 TFT 示例快照和一个事件，方便在没有真实 Overwolf app 的情况下联调 Python 主程序。
