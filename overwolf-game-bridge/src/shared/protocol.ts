import type { GameId } from "./game-ids";

export type BridgeSnapshot = {
  source: "overwolf";
  game_id: GameId;
  timestamp: string;
  data: Record<string, unknown>;
};

export type BridgeEvent = {
  source: "overwolf";
  game_id: GameId;
  event: string;
  timestamp: string;
  data: Record<string, unknown>;
};
