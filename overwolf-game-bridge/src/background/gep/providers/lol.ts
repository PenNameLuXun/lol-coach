import { GAME_IDS } from "../../../shared/game-ids";
import type { GameProvider, ProviderContext, ProviderOutput } from "../../../shared/types";

export class LolProvider implements GameProvider {
  readonly gameId = GAME_IDS.LOL;

  onInfoUpdate(_payload: unknown, _ctx: ProviderContext): ProviderOutput | null {
    return null;
  }

  onNewEvent(_payload: unknown, _ctx: ProviderContext): ProviderOutput | null {
    return null;
  }
}
