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
  market_scope TEXT NOT NULL DEFAULT 'KR',
  as_of_date TEXT NOT NULL,
  published_at TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
)`;

const ANALYSIS_REQUEST_SCHEMA = `
CREATE TABLE IF NOT EXISTS analysis_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT NOT NULL UNIQUE,
  market_scope TEXT NOT NULL DEFAULT 'KR',
  status TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  previous_run_id TEXT,
  completed_at TEXT,
  completed_run_id TEXT,
  failure_message TEXT
)`;

const ANALYSIS_COOLDOWN_MS = 5 * 60 * 1000;
const ANALYSIS_TIMEOUT_MS = 55 * 60 * 1000;

type AnalysisRequestRow = {
  request_id: string;
  market_scope: string;
  status: string;
  requested_at: string;
  previous_run_id: string | null;
  completed_at: string | null;
  completed_run_id: string | null;
  failure_message: string | null;
};

async function ensureDatabaseSchema(db: D1Database) {
  await db.batch([db.prepare(SNAPSHOT_SCHEMA), db.prepare(ANALYSIS_REQUEST_SCHEMA)]);
  const snapshotColumns = await db.prepare("PRAGMA table_info(analysis_snapshots)").all<{ name: string }>();
  const requestColumns = await db.prepare("PRAGMA table_info(analysis_requests)").all<{ name: string }>();
  if (!snapshotColumns.results.some((column) => column.name === "market_scope")) {
    await db.prepare("ALTER TABLE analysis_snapshots ADD COLUMN market_scope TEXT NOT NULL DEFAULT 'KR'").run();
  }
  if (!requestColumns.results.some((column) => column.name === "market_scope")) {
    await db.prepare("ALTER TABLE analysis_requests ADD COLUMN market_scope TEXT NOT NULL DEFAULT 'KR'").run();
  }
  await db.batch([
    db.prepare(
      "CREATE INDEX IF NOT EXISTS idx_analysis_snapshots_published_at ON analysis_snapshots (published_at)",
    ),
    db.prepare(
      "CREATE INDEX IF NOT EXISTS idx_analysis_snapshots_market_published ON analysis_snapshots (market_scope, published_at)",
    ),
    db.prepare(
      "CREATE INDEX IF NOT EXISTS idx_analysis_requests_requested_at ON analysis_requests (requested_at)",
    ),
    db.prepare(
      "CREATE INDEX IF NOT EXISTS idx_analysis_requests_market_requested ON analysis_requests (market_scope, requested_at)",
    ),
  ]);
}

async function handleSnapshot(request: Request, env: Env): Promise<Response> {
  await ensureDatabaseSchema(env.DB);
  const marketScope = marketFromRequest(request);
  if (request.method === "GET") {
    const row = await env.DB.prepare(
      "SELECT payload_json FROM analysis_snapshots WHERE market_scope=? ORDER BY published_at DESC LIMIT 1",
    ).bind(marketScope).first<{ payload_json: string }>();
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
  const payloadMarket = normalizeMarket(payload.market_scope);
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
       (run_id, market_scope, as_of_date, published_at, payload_json, created_at)
       VALUES (?, ?, ?, ?, ?, ?)
       ON CONFLICT(run_id) DO UPDATE SET
         market_scope=excluded.market_scope,
         as_of_date=excluded.as_of_date,
         published_at=excluded.published_at,
         payload_json=excluded.payload_json,
         created_at=excluded.created_at`,
    ).bind(runId, payloadMarket, asOfDate, publishedAt, payloadJson, createdAt),
    env.DB.prepare(
      `DELETE FROM analysis_snapshots
       WHERE id NOT IN (
         SELECT id FROM analysis_snapshots WHERE market_scope=? ORDER BY published_at DESC LIMIT 30
       ) AND market_scope=?`,
    ).bind(payloadMarket, payloadMarket),
    env.DB.prepare(
      `UPDATE analysis_requests
       SET status='complete', completed_at=?, completed_run_id=?, failure_message=NULL
       WHERE status='queued' AND market_scope=? AND requested_at <= ?`,
    ).bind(createdAt, runId, payloadMarket, createdAt),
    env.DB.prepare(
      `DELETE FROM analysis_requests
       WHERE id NOT IN (
         SELECT id FROM analysis_requests WHERE market_scope=? ORDER BY requested_at DESC LIMIT 30
       ) AND market_scope=?`,
    ).bind(payloadMarket, payloadMarket),
  ]);
  return jsonResponse({ ok: true, run_id: runId, market_scope: payloadMarket, as_of_date: asOfDate }, 201);
}

