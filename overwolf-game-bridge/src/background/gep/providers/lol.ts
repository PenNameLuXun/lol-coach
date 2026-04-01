import { GAME_IDS } from "../../../shared/game-ids";
import type { GameProvider, ProviderContext, ProviderOutput } from "../../../shared/types";

type MaybeRecord = Record<string, unknown>;

type LolSnapshotData = {
  mode: "LOL";
  game_time?: string;
  game_time_seconds?: number;
  summoner?: {
    name?: string;
    region?: string;
    champion?: string;
    id?: string;
  };
  match?: {
    started?: boolean;
    match_id?: string;
    queue_id?: string;
    pseudo_match_id?: string;
    game_mode?: string;
    match_paused?: boolean;
    players_tagline?: Array<{ playerName?: string; tagline?: string }>;
  };
  resources: {
    gold?: number;
    level?: number;
    minions?: number;
    neutral_minions?: number;
  };
  abilities: Record<string, unknown>;
  live_client_data: Record<string, unknown>;
  teams?: Record<string, unknown>;
  team_frames?: Record<string, unknown>;
  damage?: Record<string, unknown>;
  heal?: Record<string, unknown>;
  jungle_camps?: Record<string, unknown>;
  event_signature?: string;
};

const LOL_EVENT_NAMES = new Set([
  "matchStart",
  "levelUp",
  "goldUpdate",
  "kill",
  "assist",
  "death",
  "respawn",
  "minions",
  "jungle_camps",
  "damage",
  "heal",
]);

export class LolProvider implements GameProvider {
  readonly gameId = GAME_IDS.LOL;
  private readonly snapshot: LolSnapshotData = {
    mode: "LOL",
    resources: {},
    abilities: {},
    live_client_data: {},
  };

