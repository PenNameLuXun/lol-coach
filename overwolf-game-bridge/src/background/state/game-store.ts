export class GameStore {
  private readonly snapshots = new Map<string, Record<string, unknown>>();

  update(gameId: string, data: Record<string, unknown>): void {
    const previous = this.snapshots.get(gameId) ?? {};
    this.snapshots.set(gameId, { ...previous, ...data });
  }

  get(gameId: string): Record<string, unknown> | undefined {
    return this.snapshots.get(gameId);
  }
}