async function handleAnalysis(request: Request, env: Env): Promise<Response> {
  await ensureDatabaseSchema(env.DB);
  const marketScope = marketFromRequest(request);
  if (request.method === "GET") {
    return jsonResponse(await currentAnalysisState(env.DB, marketScope), 200);
  }
  if (request.method !== "POST") {
    return jsonResponse({ error: "method_not_allowed" }, 405);
  }
  if (!env.GITHUB_ACTIONS_TOKEN) {
    return jsonResponse({ error: "analysis_trigger_not_configured", message: "분석 실행 연결이 설정되지 않았습니다." }, 503);
  }

  const latest = await latestAnalysisRequest(env.DB, marketScope);
  if (latest) {
    const requestAge = Date.now() - Date.parse(latest.requested_at);
    if (latest.status === "queued" && requestAge < ANALYSIS_TIMEOUT_MS) {
      return jsonResponse(publicAnalysisState(latest), 202);
    }
    const retryAfterSeconds = analysisRetryAfterSeconds(latest);
    if (retryAfterSeconds > 0) {
      return jsonResponse({
        ...publicAnalysisState(latest),
        error: "analysis_cooldown",
        retry_after_seconds: retryAfterSeconds,
      }, 429);
    }
  }

  const previous = await env.DB.prepare(
    "SELECT run_id FROM analysis_snapshots WHERE market_scope=? ORDER BY published_at DESC LIMIT 1",
  ).bind(marketScope).first<{ run_id: string }>();
  const requestId = crypto.randomUUID();
  const requestedAt = new Date().toISOString();
  await env.DB.prepare(
    `INSERT INTO analysis_requests
     (request_id, market_scope, status, requested_at, previous_run_id)
     VALUES (?, ?, 'queued', ?, ?)`,
  ).bind(requestId, marketScope, requestedAt, previous?.run_id ?? null).run();

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
        body: JSON.stringify({
          ref: "main",
          inputs: { full_scan: "false", request_id: requestId, market: marketScope.toLowerCase() },
        }),
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
    market_scope: marketScope,
    status: "queued",
    requested_at: requestedAt,
    message: `${marketScope === "US" ? "미국" : "한국"} 최신 시장 데이터 수집과 Groq 심사를 시작했습니다.`,
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

async function currentAnalysisState(
  db: D1Database,
  marketScope: string,
): Promise<Record<string, unknown>> {
  const latest = await latestAnalysisRequest(db, marketScope);
  if (!latest) {
    return { market_scope: marketScope, status: "idle", message: "새 분석을 실행할 수 있습니다." };
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
  const state = publicAnalysisState(latest);
  const retryAfterSeconds = analysisRetryAfterSeconds(latest);
  return retryAfterSeconds > 0
    ? { ...state, retry_after_seconds: retryAfterSeconds }
    : state;
}

async function latestAnalysisRequest(
  db: D1Database,
  marketScope: string,
): Promise<AnalysisRequestRow | null> {
  return db.prepare(
    `SELECT request_id, market_scope, status, requested_at, previous_run_id,
            completed_at, completed_run_id, failure_message
     FROM analysis_requests
     WHERE market_scope=?
     ORDER BY requested_at DESC LIMIT 1`,
  ).bind(marketScope).first<AnalysisRequestRow>();
}

function publicAnalysisState(row: AnalysisRequestRow): Record<string, unknown> {
  const messages: Record<string, string> = {
    queued: "가격·재무·수급·뉴스·공시를 수집하고 Groq가 심사하고 있습니다.",
    complete: "새 분석이 완료되어 화면에 반영됐습니다.",
    failed: row.failure_message ?? "분석 작업이 실패했습니다.",
  };
  return {
    request_id: row.request_id,
    market_scope: row.market_scope,
    status: row.status,
    requested_at: row.requested_at,
    completed_at: row.completed_at,
    completed_run_id: row.completed_run_id,
    message: messages[row.status] ?? "분석 상태를 확인하고 있습니다.",
  };
}

function analysisRetryAfterSeconds(row: AnalysisRequestRow): number {
  if (row.status !== "complete") return 0;
  const cooldownStartedAt = row.completed_at ?? row.requested_at;
  const age = Date.now() - Date.parse(cooldownStartedAt);
  return Math.max(0, Math.ceil((ANALYSIS_COOLDOWN_MS - age) / 1000));
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

function marketFromRequest(request: Request): string {
  return normalizeMarket(new URL(request.url).searchParams.get("market"));
}

function normalizeMarket(value: unknown): string {
  return String(value ?? "KR").toUpperCase() === "US" ? "US" : "KR";
}

export default worker;
