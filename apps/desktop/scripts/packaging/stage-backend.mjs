// Stages a self-contained Python runtime + the backend source for packaging (Windows x64).
//
//   build/backend-stage/python/   embeddable CPython 3.12 with the runtime dependencies in Lib/site-packages
//   build/backend-stage/src/      the `backend` package (no tests)
//
// electron-builder copies both into resources/backend/. Nothing is installed on the machine: wheels are
// downloaded for the target platform and unpacked into the staging directory only.
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PYTHON_VERSION = "3.12.10";
// Pinned from the first verified download of this exact file. The authoritative check is the Authenticode
// signature on python.exe below; this hash additionally detects a changed or corrupted download.
const EMBED_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3";
const EMBED_URL = `https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-embed-amd64.zip`;

// Runtime only: the desktop app never runs the CLI (typer/rich) or the terminal UI (textual).
const RUNTIME_REQUIREMENTS = ["fastapi>=0.115,<1", "pydantic>=2.10,<3", "uvicorn[standard]>=0.34,<1"];

const here = dirname(fileURLToPath(import.meta.url));
const desktop = resolve(here, "..", "..");
const repoRoot = resolve(desktop, "..", "..");
const cacheDir = join(desktop, ".cache");
const stage = join(desktop, "build", "backend-stage");
const pythonDir = join(stage, "python");
const srcDir = join(stage, "src");
const hostPython = process.env.CHANGE_ASSURANCE_PYTHON || "python";

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: "inherit", shell: false, ...options });
  if (result.status !== 0) throw new Error(`${command} ${args.slice(0, 3).join(" ")} failed (exit ${result.status})`);
}

const sha256 = (file) => createHash("sha256").update(readFileSync(file)).digest("hex");

function directorySize(dir) {
  let total = 0;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    total += entry.isDirectory() ? directorySize(path) : statSync(path).size;
  }
  return total;
}

async function downloadEmbeddable() {
  mkdirSync(cacheDir, { recursive: true });
  const zip = join(cacheDir, `python-${PYTHON_VERSION}-embed-amd64.zip`);
  if (!existsSync(zip)) {
    console.log(`Downloading ${EMBED_URL}`);
    const response = await fetch(EMBED_URL);
    if (!response.ok) throw new Error(`Download failed: HTTP ${response.status}`);
    writeFileSync(zip, Buffer.from(await response.arrayBuffer()));
  }
  const digest = sha256(zip);
  console.log(`Embeddable zip SHA-256: ${digest}`);
  if (EMBED_SHA256 && digest !== EMBED_SHA256) throw new Error("Embeddable Python zip does not match the pinned SHA-256.");
  return zip;
}

/** python.exe must be signed by the Python Software Foundation; a tampered download fails here. */
function verifyPythonSignature(exe) {
  const script = `$s = Get-AuthenticodeSignature -LiteralPath '${exe}'; "$($s.Status)|$($s.SignerCertificate.Subject)"`;
  const result = spawnSync("powershell", ["-NoProfile", "-Command", script], { encoding: "utf8" });
  const [status, subject = ""] = (result.stdout ?? "").trim().split("|");
  if (status !== "Valid" || !/Python Software Foundation/i.test(subject)) {
    throw new Error(`python.exe signature check failed: status=${status} subject=${subject}`);
  }
  console.log(`python.exe signature: ${status} (${subject.split(",")[0]})`);
}

function configureEmbeddable() {
  const pth = readdirSync(pythonDir).find((name) => name.endsWith("._pth"));
  if (!pth) throw new Error("Embeddable Python ._pth file not found.");
  // The embeddable build ignores PYTHONPATH; search paths live in this file. `..\\src` is resources/backend/src.
  const zipName = pth.replace("._pth", ".zip");
  writeFileSync(join(pythonDir, pth), [zipName, ".", "Lib\\site-packages", "..\\src", "", "import site", ""].join("\r\n"));
}

