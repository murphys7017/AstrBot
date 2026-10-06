import { defineAsyncComponent } from "vue";
import { setupMonaco } from "@/plugins/monaco";

/** Drop-in Monaco editor that keeps the editor bundle out of the entry chunk. */
export const LazyMonacoEditor = defineAsyncComponent(async () => {
  const { VueMonacoEditor, loader } = await import(
    "@guolao/vue-monaco-editor"
  );
  await setupMonaco(loader);
  return VueMonacoEditor;
});
