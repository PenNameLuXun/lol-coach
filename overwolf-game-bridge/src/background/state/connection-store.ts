export class ConnectionStore {
  private lastPushAt: string | null = null;

  markPush(nowIso: string): void {
    this.lastPushAt = nowIso;
  }

  getLastPushAt(): string | null {
    return this.lastPushAt;
  }
}
