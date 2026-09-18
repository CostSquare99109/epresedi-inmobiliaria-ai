import { NextRequest, NextResponse } from "next/server";

/**
 * Proxy for client-side mutations: forwards the request to the internal API
 * injecting JWT authentication (Bearer token or cookie).
 * The legacy X-Admin-Token path was removed: a shared static token must never bypass RBAC.
 */

// Simple in-memory rate limiter for admin proxy
const RATE_LIMIT_WINDOW_MS = 60_000; // 1 minute
const RATE_LIMIT_MAX_REQUESTS = 100; // 100 requests per minute per IP
const rateLimitMap = new Map<string, { count: number; windowStart: number }>();

function checkRateLimit(ip: string): { allowed: boolean; remaining: number; resetMs: number } {
  const now = Date.now();
  const entry = rateLimitMap.get(ip);

  if (!entry || now - entry.windowStart >= RATE_LIMIT_WINDOW_MS) {
    rateLimitMap.set(ip, { count: 1, windowStart: now });
    return { allowed: true, remaining: RATE_LIMIT_MAX_REQUESTS - 1, resetMs: RATE_LIMIT_WINDOW_MS };
  }

  if (entry.count >= RATE_LIMIT_MAX_REQUESTS) {
    const resetMs = RATE_LIMIT_WINDOW_MS - (now - entry.windowStart);
    return { allowed: false, remaining: 0, resetMs: Math.max(resetMs, 0) };
  }

  entry.count++;
  return { allowed: true, remaining: RATE_LIMIT_MAX_REQUESTS - entry.count, resetMs: RATE_LIMIT_WINDOW_MS - (now - entry.windowStart) };
}

// Cleanup old entries periodically
setInterval(() => {
  const now = Date.now();
  for (const [ip, entry] of rateLimitMap.entries()) {
    if (now - entry.windowStart >= RATE_LIMIT_WINDOW_MS * 2) {
      rateLimitMap.delete(ip);
    }
  }
}, RATE_LIMIT_WINDOW_MS * 5);

async function forward(req: NextRequest, path: string[]) {
  // Rate limiting by IP
  const forwarded = req.headers.get("x-forwarded-for");
  const ip = forwarded?.split(",")[0]?.trim() || req.headers.get("x-real-ip") || "unknown";
  const rateLimit = checkRateLimit(ip);

  if (!rateLimit.allowed) {
    return new NextResponse(JSON.stringify({ error: "Rate limit exceeded" }), {
      status: 429,
      headers: {
        "Content-Type": "application/json",
        "Retry-After": String(Math.ceil(rateLimit.resetMs / 1000)),
        "X-RateLimit-Limit": String(RATE_LIMIT_MAX_REQUESTS),
        "X-RateLimit-Remaining": String(rateLimit.remaining),
        "X-RateLimit-Reset": String(Math.ceil((Date.now() + rateLimit.resetMs) / 1000)),
      },
    });
  }

  const target = `${(process.env.API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "")}/${path.join("/")}${req.nextUrl.search}`;
  const body = req.method === "GET" || req.method === "HEAD" ? undefined : await req.arrayBuffer();

  // Extract JWT from Authorization header or cookie
  const authHeader = req.headers.get("authorization");
  const cookieToken = req.cookies.get("admin_access_token")?.value;

  const headers: Record<string, string> = {
    "Content-Type": req.headers.get("content-type") ?? "application/json",
  };

  if (authHeader?.startsWith("Bearer ")) {
    headers["Authorization"] = authHeader;
  } else if (cookieToken) {
    headers["Authorization"] = `Bearer ${cookieToken}`;
  }

  const res = await fetch(target, {
    method: req.method,
    headers,
    body,
    cache: "no-store",
  });

  const data = await res.arrayBuffer();
  const responseHeaders = new Headers();
  responseHeaders.set("Content-Type", res.headers.get("content-type") ?? "application/json");
  responseHeaders.set("X-RateLimit-Limit", String(RATE_LIMIT_MAX_REQUESTS));
  responseHeaders.set("X-RateLimit-Remaining", String(rateLimit.remaining));
  responseHeaders.set("X-RateLimit-Reset", String(Math.ceil((Date.now() + rateLimit.resetMs) / 1000)));

  // Forward all Set-Cookie headers from backend (for auth cookies)
  // In Next.js/Edge runtime, we can access raw headers via the headers() iterator
  try {
    // Try getSetCookie() if available (modern Fetch API)
    const getSetCookie = res.headers.getSetCookie?.bind(res.headers);
    if (getSetCookie) {
      for (const cookie of getSetCookie()) {
        responseHeaders.append("Set-Cookie", cookie);
      }
    } else {
      // Fallback: iterate all headers to find set-cookie (case-insensitive)
      for (const [key, value] of res.headers.entries()) {
        if (key.toLowerCase() === "set-cookie") {
          responseHeaders.append("Set-Cookie", value);
        }
      }
    }
  } catch {
    // Last resort: try single get()
    const setCookieHeader = res.headers.get("set-cookie");
    if (setCookieHeader) {
      responseHeaders.append("Set-Cookie", setCookieHeader);
    }
  }

  const response = new NextResponse(data, {
    status: res.status,
    headers: responseHeaders,
  });

  return response;
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return forward(req, path);
}

export async function POST(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return forward(req, path);
}

export async function PATCH(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return forward(req, path);
}

export async function DELETE(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return forward(req, path);
}