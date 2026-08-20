import assert from "node:assert/strict";
import test from "node:test";

async function render() {
  const worker = await loadWorker();
  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

async function loadWorker() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}-${Math.random()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker;
}

class FakeD1 {
  payload = null;
  request = null;
  prepare(sql) {
    const db = this;
    return {
      sql,
      args: [],
      bind(...args) { this.args = args; return this; },
      async first() {
        if (sql.includes("SELECT payload_json") && db.payload) return { payload_json: db.payload };
        if (sql.includes("SELECT run_id FROM analysis_snapshots") && db.payload) {
          return { run_id: JSON.parse(db.payload).run_id };
        }
        if (sql.includes("FROM analysis_requests")) return db.request;
        return null;
      },
      async run() {
        if (sql.includes("INSERT INTO analysis_requests")) {
          db.request = {
            request_id: this.args[0],
            status: "queued",
            requested_at: this.args[1],
            previous_run_id: this.args[2],
            completed_at: null,
            completed_run_id: null,
            failure_message: null,
          };
        }
        if (sql.includes("UPDATE analysis_requests") && sql.includes("status='failed'") && db.request) {
          db.request = { ...db.request, status: "failed", completed_at: this.args[0], failure_message: this.args[1] };
        }
        return { success: true };
      },
    };
  }
  async batch(statements) {
    for (const statement of statements) {
      if (statement.sql.includes("INSERT INTO analysis_snapshots")) this.payload = statement.args[3];
      if (statement.sql.includes("UPDATE analysis_requests") && statement.sql.includes("status='complete'") && this.request) {
        this.request = {
          ...this.request,
          status: "complete",
          completed_at: statement.args[0],
          completed_run_id: statement.args[1],
          failure_message: null,
        };
      }
    }
    return [];
  }
}

test("server-renders the live analysis shell without invented recommendations", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, /AI Fund Manager/);
  assert.match(html, /오늘 무엇을 해야 하는가/);
  assert.match(html, /오늘 할 일/);
  assert.match(html, /실시간 호가 아님/);
  assert.match(html, /최신 분석을 불러오는 중입니다/);
  assert.doesNotMatch(html, /LG전자|24주 매수|ffc9dd1ad3/);
  assert.doesNotMatch(html, /Your site is taking shape|Building your site/);
});

test("renders evidence and risk disclosures", async () => {
  const response = await render();
  const html = await response.text();
  assert.match(html, /임의 종목이나 예측 숫자를 채우지 않습니다/);
  assert.match(html, /데이터 수집과 Groq 심사가 끝난 결과만/);
  assert.match(html, /자동 주문 기능 없음/);
  assert.match(html, /저장된 추천값을 표시하지 않고/);
});

test("accepts an authenticated snapshot and serves only the stored payload", async () => {
  const worker = await loadWorker();
  const db = new FakeD1();
  const env = {
    DB: db,
    SNAPSHOT_WRITE_TOKEN: "test-token",
    ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) },
  };
  const ctx = { waitUntil() {}, passThroughOnException() {} };
  const snapshot = {
    schema_version: 1,
    run_id: "verified-run",
    as_of_date: "2026-08-18",
    generated_at: "2026-08-18T07:30:00Z",
    decisions: [],
  };

  const denied = await worker.fetch(new Request("http://localhost/api/snapshot", { method: "POST", body: JSON.stringify(snapshot) }), env, ctx);
  assert.equal(denied.status, 401);

  const stored = await worker.fetch(new Request("http://localhost/api/snapshot", {
    method: "POST",
    headers: { authorization: "Bearer test-token", "content-type": "application/json" },
    body: JSON.stringify(snapshot),
  }), env, ctx);
  assert.equal(stored.status, 201);

  const response = await worker.fetch(new Request("http://localhost/api/snapshot"), env, ctx);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), snapshot);
});

test("queues a fresh analysis and marks it complete when the new snapshot arrives", async () => {
  const worker = await loadWorker();
  const db = new FakeD1();
  const env = {
    DB: db,
    GITHUB_ACTIONS_TOKEN: "github-test-token",
    SNAPSHOT_WRITE_TOKEN: "snapshot-test-token",
    ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) },
  };
  const ctx = { waitUntil() {}, passThroughOnException() {} };
  const originalFetch = globalThis.fetch;
  let dispatchUrl = "";
  globalThis.fetch = async (request, options) => {
    dispatchUrl = String(request);
    assert.equal(options.method, "POST");
    assert.match(options.headers.authorization, /^Bearer /);
    return new Response(null, { status: 204 });
  };
  try {
    const queued = await worker.fetch(new Request("http://localhost/api/analyze", { method: "POST" }), env, ctx);
    assert.equal(queued.status, 202);
    assert.match(dispatchUrl, /publish-analysis\.yml\/dispatches$/);
    const firstRequest = await queued.json();
    assert.equal(firstRequest.status, "queued");

    const running = await worker.fetch(new Request("http://localhost/api/analyze"), env, ctx);
    assert.equal((await running.json()).status, "queued");

    const failed = await worker.fetch(new Request("http://localhost/api/analyze/callback", {
      method: "POST",
      headers: { authorization: "Bearer snapshot-test-token", "content-type": "application/json" },
      body: JSON.stringify({ request_id: firstRequest.request_id, status: "failed", message: "Groq schema error" }),
    }), env, ctx);
    assert.equal(failed.status, 200);

    const retry = await worker.fetch(new Request("http://localhost/api/analyze", { method: "POST" }), env, ctx);
    assert.equal(retry.status, 202);
    const retryState = await retry.json();
    assert.equal(retryState.status, "queued");
    assert.notEqual(retryState.request_id, firstRequest.request_id);

    const snapshot = {
      schema_version: 1,
      run_id: "new-live-run",
      as_of_date: "2026-08-20",
      generated_at: "2026-08-20T04:50:00Z",
      decisions: [],
    };
    const published = await worker.fetch(new Request("http://localhost/api/snapshot", {
      method: "POST",
      headers: { authorization: "Bearer snapshot-test-token", "content-type": "application/json" },
      body: JSON.stringify(snapshot),
    }), env, ctx);
    assert.equal(published.status, 201);

    const complete = await worker.fetch(new Request("http://localhost/api/analyze"), env, ctx);
    const state = await complete.json();
    assert.equal(state.status, "complete");
    assert.equal(state.completed_run_id, "new-live-run");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
