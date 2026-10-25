/**
 * Helpers shared by the web triggers (triggers/debug.ts, glasses.ts, telegram.ts).
 */
import { timingSafeEqual } from 'crypto';

// TODO: replace with Forge's web trigger types if the SDK exports them.
export interface WebTriggerRequest {
  method?: string;
  body: string;
  headers: Record<string, string[]>;
  queryParameters?: Record<string, string[]>;
}

export interface WebTriggerResponse {
  statusCode: number;
  headers?: Record<string, string[]>;
  body?: string;
}

/** Response in the shape Forge expects from a web trigger. */
export function json(statusCode: number, body: unknown): WebTriggerResponse {
  return {
    statusCode,
    headers: { 'Content-Type': ['application/json'] },
    body: JSON.stringify(body),
  };
}

/**
 * CORS, for a web trigger the browser calls (the dashboard's Approve button): the browser
 * first sends OPTIONS (preflight, because of the x-secret header) and only then the POST.
 * Origin '*' is enough here: the request carries no cookies, the x-secret header is what
 * authorizes it.
 */
const CORS_HEADERS: Record<string, string[]> = {
  'Access-Control-Allow-Origin': ['*'],
  'Access-Control-Allow-Methods': ['POST, OPTIONS'],
  'Access-Control-Allow-Headers': ['Content-Type, x-secret'],
  'Access-Control-Max-Age': ['600'],
};

export function withCors(response: WebTriggerResponse): WebTriggerResponse {
  return { ...response, headers: { ...response.headers, ...CORS_HEADERS } };
}

/** Answer to a CORS preflight (OPTIONS). */
export function preflight(): WebTriggerResponse {
  return { statusCode: 204, headers: { ...CORS_HEADERS }, body: '' };
}

/** First value of a header, case-insensitive (HTTP header names are). */
export function header(request: WebTriggerRequest, name: string): string | undefined {
  const wanted = name.toLowerCase();
  for (const [key, values] of Object.entries(request.headers ?? {})) {
    if (key.toLowerCase() === wanted) {
      return values?.[0];
    }
  }
  return undefined;
}

/** Constant-time comparison of a received secret with the expected one; false if either is missing. */
export function secretMatches(given: string | undefined, expected: string | undefined): boolean {
  if (!given || !expected) {
    return false;
  }
  const a = Buffer.from(given);
  const b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}
