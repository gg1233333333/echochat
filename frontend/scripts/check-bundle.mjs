import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";

const forbidden = ["api.deepseek.com", "echochat-build-secret-sentinel"];
async function check(directory) {
  for (const item of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, item.name);
    if (item.isDirectory()) await check(path);
    else if (/\.(js|mjs|html)$/.test(item.name)) {
      const text = await readFile(path, "utf8");
      for (const value of forbidden) {
        if (text.includes(value)) throw new Error(`Forbidden model credential/URL in ${path}`);
      }
    }
  }
}
await check("dist");
console.log("Browser bundle contains no direct DeepSeek URL or build secret sentinel.");
