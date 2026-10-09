import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { APPCONTAINER_LABEL, NONE_LINE, NOT_OBSERVED, REDUCED_LABEL, REDUCED_LINE, boundaryLine, boundaryStatus, checkBoundaryStatus, workspaceInfo } from "./boundary.ts";

const source = readFileSync(new URL("../../../../backend/app/core/boundary_text.py", import.meta.url), "utf8");
/** Python's adjacent string literals joined, so a wrapped line compares as one string. */
const flat = source.replace(/"\s*\n\s*"/g, "");

test("labels and fixed lines match backend/app/core/boundary_text.py", () => {
  assert.match(source, new RegExp(`APPCONTAINER_LABEL = "${APPCONTAINER_LABEL}"`));
  assert.match(source, new RegExp(`REDUCED_LABEL = "${REDUCED_LABEL}"`));
  assert.ok(flat.includes(NOT_OBSERVED), "not-observed line drifted");
  assert.ok(flat.includes(NONE_LINE), "none line drifted");
  const reducedTail = REDUCED_LINE.slice(`Boundary: ${REDUCED_LABEL} `.length);
  assert.ok(flat.includes(reducedTail), "reduced-token line drifted");
  for (const fragment of ["capabilities: ", "integrity low", "Job verified", "Job NOT verified", "workspace drive "]) {
    assert.ok(source.includes(fragment), `AppContainer detail "${fragment}" drifted`);
  }
});

const box = (extra: Record<string, unknown> = {}) => ({
  execution_boundary: { kind: "APPCONTAINER", capabilities: ["internetClient"], integrity_rid: "0x1000", job_verified: true, ...extra },
}) as never;

test("an AppContainer line names exactly what was verified", () => {
  assert.equal(boundaryLine(box({ workspace_drive: "Z:" })), "Boundary: AppContainer (capabilities: internetClient; integrity low; Job verified; workspace drive Z:)");
  assert.equal(boundaryLine(box({ capabilities: [], job_verified: false, integrity_rid: "0x2000" })), "Boundary: AppContainer (capabilities: none; integrity 0x2000; Job NOT verified)");
  assert.deepEqual(boundaryStatus(box()), { label: "AppContainer", tone: "ok" });
  assert.equal(boundaryStatus(box({ job_verified: false })).tone, "warn");
});

test("a reduced token is never called a sandbox, and a missing boundary is never implied", () => {
  const reduced = { execution_boundary: { kind: "RESTRICTED_TOKEN", job_verified: false } } as never;
  assert.equal(boundaryLine(reduced), REDUCED_LINE);
  assert.ok(boundaryLine(reduced).includes("not a sandbox"));
  assert.equal(boundaryStatus(reduced).tone, "warn");
  assert.equal(boundaryLine({ execution_boundary: null } as never), NOT_OBSERVED);
  assert.equal(boundaryLine({ execution_boundary: { kind: "NONE", job_verified: false } } as never), NONE_LINE);
  assert.equal(boundaryStatus({ execution_boundary: { kind: "NONE", job_verified: false } } as never).tone, "danger");
});

test("check-run and workspace states", () => {
  assert.equal(checkBoundaryStatus({ boundary: "APPCONTAINER" }).tone, "ok");
  assert.equal(checkBoundaryStatus({ boundary: "UNCONFINED" }).tone, "danger");
  assert.equal(checkBoundaryStatus({ boundary: null }).tone, "neutral");
  assert.equal(workspaceInfo("APPLIED").tone, "ok");
  assert.equal(workspaceInfo("APPLY_REFUSED").tone, "danger");
});
