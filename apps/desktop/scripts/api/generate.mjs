// Generates src/lib/api/generated/schema.ts from the root openapi.json snapshot.
// `--check` regenerates in memory and exits nonzero when the committed output differs.
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const specPath = resolve(here, "..", "..", "..", "..", "openapi.json");
const outDir = resolve(here, "..", "..", "src", "lib", "api", "generated");
const schemaPath = resolve(outDir, "schema.ts");
const hashPath = resolve(outDir, "OPENAPI_SHA256");

const banner = "// Generated from the root openapi.json by scripts/api/generate.mjs. Do not edit.\n";
const ast = await openapiTS(pathToFileURL(specPath));
const output = banner + astToString(ast).replace(/\r\n/g, "\n");
const hash = createHash("sha256").update(readFileSync(specPath)).digest("hex") + "\n";

function safeRead(path) {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return null;
  }
}

if (process.argv.includes("--check")) {
  const drift = safeRead(schemaPath) !== output || safeRead(hashPath) !== hash;
  if (drift) {
    console.error("Generated API types are out of date. Run `npm run api:generate`.");
    process.exit(1);
  }
  console.log("Generated API types match openapi.json.");
} else {
  mkdirSync(outDir, { recursive: true });
  for (const [path, content] of [
    [schemaPath, output],
    [hashPath, hash],
  ]) {
    writeFileSync(path + ".tmp", content);
    renameSync(path + ".tmp", path);
  }
  console.log(`Wrote ${schemaPath}`);
}
