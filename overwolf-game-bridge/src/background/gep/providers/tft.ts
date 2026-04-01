import { GAME_IDS } from "../../../shared/game-ids";
import type { GameProvider, ProviderContext, ProviderOutput } from "../../../shared/types";

type Piece = {
  slot: string;
  name: string;
  level?: number;
  items?: string[];
};

type Opponent = {
  name?: string;
  tag_line?: string;
};

type TftSnapshotData = {
  mode: "TFT";
  game_time?: string;
  game_time_seconds?: number;
  hp?: number;
  gold?: number;
  level?: number;
  xp?: number;
  rank?: number;
  alive_players?: number;
  round?: string;
  round_type?: string;
  battle_state?: string;
  match_state?: string;
  round_outcome?: string;
  opponent?: Opponent;
  event_signature?: string;
  me: {
    name?: string;
  };
  shop: Array<{ slot: string; name: string }>;
  board: Piece[];
  bench: Piece[];
  carousel: Array<{ slot: string; name: string; item?: string }>;
  roster: Array<{ name: string; health?: number; xp?: number; rank?: number; localplayer?: boolean }>;
  local_player_damage: Array<{ name: string; damage?: number; level?: number }>;
  item_select: string[];
  live_client_data: Record<string, unknown>;
};

type MaybeRecord = Record<string, unknown>;

const TFT_EVENT_NAMES = new Set([
  "round_start",
  "round_end",
  "battle_start",
  "battle_end",
  "match_start",
  "match_end",
  "picked_item",
]);

export class TftProvider implements GameProvider {
  readonly gameId = GAME_IDS.TFT;
  private readonly snapshot: TftSnapshotData = {
    mode: "TFT",
    me: {},
    shop: [],
    board: [],
    bench: [],
    carousel: [],
    roster: [],
    local_player_damage: [],
    item_select: [],
    live_client_data: {},
  };

  onInfoUpdate(payload: unknown, ctx: ProviderContext): ProviderOutput | null {
    // Supports both direct {feature,key,value} updates and getInfo()-style {info:{...}, feature:"..."} payloads.
    const updates = this.extractInfoUpdates(payload);
    if (!updates.length) {
      return null;
    }

    for (const update of updates) {
      this.applyInfoUpdate(update.feature, update.category, update.key, update.value);
    }

    return {
      snapshot: {
        source: "overwolf",
        game_id: this.gameId,
        timestamp: ctx.nowIso,
        data: this.toBridgeData(),
      },
    };
  }

  onNewEvent(payload: unknown, ctx: ProviderContext): ProviderOutput | null {
    // Supports both direct {name,data} events and {events:[...]} envelopes.
    const events = this.extractEvents(payload);
    if (!events.length) {
      return null;
    }

    const bridgeEvents = events
      .filter((event) => TFT_EVENT_NAMES.has(event.name))
      .map((event) => {
        this.snapshot.event_signature = event.name;
        if (event.name === "round_start" && typeof event.data === "string") {
          this.snapshot.round_type = event.data;
          this.snapshot.round = event.data;
        }
        return {
          source: "overwolf" as const,
          game_id: this.gameId,
          event: event.name,
          timestamp: ctx.nowIso,
          data: {
            value: event.data,
          },
        };
      });

    if (!bridgeEvents.length) {
      return null;
    }

    return {
      snapshot: {
        source: "overwolf",
        game_id: this.gameId,
        timestamp: ctx.nowIso,
        data: this.toBridgeData(),
      },
      events: bridgeEvents,
    };
  }

  private toBridgeData(): Record<string, unknown> {
    return {
      mode: this.snapshot.mode,
      game_time: this.snapshot.game_time,
      game_time_seconds: this.snapshot.game_time_seconds,
      hp: this.snapshot.hp,
      gold: this.snapshot.gold,
      level: this.snapshot.level,
      xp: this.snapshot.xp,
      rank: this.snapshot.rank,
      alive_players: this.snapshot.alive_players,
      round: this.snapshot.round,
      round_type: this.snapshot.round_type,
      battle_state: this.snapshot.battle_state,
      match_state: this.snapshot.match_state,
      round_outcome: this.snapshot.round_outcome,
      opponent: this.snapshot.opponent,
      event_signature: this.snapshot.event_signature,
      me: this.snapshot.me,
      shop: this.snapshot.shop,
      board: this.snapshot.board,
      bench: this.snapshot.bench,
      carousel: this.snapshot.carousel,
      roster: this.snapshot.roster,
      local_player_damage: this.snapshot.local_player_damage,
      item_select: this.snapshot.item_select,
      live_client_data: this.snapshot.live_client_data,
    };
  }

