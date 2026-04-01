export const GAME_IDS = {
  TFT: "tft",
  LOL: "lol",
} as const;

export type GameId = (typeof GAME_IDS)[keyof typeof GAME_IDS];
