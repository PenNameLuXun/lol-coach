import type { OverwolfGameInfo } from "../../shared/overwolf";
import { AppController } from "../app-controller";
import { requiredFeaturesFor } from "./feature-map";

// Note: keep these as heuristics until the real Overwolf runtime confirms exact class IDs.
const TFT_CLASS_IDS = new Set<number>([5426]);
const LOL_CLASS_IDS = new Set<number>([5425]);

export class OverwolfRuntime {
  private boundInfoListener = (payload: unknown) => this.handleInfoUpdate(payload);
  private boundEventListener = (payload: unknown) => this.handleNewEvents(payload);
  private boundGameInfoListener = (payload: { gameInfo?: OverwolfGameInfo }) => {
    void this.handleGameInfo(payload.gameInfo);
  };
  private activeGameId: string | null = null;

  constructor(private readonly controller: AppController) {}

  async start(): Promise<void> {
    const ow = window.overwolf;
    if (!ow) {
      console.warn("Overwolf runtime not available; running in scaffold mode.");
      return;
    }

    ow.games.events.onInfoUpdates2.removeListener(this.boundInfoListener as (payload: any) => void);
    ow.games.events.onNewEvents.removeListener(this.boundEventListener as (payload: any) => void);
    ow.games.onGameInfoUpdated.removeListener(this.boundGameInfoListener as (payload: any) => void);

    ow.games.events.onInfoUpdates2.addListener(this.boundInfoListener as (payload: any) => void);
    ow.games.events.onNewEvents.addListener(this.boundEventListener as (payload: any) => void);
    ow.games.onGameInfoUpdated.addListener(this.boundGameInfoListener as (payload: any) => void);
    ow.games.events.onError.addListener((error: { reason?: string; message?: string }) => {
      console.error("Overwolf GEP error", error);
    });

    ow.games.getRunningGameInfo((info) => {
      void this.handleGameInfo(info);
    });
  }

  private async handleGameInfo(info?: OverwolfGameInfo): Promise<void> {
    const gameId = this.resolveGameId(info);
    if (!gameId || gameId === this.activeGameId) {
      return;
    }
    this.activeGameId = gameId;
    const features = requiredFeaturesFor(gameId);
    if (!features.length || !window.overwolf) {
      return;
    }
    await this.setRequiredFeatures(features);
    window.overwolf.games.events.getInfo((payload) => {
      void this.controller.pushInfo(gameId, payload);
    });
  }

  private async setRequiredFeatures(features: string[]): Promise<void> {
    if (!window.overwolf) {
      return;
    }
    const maxAttempts = 5;
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      const result = await new Promise<{ success: boolean; supportedFeatures: string[] }>((resolve) => {
        window.overwolf?.games.events.setRequiredFeatures(features, resolve);
      });
      if (result.success) {
        console.log("setRequiredFeatures success", result.supportedFeatures);
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000 * attempt));
    }
    console.warn("setRequiredFeatures failed", features);
  }

  private async handleInfoUpdate(payload: unknown): Promise<void> {
    if (!this.activeGameId) {
      return;
    }
    await this.controller.pushInfo(this.activeGameId, payload);
  }

  private async handleNewEvents(payload: unknown): Promise<void> {
    if (!this.activeGameId) {
      return;
    }
    await this.controller.pushEvent(this.activeGameId, payload);
  }

  private resolveGameId(info?: OverwolfGameInfo): string | null {
    const classId = info?.classId;
    const title = String(info?.title ?? "").toLowerCase();
    if (classId !== undefined) {
      if (TFT_CLASS_IDS.has(classId)) {
        return "tft";
      }
      if (LOL_CLASS_IDS.has(classId)) {
        return "lol";
      }
    }
    if (title.includes("teamfight tactics") || title.includes("云顶")) {
      return "tft";
    }
    if (title.includes("league of legends") || title.includes("英雄联盟")) {
      return "lol";
    }
    return null;
  }
}
