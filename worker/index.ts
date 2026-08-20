/** Cloudflare Worker entry point for the vinext-starter template. */
import { handleImageOptimization, DEFAULT_DEVICE_SIZES, DEFAULT_IMAGE_SIZES } from "vinext/server/image-optimization";
import handler from "vinext/server/app-router-entry";

interface Env {
  ASSETS: Fetcher;
  DB: D1Database;
  SNAPSHOT_WRITE_TOKEN?: string;
  GITHUB_ACTIONS_TOKEN?: string;
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

    if (url.pathname === "/api/analyze/callback") {
      return handleAnalysisCallback(request, env);
    }

    if (url.pathname === "/api/analyze") {
      return handleAnalysis(request, env);
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

const ANALYSIS_REQUEST_SCHEMA = `
CREATE TABLE IF NOT EXISTS analysis_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  previous_run_id TEXT,
  completed_at TEXT,
  completed_run_id TEXT,
  failure_message TEXT
)`;

const ANALYSIS_COOLDOWN_MS = 30 * 60 * 1000;
const ANALYSIS_TIMEOUT_MS = 55 * 60 * 1000;

type AnalysisRequestRow = {
  request_id: string;
  status: string;
  requested_at: string;
  previous_run_id: string | null;
  completed_at: string | null;
  completed_run_id: string | null;
  failure_message: string | null;
};

async function ensureDatabaseSchema(db: D1Database) {
  await db.batch([
    db.prepare(SNAPSHOT_SCHEMA),
    db.prepare(
      "CREATE INDEX IF NOT EXISTS idx_analysis_snapshots_published_at ON analysis_snapshots (published_at)",
    ),
    db.prepare(ANALYSIS_REQUEST_SCHEMA),
    db.prepare(
      "CREATE INDEX IF NOT EXISTS idx_analysis_requests_requested_at ON analysis_requests (requested_at)",
    ),
  ]);
}

async function handleSnapshot(request: Request, env: Env): Promise<Response> {
  await ensureDatabaseSchema(env.DB);
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
    env.DB.prepare(
      `UPDATE analysis_requests
       SET status='complete', completed_at=?, completed_run_id=?, failure_message=NULL
       WHERE status='queued' AND requested_at <= ?`,
    ).bind(createdAt, runId, createdAt),
    env.DB.prepare(
      `DELETE FROM analysis_requests
       WHERE id NOT IN (
         SELECT id FROM analysis_requests ORDER BY requested_at DESC LIMIT 30
       )`,
    ),
  ]);
  return jsonResponse({ ok: true, run_id: runId, as_of_date: asOfDate }, 201);
}

async function handleAnalysis(request: Request, env: Env): Promise<Response> {
  await ensureDatabaseSchema(env.DB);
  if (request.method === "GET") {
    return jsonResponse(await currentAnalysisState(env.DB), 200);
  }
  if (request.method !== "POST") {
    return jsonResponse({ error: "method_not_allowed" }, 405);
  }
  if (!env.GITHUB_ACTIONS_TOKEN) {
    return jsonResponse({ error: "analysis_trigger_not_configured", message: "분석 실행 연결이 설정되지 않았습니다." }, 503);
  }

  const latest = await latestAnalysisRequest(env.DB);
  if (latest) {
    const age = Date.now() - Date.parse(latest.requested_at);
    if (latest.status === "queued" && age < ANALYSIS_TIMEOUT_MS) {
      return jsonResponse(publicAnalysisState(latest), 202);
    }
    if (age < ANALYSIS_COOLDOWN_MS) {
      return jsonResponse({
        ...publicAnalysisState(latest),
        error: "analysis_cooldown",
        retry_after_seconds: Math.ceil((ANALYSIS_COOLDOWN_MS - age) / 1000),
      }, 429);
    }
  }

  const previous = await env.DB.prepare(
    "SELECT run_id FROM analysis_snapshots ORDER BY published_at DESC LIMIT 1",
  ).first<{ run_id: string }>();
  const requestId = crypto.randomUUID();
  const requestedAt = new Date().toISOString();
  await env.DB.prepare(
    `INSERT INTO analysis_requests
     (request_id, status, requested_at, previous_run_id)
     VALUES (?, 'queued', ?, ?)`,
  ).bind(requestId, requestedAt, previous?.run_id ?? null).run();

  let dispatch: Response;
  try {
    dispatch = await fetch(
      "https://api.github.com/repos/asdf8421/toss/actions/workflows/publish-analysis.yml/dispatches",
      {
        method: "POST",
        headers: {
          accept: "application/vnd.github+json",
          authorization: `Bearer ${env.GITHUB_ACTIONS_TOKEN}`,
          "content-type": "application/json",
          "user-agent": "evidence-first-fund-manager",
          "x-github-api-version": "2022-11-28",
        },
        body: JSON.stringify({ ref: "main", inputs: { full_scan: "false", request_id: requestId } }),
      },
    );
  } catch {
    return failAnalysisRequest(env.DB, requestId, "GitHub 분석 실행 서버에 연결하지 못했습니다.");
  }
  if (dispatch.status !== 204) {
    return failAnalysisRequest(env.DB, requestId, `GitHub 분석 실행 요청이 거부되었습니다. (${dispatch.status})`);
  }

  return jsonResponse({
    request_id: requestId,
    status: "queued",
    requested_at: requestedAt,
    message: "최신 시장 데이터 수집과 Groq 심사를 시작했습니다.",
  }, 202);
}

