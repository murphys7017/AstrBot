import type { loader } from "@guolao/vue-monaco-editor";

type MonacoLoader = typeof loader;

let monacoSetupPromise: Promise<void> | null = null;

/** Load Monaco only when an editor is rendered. */
export function setupMonaco(loaderInstance: MonacoLoader): Promise<void> {
  if (!monacoSetupPromise) {
    monacoSetupPromise = (async () => {
      const monaco = await import("monaco-editor");
      const workerUrl = (fileName: string) =>
        new URL(
          `${import.meta.env.BASE_URL}monaco-workers/${fileName}`,
          window.location.href,
        ).toString();
      const createWorker = (fileName: string) =>
        new Worker(workerUrl(fileName), { type: "module" });

      (self as any).MonacoEnvironment = {
        getWorker(_: string, label: string) {
          if (label === "json") return createWorker("json.worker.js");
          if (label === "css" || label === "scss" || label === "less") {
            return createWorker("css.worker.js");
          }
          if (label === "html" || label === "handlebars" || label === "razor") {
            return createWorker("html.worker.js");
          }
          if (label === "typescript" || label === "javascript") {
            return createWorker("ts.worker.js");
          }
          return createWorker("editor.worker.js");
        },
      };

      loaderInstance.config({ monaco });
    })();
  }

  return monacoSetupPromise;
}