  private applyInfoUpdate(feature: string, category: string, key: string, rawValue: unknown): void {
    const value = this.parseMaybeJson(rawValue);

    if (feature === "me") {
      if (key === "summoner_name") this.snapshot.me.name = this.stringOrUndefined(value);
      if (key === "gold") this.snapshot.gold = this.numberOrUndefined(value);
      if (key === "health") this.snapshot.hp = this.numberOrUndefined(value);
      if (key === "xp") this.snapshot.xp = this.numberOrUndefined(value);
      if (key === "rank") this.snapshot.rank = this.numberOrUndefined(value);
      return;
    }

    if (feature === "match_info") {
      if (key === "round_type") {
        this.snapshot.round_type = this.stringOrUndefined(value);
        this.snapshot.round = this.snapshot.round_type;
      }
      if (key === "battle_state") this.snapshot.battle_state = this.stringOrUndefined(value);
      if (key === "match_state") this.snapshot.match_state = this.stringOrUndefined(value);
      if (key === "round_outcome") this.snapshot.round_outcome = this.stringOrUndefined(value);
      if (key === "opponent") this.snapshot.opponent = this.parseOpponent(value);
      if (key === "game_mode") this.snapshot.mode = "TFT";
      if (key === "local_player_damage") this.snapshot.local_player_damage = this.parseDamageMap(value);
      if (key === "item_select") this.snapshot.item_select = this.parseItemSelect(value);
      return;
    }

    if (feature === "roster" && category === "roster" && key === "player_status") {
      this.snapshot.roster = this.parseRoster(value);
      const alive = this.snapshot.roster.filter((item) => (item.health ?? 0) > 0).length;
      if (alive > 0) this.snapshot.alive_players = alive;
      return;
    }

    if (feature === "store" && key === "shop_pieces") {
      this.snapshot.shop = this.parseShop(value);
      return;
    }

    if (feature === "board" && key === "board_pieces") {
      this.snapshot.board = this.parsePieces(value);
      return;
    }

    if (feature === "bench" && key === "bench_pieces") {
      this.snapshot.bench = this.parsePieces(value);
      return;
    }

    if (feature === "carousel" && key === "carousel_pieces") {
      this.snapshot.carousel = this.parseCarousel(value);
      return;
    }

    if (feature === "live_client_data") {
      this.snapshot.live_client_data[key] = value as unknown;
      if (key === "active_player") {
        const activePlayer = this.recordOrEmpty(value);
        this.snapshot.level = this.numberOrUndefined(activePlayer.level);
        this.snapshot.me.name = this.stringOrUndefined(activePlayer.summonerName) ?? this.snapshot.me.name;
      }
      if (key === "game_data") {
        const gameData = this.recordOrEmpty(value);
        const gameTime = this.numberOrUndefined(gameData.gameTime);
        if (gameTime !== undefined) {
          this.snapshot.game_time_seconds = gameTime;
          this.snapshot.game_time = `${Math.floor(gameTime / 60)}:${String(gameTime % 60).padStart(2, "0")}`;
        }
      }
      return;
    }

    if (feature === "augments") {
      // Intentionally ignored. Riot TOS disallows displaying augment data.
      return;
    }
  }

  private extractInfoUpdates(payload: unknown): Array<{ feature: string; category: string; key: string; value: unknown }> {
    const record = this.recordOrNull(payload);
    if (!record) return [];

    if (typeof record.feature === "string" && typeof record.key === "string") {
      return [{
        feature: record.feature,
        category: typeof record.category === "string" ? record.category : record.feature,
        key: record.key,
        value: record.value,
      }];
    }

    const info = this.recordOrNull(record.info);
    const feature = typeof record.feature === "string" ? record.feature : undefined;
    if (!info || !feature) return [];

    const featureData = this.recordOrNull(info[feature]);
    if (!featureData) return [];

    return Object.entries(featureData).map(([key, value]) => ({
      feature,
      category: feature,
      key,
      value,
    }));
  }

  private extractEvents(payload: unknown): Array<{ name: string; data: unknown }> {
    const record = this.recordOrNull(payload);
    if (!record) return [];

    if (typeof record.name === "string") {
      return [{ name: record.name, data: record.data }];
    }

    const events = Array.isArray(record.events) ? record.events : [];
    return events
      .map((item) => this.recordOrNull(item))
      .filter((item): item is MaybeRecord => Boolean(item) && typeof item.name === "string")
      .map((item) => ({ name: String(item.name), data: item.data }));
  }

