// Regresión del bug "API 422 en /properties" (2026-09-24).
// El cliente fetch enviaba cuerpos JSON sin `Content-Type: application/json`
// (el navegador usa text/plain) y FastAPI respondía 422 `model_attributes_type`.
// backend() debe fijar la cabecera solo para cuerpos string, sin tocar FormData.
import assert from "node:assert";
import { execSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const bundle = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "client-test-")), "client.cjs");

execSync(
  `node ./node_modules/esbuild/bin/esbuild --bundle --format=cjs --platform=node ${JSON.stringify(path.join(root, "src/api/client.ts"))} --outfile=${JSON.stringify(bundle)} --log-level=error`,
  { cwd: root, stdio: "inherit" },
);
const { backend, ApiError } = await import(bundle);

let lastInit;
globalThis.fetch = async (_url, init) => {
  lastInit = init;
  return { ok: true, json: async () => ({}) };
};

// 1. Cuerpo JSON string sin cabeceras -> fija application/json
await backend("/properties", { method: "POST", body: JSON.stringify({ title: "X" }) });
assert.strictEqual(
  new Headers(lastInit.headers).get("Content-Type"),
  "application/json",
  "el cuerpo JSON debe viajar con Content-Type: application/json",
);

// 2. Respeta un Content-Type explícito del llamador
await backend("/x", {
  method: "POST",
  headers: { "Content-Type": "text/csv" },
  body: "a,b",
});
assert.strictEqual(new Headers(lastInit.headers).get("Content-Type"), "text/csv");

// 3. FormData (subida de imágenes) -> no impone cabecera JSON (rompería el boundary)
const fd = new FormData();
fd.append("file", new Blob(["img"]), "foto.png");
await backend("/properties/1/images", { method: "POST", body: fd });
assert.strictEqual(
  new Headers(lastInit.headers).get("Content-Type"),
  null,
  "FormData gestiona su propio Content-Type con boundary",
);

// 4. GET sin cuerpo -> no añade cabecera innecesaria
await backend("/properties");
assert.strictEqual(new Headers(lastInit.headers).get("Content-Type"), null);

// 5. El formato de error se mantiene: "API {status} en {path}"
globalThis.fetch = async () => ({ ok: false, status: 422, text: async () => '{"detail":[]}' });
await assert.rejects(backend("/properties", { method: "POST", body: "{}" }), (e) => {
  assert.ok(e instanceof ApiError);
  assert.match(e.message, /^API 422 en \/properties: /);
  return true;
});

console.log("client-headers: 5/5 OK");
