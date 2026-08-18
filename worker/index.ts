/** Cloudflare Worker entry point for the vinext-starter template. */
import { handleImageOptimization, DEFAULT_DEVICE_SIZES, DEFAULT_IMAGE_SIZES } from "vinext/server/image-optimization";
import handler from "vinext/server/app-router-entry";

interface Env {
  ASSETS: Fetcher;
  DB: D1Database;
  SNAPSHOT_WRITE_TOKEN?: string;
  IMAGES: {
    input(stream: ReadableStream): {
      transform(options: Record<string, unknown>): {
        output(options: { format: string; quality: number }): Promise<{ response(): Response }>;
      };
    };
  };
}

interface ExecutionContext {
  waitUntil(promise: Promise<unknown>): void;
  passThroughOnException(): void;
}

// Image security config. SVG sources with .svg extension auto-skip the
// optimization endpoint on the client side (served directly, no proxy).
// To route SVGs through the optimizer (with security headers), set
// dangerouslyAllowSVG: true in next.config.js and uncomment below:
// const imageConfig: ImageConfig = { dangerouslyAllowSVG: true };

const worker = {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/api/snapshot") {
      return handleSnapshot(request, env);
    }

    if (url.pathname === "/_vinext/image") {
      const allowedWidths = [...DEFAULT_DEVICE_SIZES, ...DEFAULT_IMAGE_SIZES];
      return handleImageOptimization(request, {
        fetchAsset: (path) => env.ASSETS.fetch(new Request(new URL(path, request.url))),
        transformImage: async (body, { width, format, quality }) => {
          const result = await env.IMAGES.input(body).transform(width > 0 ? { width } : {}).output({ format, quality });
          return result.response();
        },
      }, allowedWidths);
    }

    return handler.fetch(request, env, ctx);
  },
};

const SNAPSHOT_SCHEMA = `
CREATE TABLE IF NOT EXISTS analysis_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL UNIQUE,
  as_of_date TEXT NOT NULL,
  published_at TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
)`;

async function ensureSnapshotSchema(db: D1Database) {
  await db.batch([
    db.prepare(SNAPSHOT_SCHEMA),
    db.prepare(
      "CREATE INDEX IF NOT EXISTS idx_analysis_snapshots_published_at ON analysis_snapshots (published_at)",
    ),
  ]);
}

async function handleSnapshot(request: Request, env: Env): Promise<Response> {
  await ensureSnapshotSchema(env.DB);
  if (request.method === "GET") {
    const row = await env.DB.prepare(
      "SELECT payload_json FROM analysis_snapshots ORDER BY published_at DESC LIMIT 1",
    ).first<{ payload_json: string }>();
    if (!row) {
      return jsonResponse({ error: "analysis_not_published" }, 404);
    }
    return new Response(row.payload_json, {
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store, max-age=0",
      },
    });
  }

  if (request.method !== "POST") {
    return jsonResponse({ error: "method_not_allowed" }, 405);
  }
  const token = env.SNAPSHOT_WRITE_TOKEN;
  const authorization = request.headers.get("authorization") ?? "";
  if (!token || authorization !== `Bearer ${token}`) {
    return jsonResponse({ error: "unauthorized" }, 401);
  }
  const contentLength = Number(request.headers.get("content-length") ?? 0);
  if (contentLength > 2_000_000) {
    return jsonResponse({ error: "snapshot_too_large" }, 413);
  }

  let payload: Record<string, unknown>;
  try {
    payload = (await request.json()) as Record<string, unknown>;
  } catch {
    return jsonResponse({ error: "invalid_json" }, 400);
  }
  const runId = String(payload.run_id ?? "");
  const asOfDate = String(payload.as_of_date ?? "");
  const publishedAt = String(payload.generated_at ?? "");
  if (!runId || !/^\d{4}-\d{2}-\d{2}$/.test(asOfDate) || !publishedAt) {
    return jsonResponse({ error: "invalid_snapshot" }, 400);
  }
  const payloadJson = JSON.stringify(payload);
  if (payloadJson.length > 2_000_000) {
    return jsonResponse({ error: "snapshot_too_large" }, 413);
  }
  const createdAt = new Date().toISOString();
  await env.DB.batch([
    env.DB.prepare(
      `INSERT INTO analysis_snapshots
       (run_id, as_of_date, published_at, payload_json, created_at)
       VALUES (?, ?, ?, ?, ?)
       ON CONFLICT(run_id) DO UPDATE SET
         as_of_date=excluded.as_of_date,
         published_at=excluded.published_at,
         payload_json=excluded.payload_json,
         created_at=excluded.created_at`,
    ).bind(runId, asOfDate, publishedAt, payloadJson, createdAt),
    env.DB.prepare(
      `DELETE FROM analysis_snapshots
       WHERE id NOT IN (
         SELECT id FROM analysis_snapshots ORDER BY published_at DESC LIMIT 30
       )`,
    ),
  ]);
  return jsonResponse({ ok: true, run_id: runId, as_of_date: asOfDate }, 201);
}

function jsonResponse(payload: unknown, status: number): Response {
  return Response.json(payload, {
    status,
    headers: { "cache-control": "no-store, max-age=0" },
  });
}

export default worker;
