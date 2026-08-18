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
  prepare(sql) {
    const db = this;
    return {
      sql,
      args: [],
      bind(...args) { this.args = args; return this; },
      async first() { return sql.includes("SELECT payload_json") && db.payload ? { payload_json: db.payload } : null; },
    };
  }
  async batch(statements) {
    for (const statement of statements) {
      if (statement.sql.includes("INSERT INTO analysis_snapshots")) this.payload = statement.args[3];
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
  assert.match(html, /실행 시점의 투자 판단/);
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
