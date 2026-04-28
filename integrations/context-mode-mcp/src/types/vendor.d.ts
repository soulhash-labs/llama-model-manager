declare module "bun:sqlite" {
  export class Database {
    constructor(path: string, opts?: { create?: boolean });
    query(sql: string): {
      run(...params: unknown[]): unknown;
      all(...params: unknown[]): unknown[];
      get(...params: unknown[]): unknown;
    };
    close(): void;
  }
}

declare module "turndown" {
  export default class TurndownService {
    constructor(options?: Record<string, unknown>);
    turndown(input: string): string;
  }
}
