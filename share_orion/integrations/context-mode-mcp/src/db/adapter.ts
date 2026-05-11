import { createRequire } from "node:module";

export type DbValue = string | number | boolean | Buffer | null;
export type DbParams = Record<string, DbValue> | DbValue[];

export interface SqlBackend {
  kind: "better-sqlite3" | "node:sqlite" | "bun:sqlite" | "none";
  dbPath: string;
  execute(sql: string, params?: DbParams): void;
  all<T = unknown>(sql: string, params?: DbParams): T[];
  get<T = unknown>(sql: string, params?: DbParams): T | undefined;
  close(): void;
}

function isNamedParams(params?: DbParams): params is Record<string, DbValue> {
  return Boolean(params) && !Array.isArray(params);
}

function paramValues(params?: DbParams): DbValue[] {
  if (!params || Array.isArray(params)) return params ? params : [];
  return Object.values(params);
}

async function openBetterSqlite(dbPath: string): Promise<SqlBackend | null> {
  try {
    const req = createRequire(import.meta.url);
    // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
    const sqlite = req("better-sqlite3");
    const DatabaseCtor = sqlite?.Database ?? sqlite?.default?.Database ?? sqlite?.default ?? sqlite;
    if (typeof DatabaseCtor !== "function") return null;
    if (!DatabaseCtor) return null;

    const db = new DatabaseCtor(dbPath);
    const execute = (sql: string, params: DbParams = []) => {
      const statement = db.prepare(sql);
      if (isNamedParams(params)) {
        statement.run(params);
      } else {
        statement.run(...paramValues(params));
      }
    };

    const all = <T = unknown>(sql: string, params: DbParams = []): T[] => {
      const statement = db.prepare(sql);
      if (isNamedParams(params)) return statement.all(params) as T[];
      return statement.all(...paramValues(params)) as T[];
    };

    const get = <T = unknown>(sql: string, params: DbParams = []): T | undefined => {
      const statement = db.prepare(sql);
      if (isNamedParams(params)) return statement.get(params) as T | undefined;
      return statement.get(...paramValues(params)) as T | undefined;
    };

    return {
      kind: "better-sqlite3",
      dbPath,
      execute,
      all,
      get,
      close() {
        db.close();
      },
    };
  } catch {
    return null;
  }
}

async function openNodeSqlite(dbPath: string): Promise<SqlBackend | null> {
  try {
    const sqlite = await import("node:sqlite");
    const DatabaseSync = (sqlite as { DatabaseSync?: new (path: string) => any }).DatabaseSync;
    if (!DatabaseSync) return null;

    const db = new DatabaseSync(dbPath);
    const execute = (sql: string, params: DbParams = []) => {
      const statement = db.prepare(sql);
      if (isNamedParams(params)) statement.run(params);
      else statement.run(...paramValues(params));
    };

    const all = <T = unknown>(sql: string, params: DbParams = []): T[] => {
      const statement = db.prepare(sql);
      if (isNamedParams(params)) return statement.all(params) as T[];
      return statement.all(...paramValues(params)) as T[];
    };

    const get = <T = unknown>(sql: string, params: DbParams = []): T | undefined => {
      const statement = db.prepare(sql);
      if (isNamedParams(params)) return statement.get(params) as T | undefined;
      return statement.get(...paramValues(params)) as T | undefined;
    };

    return {
      kind: "node:sqlite",
      dbPath,
      execute,
      all,
      get,
      close() {
        db.close();
      },
    };
  } catch {
    return null;
  }
}

async function openBunSqlite(dbPath: string): Promise<SqlBackend | null> {
  try {
    const sqlite = await import("bun:sqlite");
    const DatabaseCtor = (sqlite as { Database?: new (path: string, opts?: { create?: boolean }) => any }).Database;
    if (!DatabaseCtor) return null;

    const db = new DatabaseCtor(dbPath, { create: true });
    const execute = (sql: string, params: DbParams = []) => {
      const statement = db.query(sql);
      if (isNamedParams(params)) statement.run(params);
      else statement.run(...paramValues(params));
    };

    const all = <T = unknown>(sql: string, params: DbParams = []): T[] => {
      const statement = db.query(sql);
      if (isNamedParams(params)) return statement.all(params) as T[];
      return statement.all(...paramValues(params)) as T[];
    };

    const get = <T = unknown>(sql: string, params: DbParams = []): T | undefined => {
      const statement = db.query(sql);
      if (isNamedParams(params)) return statement.get(params) as T | undefined;
      return statement.get(...paramValues(params)) as T | undefined;
    };

    return {
      kind: "bun:sqlite",
      dbPath,
      execute,
      all,
      get,
      close() {
        db.close();
      },
    };
  } catch {
    return null;
  }
}

function openFallbackBackend(dbPath: string): SqlBackend {
  return {
    kind: "none",
    dbPath,
    execute() {
      throw new Error("No sqlite backend available");
    },
    all() {
      throw new Error("No sqlite backend available");
    },
    get() {
      throw new Error("No sqlite backend available");
    },
    close() {},
  };
}

export async function openSqlBackend(dbPath: string): Promise<SqlBackend> {
  const better = await openBetterSqlite(dbPath);
  if (better) return better;

  const node = await openNodeSqlite(dbPath);
  if (node) return node;

  const bun = await openBunSqlite(dbPath);
  if (bun) return bun;

  return openFallbackBackend(dbPath);
}

export function isUnavailableBackend(db: SqlBackend): boolean {
  return db.kind === "none";
}

export function coerceError(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
