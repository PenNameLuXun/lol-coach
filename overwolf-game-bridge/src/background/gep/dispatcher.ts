import type { GameProvider, ProviderOutput } from "../../shared/types";

export class GepDispatcher {
  constructor(private readonly providers: GameProvider[]) {}

  dispatchInfo(gameId: string, payload: unknown, nowIso: string): ProviderOutput | null {
    const provider = this.providers.find((item) => item.gameId === gameId);
    return provider?.onInfoUpdate(payload, { nowIso }) ?? null;
  }

  dispatchEvent(gameId: string, payload: unknown, nowIso: string): ProviderOutput | null {
    const provider = this.providers.find((item) => item.gameId === gameId);
    return provider?.onNewEvent(payload, { nowIso }) ?? null;
  }
}
