"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const { saveJson, safeJsonName, selectFolder, MAX_EXPORT_BYTES } = require("../native-dialogs.cjs");

function harness(dialogResult) {
  const calls = { dialog: [], writes: [] };
  return {
    calls,
    deps: {
      window: {},
      dialog: { showSaveDialog: async (...a) => (calls.dialog.push(a), dialogResult), showOpenDialog: async () => dialogResult },
      writeFile: async (...a) => void calls.writes.push(a),
    },
  };
}

test("writes exactly the given content to the path the user picked", async () => {
  const h = harness({ canceled: false, filePath: "C:\\Users\\me\\out.json" });
  const result = await saveJson(h.deps, { suggestedName: "passport-1.json", content: '{"a":1}' });
  assert.deepEqual(result, { ok: true, path: "C:\\Users\\me\\out.json" });
  assert.deepEqual(h.calls.writes, [["C:\\Users\\me\\out.json", '{"a":1}', "utf8"]]);
});

test("cancel writes nothing and reports a null path", async () => {
  const h = harness({ canceled: true, filePath: undefined });
  assert.deepEqual(await saveJson(h.deps, { suggestedName: "x.json", content: "{}" }), { ok: true, path: null });
  assert.equal(h.calls.writes.length, 0);
});

test("adds a .json extension when the user drops it", async () => {
  const h = harness({ canceled: false, filePath: "C:\\out" });
  const result = await saveJson(h.deps, { suggestedName: "x", content: "{}" });
  assert.equal(result.path, "C:\\out.json");
});

test("rejects missing or non-string content and oversized content before showing a dialog", async () => {
  const h = harness({ canceled: false, filePath: "C:\\x.json" });
  for (const bad of [undefined, null, "str", {}, { content: 5 }]) {
    const r = await saveJson(h.deps, bad);
    assert.equal(r.ok, false);
    assert.equal(r.error.code, "invalid_request");
  }
  const big = await saveJson(h.deps, { suggestedName: "x", content: "a".repeat(MAX_EXPORT_BYTES + 1) });
  assert.equal(big.error.code, "too_large");
  assert.equal(h.calls.dialog.length, 0);
  assert.equal(h.calls.writes.length, 0);
});

test("suggested names are reduced to a plain json file name", () => {
  assert.equal(safeJsonName("..\\..\\evil\\a:b?.json"), "a_b_.json");
  assert.equal(safeJsonName("../../etc/passwd"), "passwd.json");
  assert.equal(safeJsonName(""), "export.json");
  assert.equal(safeJsonName(undefined), "export.json");
  assert.equal(safeJsonName(".hidden"), "hidden.json");
  assert.equal(safeJsonName("a".repeat(300)).length, 105);
});

test("the renderer can't choose the destination: the dialog is opened with only a file name", async () => {
  const h = harness({ canceled: true });
  await saveJson(h.deps, { suggestedName: "C:\\Windows\\System32\\x.json", content: "{}", path: "C:\\Windows\\evil.json" });
  const options = h.calls.dialog[0][1];
  assert.equal(options.defaultPath, "x.json");
  assert.equal(h.calls.writes.length, 0);
});

test("folder picker still returns null on cancel", async () => {
  const h = harness({ canceled: true, filePaths: [] });
  assert.deepEqual(await selectFolder(h.deps), { ok: true, path: null });
});
