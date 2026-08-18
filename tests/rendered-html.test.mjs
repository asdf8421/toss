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
  assert.match(html, /오늘의 투자 판단/);
  assert.match(html, /Groq 4 \/ 4/);
  assert.match(html, /LG전자/);
  assert.match(html, /24주 매수/);
  assert.match(html, /openai\/gpt-oss-120b/);
  assert.doesNotMatch(html, /Your site is taking shape|Building your site/);
});

test("renders evidence and risk disclosures", async () => {
  const response = await render();
  const html = await response.text();
  assert.match(html, /AI가 숫자를 만들지 않습니다/);
  assert.match(html, /API 실패 시 판단 중단/);
  assert.match(html, /자동 주문 기능 없음/);
  assert.match(html, /ffc9dd1ad3/);
});