  onInfoUpdate(payload: unknown, ctx: ProviderContext): ProviderOutput | null {
    const updates = this.extractInfoUpdates(payload);
    if (!updates.length) {
      return null;
    }

    for (const update of updates) {
      this.applyInfoUpdate(update.feature, update.key, update.value);
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
    const events = this.extractEvents(payload);
    if (!events.length) {
      return null;
    }

    const bridgeEvents = events
      .filter((event) => LOL_EVENT_NAMES.has(event.name))
      .map((event) => {
        this.snapshot.event_signature = event.name;
        return {
          source: "overwolf" as const,
          game_id: this.gameId,
          event: event.name,
          timestamp: ctx.nowIso,
          data: this.recordOrEmpty(event.data),
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
      summoner: this.snapshot.summoner,
      match: this.snapshot.match,
      gold: this.snapshot.resources.gold,
      level: this.snapshot.resources.level,
      minions: this.snapshot.resources.minions,
      neutral_minions: this.snapshot.resources.neutral_minions,
      abilities: this.snapshot.abilities,
      teams: this.snapshot.teams,
      team_frames: this.snapshot.team_frames,
      damage: this.snapshot.damage,
      heal: this.snapshot.heal,
      jungle_camps: this.snapshot.jungle_camps,
      live_client_data: this.snapshot.live_client_data,
      event_signature: this.snapshot.event_signature,
    };
  }

  private applyInfoUpdate(feature: string, key: string, rawValue: unknown): void {
    const value = this.parseMaybeJson(rawValue);

    if (feature === "summoner_info") {
      const current = this.snapshot.summoner ?? {};
      if (key === "id") current.id = this.stringOrUndefined(value);
      if (key === "region") current.region = this.stringOrUndefined(value);
      if (key === "champion") current.champion = this.stringOrUndefined(value);
      if (key === "summoner_name") current.name = this.stringOrUndefined(value);
      this.snapshot.summoner = current;
      return;
    }

    if (feature === "matchState") {
      const current = this.snapshot.match ?? {};
      if (key === "matchStarted") current.started = this.boolOrUndefined(value);
      if (key === "matchId") current.match_id = this.stringOrUndefined(value);
      if (key === "queueId") current.queue_id = this.stringOrUndefined(value);
      this.snapshot.match = current;
      return;
    }

    if (feature === "match_info") {
      const current = this.snapshot.match ?? {};
      if (key === "pseudo_match_id") current.pseudo_match_id = this.stringOrUndefined(value);
      if (key === "game_mode") current.game_mode = this.stringOrUndefined(value);
      if (key === "match_paused") current.match_paused = this.boolOrUndefined(value);
      if (key === "players_tagline") current.players_tagline = this.parsePlayersTagline(value);
      this.snapshot.match = current;
      return;
    }

    if (feature === "gold" && key === "gold") {
      this.snapshot.resources.gold = this.numberOrUndefined(value);
      return;
    }

    if (feature === "level" && key === "level") {
      this.snapshot.resources.level = this.numberOrUndefined(value);
      return;
    }

    if (feature === "minions") {
      if (key === "minionKills") this.snapshot.resources.minions = this.numberOrUndefined(value);
      if (key === "neutralMinionKills") this.snapshot.resources.neutral_minions = this.numberOrUndefined(value);
      return;
    }

    if (feature === "abilities") {
      this.snapshot.abilities[key] = value as unknown;
      return;
    }

    if (feature === "teams") {
      this.snapshot.teams = this.recordOrEmpty(value);
      return;
    }

    if (feature === "team_frames") {
      this.snapshot.team_frames = this.recordOrEmpty(value);
      return;
    }

    if (feature === "damage") {
      this.snapshot.damage = { ...(this.snapshot.damage ?? {}), [key]: value };
      return;
    }

    if (feature === "heal") {
      this.snapshot.heal = { ...(this.snapshot.heal ?? {}), [key]: value };
      return;
    }

    if (feature === "jungle_camps") {
      this.snapshot.jungle_camps = { ...(this.snapshot.jungle_camps ?? {}), [key]: value };
      return;
    }

    if (feature === "live_client_data") {
      this.snapshot.live_client_data[key] = value as unknown;
      if (key === "game_data") {
        const gameData = this.recordOrEmpty(value);
        const gameTime = this.numberOrUndefined(gameData.gameTime);
        if (gameTime !== undefined) {
          this.snapshot.game_time_seconds = gameTime;
          this.snapshot.game_time = `${Math.floor(gameTime / 60)}:${String(gameTime % 60).padStart(2, "0")}`;
        }
      }
      if (key === "active_player") {
        const activePlayer = this.recordOrEmpty(value);
        if (this.snapshot.resources.level === undefined) {
          this.snapshot.resources.level = this.numberOrUndefined(activePlayer.level);
        }
        const name = this.stringOrUndefined(activePlayer.summonerName);
        if (name) {
          this.snapshot.summoner = { ...(this.snapshot.summoner ?? {}), name };
        }
      }
    }
  }

  private extractInfoUpdates(payload: unknown): Array<{ feature: string; key: string; value: unknown }> {
    const record = this.recordOrNull(payload);
    if (!record) return [];

    if (typeof record.feature === "string" && typeof record.key === "string") {
      return [{ feature: record.feature, key: record.key, value: record.value }];
    }

    const info = this.recordOrNull(record.info);
    const feature = typeof record.feature === "string" ? record.feature : undefined;
    if (!info || !feature) return [];

    const featureData = this.recordOrNull(info[feature]);
    if (!featureData) return [];

    return Object.entries(featureData).map(([key, value]) => ({ feature, key, value }));
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
    if (!(trimmed.startsWith("{") || trimmed.startsWith("[") || trimmed === "true" || trimmed === "false")) {
      return value;
    }
    try {
      return JSON.parse(trimmed);
    } catch {
      return value;
    }
  }

  private parsePlayersTagline(value: unknown): Array<{ playerName?: string; tagline?: string }> {
    const parsed = Array.isArray(value) ? value : [];
    return parsed
      .map((item) => this.recordOrEmpty(item))
      .map((item) => ({
        playerName: this.stringOrUndefined(item.playerName),
        tagline: this.stringOrUndefined(item.tagline),
      }))
      .filter((item) => Boolean(item.playerName));
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

  private boolOrUndefined(value: unknown): boolean | undefined {
    if (typeof value === "boolean") return value;
    if (typeof value === "string") {
      if (value === "true") return true;
      if (value === "false") return false;
    }
    return undefined;
  }
}