  private parseMaybeJson(value: unknown): unknown {
    if (typeof value !== "string") return value;
    const trimmed = value.trim();
    if (!(trimmed.startsWith("{") || trimmed.startsWith("["))) {
      return value;
    }
    try {
      return JSON.parse(trimmed);
    } catch {
      return value;
    }
  }

  private parseShop(value: unknown): Array<{ slot: string; name: string }> {
    const record = this.recordOrEmpty(value);
    return Object.entries(record)
      .map(([slot, raw]) => ({ slot, name: this.normalizeName(this.recordOrEmpty(raw).name) }))
      .filter((item) => Boolean(item.name) && item.name !== "Sold");
  }

  private parsePieces(value: unknown): Piece[] {
    const record = this.recordOrEmpty(value);
    return Object.entries(record)
      .map(([slot, raw]) => {
        const piece = this.recordOrEmpty(raw);
        const items = [piece.item_1, piece.item_2, piece.item_3]
          .map((item) => this.normalizeItem(item))
          .filter((item): item is string => Boolean(item));
        return {
          slot,
          name: this.normalizeName(piece.name),
          level: this.numberOrUndefined(piece.level),
          items,
        } satisfies Piece;
      })
      .filter((item) => Boolean(item.name));
  }

  private parseCarousel(value: unknown): Array<{ slot: string; name: string; item?: string }> {
    const record = this.recordOrEmpty(value);
    return Object.entries(record)
      .map(([slot, raw]) => {
        const piece = this.recordOrEmpty(raw);
        const item = this.normalizeItem(piece.item_1);
        return {
          slot,
          name: this.normalizeName(piece.name),
          item: item || undefined,
        };
      })
      .filter((item) => Boolean(item.name));
  }

  private parseRoster(value: unknown): Array<{ name: string; health?: number; xp?: number; rank?: number; localplayer?: boolean }> {
    const record = this.recordOrEmpty(value);
    return Object.entries(record).map(([name, raw]) => {
      const item = this.recordOrEmpty(raw);
      return {
        name,
        health: this.numberOrUndefined(item.health),
        xp: this.numberOrUndefined(item.xp),
        rank: this.numberOrUndefined(item.rank),
        localplayer: Boolean(item.localplayer),
      };
    });
  }

  private parseDamageMap(value: unknown): Array<{ name: string; damage?: number; level?: number }> {
    const record = this.recordOrEmpty(value);
    return Object.values(record)
      .map((raw) => this.recordOrEmpty(raw))
      .map((item) => ({
        name: this.normalizeName(item.name),
        damage: this.numberOrUndefined(item.damage),
        level: this.numberOrUndefined(item.level),
      }))
      .filter((item) => Boolean(item.name));
  }

  private parseItemSelect(value: unknown): string[] {
    const record = this.recordOrEmpty(value);
    return Object.values(record)
      .map((raw) => this.recordOrEmpty(raw).name)
      .map((item) => this.normalizeItem(item))
      .filter((item): item is string => Boolean(item));
  }

  private parseOpponent(value: unknown): Opponent | undefined {
    const record = this.recordOrNull(value);
    if (!record) return undefined;
    return {
      name: this.stringOrUndefined(record.name),
      tag_line: this.stringOrUndefined(record.tag_line),
    };
  }

  private normalizeName(value: unknown): string {
    const name = this.stringOrUndefined(value) ?? "";
    return name.replace(/^TFT\d*_?/, "").replace(/^TFT_/, "").trim();
  }

  private normalizeItem(value: unknown): string | undefined {
    const item = this.stringOrUndefined(value);
    if (!item || item === "0") return undefined;
    return item.replace(/^TFT_Item_/, "").trim();
  }

  private recordOrNull(value: unknown): MaybeRecord | null {
    return value && typeof value === "object" && !Array.isArray(value) ? (value as MaybeRecord) : null;
  }

  private recordOrEmpty(value: unknown): MaybeRecord {
    return this.recordOrNull(value) ?? {};
  }

  private stringOrUndefined(value: unknown): string | undefined {
    return typeof value === "string" && value.trim() ? value.trim() : undefined;
  }

  private numberOrUndefined(value: unknown): number | undefined {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim()) {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : undefined;
    }
    return undefined;
  }
}