function installDependencies() {
  const target = join(pythonDir, "Lib", "site-packages");
  mkdirSync(target, { recursive: true });
  run(hostPython, [
    "-m", "pip", "install",
    "--target", target,
    "--only-binary=:all:",
    "--platform", "win_amd64",
    "--python-version", "3.12",
    "--implementation", "cp",
    "--no-compile",
    "--disable-pip-version-check",
    ...RUNTIME_REQUIREMENTS,
  ]);
  // Not needed at runtime; keeps the package small and free of stray executables.
  for (const name of readdirSync(target)) {
    if (name === "bin" || name === "__pycache__") rmSync(join(target, name), { recursive: true, force: true });
  }
}

function copyBackend() {
  cpSync(join(repoRoot, "backend"), join(srcDir, "backend"), {
    recursive: true,
    filter: (source) => {
      const name = source.replace(/\\/g, "/");
      return !/\/tests(\/|$)|__pycache__|\.pyc$|\.md$/.test(name);
    },
  });
}

function smokeTest() {
  const exe = join(pythonDir, "python.exe");
  const code = "import backend.app.main, fastapi, pydantic, uvicorn, sqlite3; print('ok')";
  // Importing the backend creates its database and API token under CHANGE_ASSURANCE_DB_PATH (default: the working
  // directory). Point it at a throwaway directory outside the stage so nothing runtime-generated is ever packaged.
  const scratch = mkdtempSync(join(tmpdir(), "ca-stage-smoke-"));
  try {
    const result = spawnSync(exe, ["-B", "-s", "-c", code], {
      cwd: srcDir,
      encoding: "utf8",
      env: { PATH: "", PYTHONDONTWRITEBYTECODE: "1", CHANGE_ASSURANCE_DB_PATH: join(scratch, "smoke.sqlite3") },
    });
    if (result.status !== 0 || !result.stdout.includes("ok")) {
      throw new Error(`Bundled Python import check failed:\n${result.stderr}`);
    }
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
  console.log("Bundled Python imports the backend and its dependencies.");
}

/** Fail loudly if anything that must never ship (tokens, databases, env files, tests, caches) is in the stage. */
function auditStage(dir = stage, found = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    const rel = path.slice(stage.length + 1).replace(/\\/g, "/");
    if (/(^|\/)(api_token|\.env[^/]*|\.change-assurance|tests|__pycache__)(\/|$)|\.(sqlite3?|db|pyc|pdf)$/i.test(rel)) found.push(rel);
    else if (entry.isDirectory()) auditStage(path, found);
  }
  if (dir === stage && found.length > 0) {
    throw new Error(`Staged backend contains files that must not ship:\n  ${found.join("\n  ")}`);
  }
  return found;
}

async function main() {
  if (process.platform !== "win32") throw new Error("Backend staging currently supports Windows x64 only.");
  rmSync(stage, { recursive: true, force: true });
  mkdirSync(stage, { recursive: true });

  const zip = await downloadEmbeddable();
  mkdirSync(pythonDir, { recursive: true });
  run("powershell", [
    "-NoProfile",
    "-Command",
    `Expand-Archive -LiteralPath '${zip}' -DestinationPath '${pythonDir}' -Force`,
  ]);
  verifyPythonSignature(join(pythonDir, "python.exe"));
  configureEmbeddable();
  installDependencies();
  copyBackend();
  smokeTest();
  auditStage();
  console.log("Stage audit: no tokens, databases, env files, tests or caches.");

  const manifest = {
    python: PYTHON_VERSION,
    embedSha256: sha256(zip),
    pythonExeSha256: sha256(join(pythonDir, "python.exe")),
    requirements: RUNTIME_REQUIREMENTS,
    sizeBytes: directorySize(stage),
  };
  writeFileSync(join(stage, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
  console.log(`Staged backend: ${(manifest.sizeBytes / 1_048_576).toFixed(1)} MB at ${stage}`);
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
