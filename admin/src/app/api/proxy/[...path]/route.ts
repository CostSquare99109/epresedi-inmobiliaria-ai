import { NextRequest, NextResponse } from "next/server";

/**
 * Proxy for client-side mutations: forwards the request to the internal API
 * injecting X-Admin-Token server-side (never exposed to the browser).
 */
async function forward(req: NextRequest, path: string[]) {
  const target = `${(process.env.API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "")}/${path.join("/")}${req.nextUrl.search}`;
  const body = req.method === "GET" || req.method === "HEAD" ? undefined : await req.arrayBuffer();
  const res = await fetch(target, {
    method: req.method,
    headers: {
      "X-Admin-Token": process.env.ADMIN_TOKEN ?? "",
      "Content-Type": req.headers.get("content-type") ?? "application/json",
    },
    body,
    cache: "no-store",
  });
  const data = await res.arrayBuffer();
  return new NextResponse(data, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("content-type") ?? "application/json" },
  });
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
