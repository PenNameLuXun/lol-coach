import { GAME_IDS } from "../../shared/game-ids";

const FEATURE_MAP: Record<string, string[]> = {
  [GAME_IDS.TFT]: [
    "me",
    "match_info",
    "roster",
    "store",
    "board",
    "bench",
    "carousel",
    "live_client_data",
  ],
  [GAME_IDS.LOL]: [
    "live_client_data",
    "matchState",
    "match_info",
    "abilities",
    "gold",
    "minions",
    "summoner_info",
    "teams",
    "team_frames",
    "damage",
    "heal",
    "jungle_camps",
    "level",
    "gameMode",
  ],
};

export function requiredFeaturesFor(gameId: string): string[] {
  return FEATURE_MAP[gameId] ?? [];
}
