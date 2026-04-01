import type { BridgeEvent, BridgeSnapshot } from "./protocol";
import type { GameId } from "./game-ids";

export type ProviderContext = {
  nowIso: string;
};

export type ProviderOutput = {
  snapshot?: BridgeSnapshot;
  events?: BridgeEvent[];
};

export interface GameProvider {
  gameId: GameId;
  onInfoUpdate(payload: unknown, ctx: ProviderContext): ProviderOutput | null;
  onNewEvent(payload: unknown, ctx: ProviderContext): ProviderOutput | null;
}
