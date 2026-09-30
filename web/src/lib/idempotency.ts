export type IdempotencyKeyFactory = () => string;

/** Retains one key for one canonical logical payload until completion or reset. */
export class LogicalActionIdempotencyKey {
  private fingerprint: string | undefined;
  private key: string | undefined;

  constructor(private readonly createKey: IdempotencyKeyFactory = () => crypto.randomUUID()) {}

  keyFor(fingerprint: string): string {
    if (this.key === undefined || this.fingerprint !== fingerprint) {
      this.fingerprint = fingerprint;
      this.key = this.createKey();
    }
    return this.key;
  }

  complete(): void {
    this.fingerprint = undefined;
    this.key = undefined;
  }

  beginNewAction(): void {
    this.complete();
  }
}
