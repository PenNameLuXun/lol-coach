import type { BridgeEvent, BridgeSnapshot } from "../../shared/protocol";
import { DEFAULT_BRIDGE_URL } from "../../shared/consts";

export class BridgeClient {
  constructor(private readonly baseUrl: string = DEFAULT_BRIDGE_URL) {}

  async postSnapshot(snapshot: BridgeSnapshot): Promise<void> {
    await fetch(`${this.baseUrl}/snapshot`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(snapshot),
    });
  }

  async postEvent(event: BridgeEvent): Promise<void> {
    await fetch(`${this.baseUrl}/event`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(event),
    });
  }
}
