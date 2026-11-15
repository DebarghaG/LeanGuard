export interface GuardConnection {
  /** A trusted deployment URL, never an agent-selected destination. */
  url: string;
  /** Service credential for one server-bound principal/session. */
  token: string;
}

export function connection(options: GuardConnection) {
  const url = new URL(options.url);
  const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (url.username || url.password || url.hash || url.search ||
      (url.protocol !== "https:" && !(url.protocol === "http:" && loopback))) {
    throw new Error("Use HTTPS, or HTTP on loopback, without URL credentials or query parameters");
  }
  if (!/^[A-Za-z0-9_-]{32,}$/.test(options.token)) {
    throw new Error("Supply the deployment's URL-safe bearer credential");
  }
  return { url, headers: { Authorization: `Bearer ${options.token}` } };
}

/** Reject values JSON would silently alter before they reach policy admission. */
export function assertJson(value: unknown, seen = new Set<object>(), depth = 0): void {
  if (depth > 64) throw new TypeError("Tool arguments exceed 64 levels");
  if (value === null || typeof value === "string" || typeof value === "boolean") return;
  if (typeof value === "number") {
    if (!Number.isFinite(value) || Object.is(value, -0) ||
        (Number.isInteger(value) && !Number.isSafeInteger(value))) {
      throw new TypeError("Tool arguments contain a non-finite or inexact JSON number");
    }
    return;
  }
  if (typeof value !== "object") throw new TypeError("Tool arguments must contain only JSON values");
  if (seen.has(value)) throw new TypeError("Tool arguments contain a cycle");
  if (!Array.isArray(value) && ![Object.prototype, null].includes(Object.getPrototypeOf(value))) {
    throw new TypeError("Tool arguments must use plain objects");
  }
  seen.add(value);
  const descriptors = Object.getOwnPropertyDescriptors(value);
  if (Object.getOwnPropertySymbols(value).length) throw new TypeError("JSON cannot preserve symbol keys");
  if (Array.isArray(value) && Object.keys(descriptors).length !== value.length + 1) {
    throw new TypeError("JSON cannot preserve sparse arrays or extra array properties");
  }
  for (const [key, descriptor] of Object.entries(descriptors)) {
    if (Array.isArray(value) && key === "length") continue;
    if (!descriptor.enumerable || !("value" in descriptor)) {
      throw new TypeError("JSON arguments must contain enumerable data properties");
    }
    if (Array.isArray(value) && (!/^(0|[1-9][0-9]*)$/.test(key) || Number(key) >= value.length)) {
      throw new TypeError("JSON cannot preserve extra array properties");
    }
    assertJson(descriptor.value, seen, depth + 1);
  }
  seen.delete(value);
}

export function snapshotJson<T>(value: T): T {
  assertJson(value);
  return JSON.parse(JSON.stringify(value));
}
