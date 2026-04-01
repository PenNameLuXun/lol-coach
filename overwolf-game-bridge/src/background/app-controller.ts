import { BridgeClient } from "./bridge/client";
import { GepDispatcher } from "./gep/dispatcher";
import { buildProviderRegistry } from "./gep/registry";

export class AppController {
  private readonly bridgeClient = new BridgeClient();
  private readonly dispatcher = new GepDispatcher(buildProviderRegistry());

  async pushInfo(gameId: string, payload: unknown): Promise<void> {
    const output = this.dispatcher.dispatchInfo(gameId, payload, new Date().toISOString());
    if (!output?.snapshot) {
      return;
    }
    await this.bridgeClient.postSnapshot(output.snapshot);
  }

  async pushEvent(gameId: string, payload: unknown): Promise<void> {
    const output = this.dispatcher.dispatchEvent(gameId, payload, new Date().toISOString());
    if (!output?.events?.length) {
      return;
    }
    for (const event of output.events) {
      await this.bridgeClient.postEvent(event);
    }
  }
}