async function handleAnalysisCallback(request: Request, env: Env): Promise<Response> {
  await ensureDatabaseSchema(env.DB);
  if (request.method !== "POST") {
    return jsonResponse({ error: "method_not_allowed" }, 405);
  }
  const token = env.SNAPSHOT_WRITE_TOKEN;
  if (!token || request.headers.get("authorization") !== `Bearer ${token}`) {
    return jsonResponse({ error: "unauthorized" }, 401);
  }
  let payload: { request_id?: string; status?: string; message?: string };
  try {
    payload = await request.json();
  } catch {
    return jsonResponse({ error: "invalid_json" }, 400);
  }
  if (!payload.request_id || payload.status !== "failed") {
    return jsonResponse({ error: "invalid_callback" }, 400);
  }
  const completedAt = new Date().toISOString();
  await env.DB.prepare(
    `UPDATE analysis_requests
     SET status='failed', completed_at=?, failure_message=?
     WHERE request_id=?`,
  ).bind(completedAt, payload.message ?? "분석 작업이 실패했습니다.", payload.request_id).run();
  return jsonResponse({ ok: true }, 200);
}

async function currentAnalysisState(db: D1Database): Promise<Record<string, unknown>> {
  const latest = await latestAnalysisRequest(db);
  if (!latest) {
    return { status: "idle", message: "새 분석을 실행할 수 있습니다." };
  }
  if (latest.status === "queued" && Date.now() - Date.parse(latest.requested_at) >= ANALYSIS_TIMEOUT_MS) {
    const message = "분석이 제한 시간 안에 완료되지 않았습니다. 다시 실행해 주세요.";
    await db.prepare(
      `UPDATE analysis_requests
       SET status='failed', completed_at=?, failure_message=?
       WHERE request_id=?`,
    ).bind(new Date().toISOString(), message, latest.request_id).run();
    return { ...publicAnalysisState(latest), status: "failed", message };
  }
  return publicAnalysisState(latest);
}

async function latestAnalysisRequest(db: D1Database): Promise<AnalysisRequestRow | null> {
  return db.prepare(
    `SELECT request_id, status, requested_at, previous_run_id,
            completed_at, completed_run_id, failure_message
     FROM analysis_requests
     ORDER BY requested_at DESC LIMIT 1`,
  ).first<AnalysisRequestRow>();
}

function publicAnalysisState(row: AnalysisRequestRow): Record<string, unknown> {
  const messages: Record<string, string> = {
    queued: "가격·재무·수급·뉴스·공시를 수집하고 Groq가 심사하고 있습니다.",
    complete: "새 분석이 완료되어 화면에 반영됐습니다.",
    failed: row.failure_message ?? "분석 작업이 실패했습니다.",
  };
  return {
    request_id: row.request_id,
    status: row.status,
    requested_at: row.requested_at,
    completed_at: row.completed_at,
    completed_run_id: row.completed_run_id,
    message: messages[row.status] ?? "분석 상태를 확인하고 있습니다.",
  };
}

async function failAnalysisRequest(db: D1Database, requestId: string, message: string): Promise<Response> {
  await db.prepare(
    `UPDATE analysis_requests
     SET status='failed', completed_at=?, failure_message=?
     WHERE request_id=?`,
  ).bind(new Date().toISOString(), message, requestId).run();
  return jsonResponse({ request_id: requestId, status: "failed", message }, 502);
}

function jsonResponse(payload: unknown, status: number): Response {
  return Response.json(payload, {
    status,
    headers: { "cache-control": "no-store, max-age=0" },
  });
}

export default worker;
