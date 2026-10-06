/** Assemble a locale's JSON modules into the nested translation shape. */
export function assembleLocale(modules: Record<string, unknown>) {
  const locale: Record<string, any> = {};

  for (const [modulePath, value] of Object.entries(modules)) {
    const relativePath = modulePath
      .replace(/^\.\//, "")
      .replace(/\.json$/, "");
    const segments = relativePath.split("/");
    const leaf = segments.pop();
    if (!leaf) continue;

    let target = locale;
    for (const segment of segments) {
      if (!target[segment] || typeof target[segment] !== "object") {
        target[segment] = {};
      }
      target = target[segment];
    }
    target[leaf] = value;
  }

  return locale;
}
