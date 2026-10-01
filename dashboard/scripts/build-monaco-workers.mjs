import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import * as esbuild from "esbuild";

const dashboardRoot = dirname(fileURLToPath(import.meta.url));
const outputRoot = join(dashboardRoot, "..", "public", "monaco-workers");
const workerEntries = {
  "editor.worker.js": "monaco-editor/esm/vs/editor/editor.worker.js",
  "json.worker.js": "monaco-editor/esm/vs/language/json/json.worker.js",
  "css.worker.js": "monaco-editor/esm/vs/language/css/css.worker.js",
  "html.worker.js": "monaco-editor/esm/vs/language/html/html.worker.js",
  "ts.worker.js": "monaco-editor/esm/vs/language/typescript/ts.worker.js",
};

await mkdir(outputRoot, { recursive: true });

for (const [fileName, entryPoint] of Object.entries(workerEntries)) {
  const result = await esbuild.build({
    absWorkingDir: join(dashboardRoot, ".."),
    entryPoints: [entryPoint],
    bundle: true,
    format: "esm",
    platform: "browser",
    target: "es2020",
    write: false,
    logLevel: "silent",
  });
  await writeFile(join(outputRoot, fileName), result.outputFiles[0].contents);
}
