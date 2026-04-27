import { randomBytes } from "node:crypto";

export function nowMs(): number {
  return Date.now();
}

export function toISO(value: string | number | Date = new Date()): string {
  if (value instanceof Date) return value.toISOString();
  if (typeof value === "number") return new Date(value).toISOString();
  return new Date(value).toISOString();
}

export function clampBytes(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.floor(value));
}

export function newRequestId(): string {
  return randomBytes(8).toString("hex");
}

export function newRequestIdIfMissing(value?: string): string {
  return value || newRequestId();
}
