import test from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import { Buffer } from "node:buffer";
import { build } from "vite";

test("production entry stays within its loading budget and defers code grammars", async () => {
  const result = await build({
    root: fileURLToPath(new URL("../../", import.meta.url)),
    logLevel: "error",
    build: { write: false },
  });
  const chunks = result.output.filter((item) => item.type === "chunk");
  const initial = new Set();
  const visit = (chunk) => {
    if (initial.has(chunk)) return;
    initial.add(chunk);
    chunk.imports.forEach((file) => visit(chunks.find((item) => item.fileName === file)));
  };
  chunks.filter((chunk) => chunk.isEntry).forEach(visit);
  const initialGzip = [...initial].reduce((sum, chunk) => sum + gzipSync(chunk.code).length, 0);
  assert.ok(
    initialGzip < 300_000,
    `Initial JavaScript gzip: ${initialGzip} bytes (budget: 300000)`,
  );
  for (const chunk of chunks) {
    assert.ok(
      Buffer.byteLength(chunk.code) < 500_000,
      `Oversized JavaScript chunk: ${chunk.fileName}`,
    );
  }
  for (const chunk of initial) {
    assert.ok(
      !Object.keys(chunk.modules).some((id) => /highlight\.js\/(?:es|lib)\/languages\//.test(id)),
      `Language grammars loaded by entry: ${chunk.fileName}`,
    );
  }
  assert.ok(
    chunks.some(
      (chunk) =>
        !initial.has(chunk) &&
        Object.keys(chunk.modules).some((id) => id.endsWith("highlight.js/es/languages/python.js")),
    ),
  );
});
