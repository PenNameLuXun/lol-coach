import type { GameProvider } from "../../shared/types";
import { LolProvider } from "./providers/lol";
import { TftProvider } from "./providers/tft";

export function buildProviderRegistry(): GameProvider[] {
  return [
    new TftProvider(),
    new LolProvider(),
  ];
}
