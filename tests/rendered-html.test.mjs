import assert from "node:assert/strict";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the AI fund manager snapshot", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, /AI Fund Manager/);
  assert.match(html, /예측하고/);
  assert.match(html, /GROQ 4 \/ 4/);
  assert.match(html, /LG전자/);
  assert.match(html, /BUY/);
  assert.match(html, /openai\/gpt-oss-120b/);
  assert.doesNotMatch(html, /Your site is taking shape|Building your site/);
});

test("renders evidence and risk disclosures", async () => {
  const response = await render();
  const html = await response.text();
  assert.match(html, /미래 누출 검사/);
  assert.match(html, /FAIL CLOSED/);
  assert.match(html, /수익을 보장하지 않고 주문은 자동 전송되지 않습니다/);
  assert.match(html, /ffc9dd1ad3264a0dbfecf872e4fafa49/);
});
