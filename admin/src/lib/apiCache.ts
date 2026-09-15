/** Bounded, tab-local cache. A miss shared by several components runs once. */
export class RequestCache {
  private entries = new Map<string, { value: unknown; expires: number }>();
  private pending = new Map<string, Promise<unknown>>();
  private generation = 0;

  constructor(private maxEntries = 64, private now = () => Date.now()) {}

  clear(): void {
    this.generation += 1;
    this.entries.clear();
    this.pending.clear();
  }

  async get<T>(key: string, fetcher: () => Promise<T>, ttlMs = 60_000): Promise<T> {
    const cached = this.entries.get(key);
    if (cached && cached.expires > this.now()) {
      this.entries.delete(key);
      this.entries.set(key, cached);
      return cached.value as T;
    }
    this.entries.delete(key);
    const existing = this.pending.get(key);
    if (existing) return existing as Promise<T>;

    const generation = this.generation;
    const pending = Promise.resolve().then(fetcher).then((value) => {
      if (generation === this.generation) {
        this.entries.set(key, { value, expires: this.now() + ttlMs });
        while (this.entries.size > this.maxEntries) {
          this.entries.delete(this.entries.keys().next().value!);
        }
      }
      return value;
    });
    this.pending.set(key, pending);
    try {
      return await pending;
    } finally {
      if (this.pending.get(key) === pending) this.pending.delete(key);
    }
  }
}
