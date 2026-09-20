"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const { buildRepairPage, MAX_AUTO_RETRIES } = require("../repair-page.cjs");

const decode = (url) => decodeURIComponent(url.slice(url.indexOf(",") + 1));

test("the page is a self-contained data URL with a locked-down policy and no script", () => {
  const url = buildRepairPage({ retryUrl: "app://app/", reason: "The app's interface didn't load." });
  assert.match(url, /^data:text\/html;charset=utf-8,/);
  const html = decode(url);
  assert.match(html, /default-src 'none'/);
  assert.ok(!/<script/i.test(html));
  assert.match(html, /http-equiv="refresh" content="3;url=app:\/\/app\/"/);
});

test("interpolated values are escaped, so a hostile reason or URL can't inject markup", () => {
  const html = decode(buildRepairPage({ retryUrl: 'app://a/"><script>x</script>', reason: "<img src=x onerror=alert(1)>" }));
  assert.ok(!/<script>x/.test(html));
  assert.ok(!/<img src=x/.test(html));
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
});

test("retries are bounded: past the limit there is no refresh and the message says so", () => {
  const html = decode(buildRepairPage({ retryUrl: "app://app/", reason: "r", attempt: MAX_AUTO_RETRIES + 1 }));
  assert.ok(!/http-equiv="refresh"/.test(html));
  assert.match(html, /Automatic retries stopped/);
  assert.match(decode(buildRepairPage({ retryUrl: "app://app/", reason: "r", attempt: 2 })), /attempt 2 of 10/);
});

test("the page states the problem without exposing a path or token", () => {
  const html = decode(buildRepairPage({ retryUrl: "app://app/", reason: "The app's interface stopped unexpectedly." }));
  assert.match(html, /role="alert"/);
  assert.ok(!/C:\|token|Bearer/i.test(html));
});
