interface CopyToClipboardOptions {
  container?: HTMLElement | null;
}

export async function copyToClipboard(
  text: string,
  options: CopyToClipboardOptions = {},
): Promise<boolean> {
  const container = options.container;
  const debugInfo = {
    length: text?.length ?? 0,
    trimmedLength: text?.trim().length ?? 0,
    isSecureContext:
      typeof window !== "undefined" ? window.isSecureContext : false,
    hasClipboardApi:
      typeof navigator !== "undefined" && !!navigator.clipboard?.writeText,
    containerTag: container?.tagName ?? null,
    containerInBody:
      typeof document !== "undefined" &&
      !!container &&
      document.body.contains(container),
  };

  if (!text) {
    console.debug("[clipboard] empty text payload", debugInfo);
    return false;
  }

  console.debug("[clipboard] copy request", debugInfo);

  if (
    typeof navigator !== "undefined" &&
    navigator.clipboard &&
    window.isSecureContext
  ) {
    try {
      await navigator.clipboard.writeText(text);
      console.info("[clipboard] copied via Clipboard API", debugInfo);
      return true;
    } catch (err) {
      console.warn(
        "[clipboard] Clipboard API failed, falling back:",
        err,
        debugInfo,
      );
    }
  }

  const fallbackOk = fallbackCopy(text, container);
  if (fallbackOk) {
    console.info(
      "[clipboard] fallback succeeded via document.execCommand('copy')",
      debugInfo,
    );
  } else {
    console.warn(
      "[clipboard] fallback failed via document.execCommand('copy')",
      debugInfo,
    );
  }
  return fallbackOk;
}

function fallbackCopy(text: string, container?: HTMLElement | null): boolean {
  if (typeof document === "undefined") return false;
  const target =
    container && document.body.contains(container) ? container : document.body;
  if (!target) return false;

  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.setAttribute("readonly", "");
  Object.assign(textArea.style, {
    position: "fixed",
    top: "0",
    left: "0",
    width: "1px",
    height: "1px",
    opacity: "0",
    pointerEvents: "none",
    zIndex: "-1",
  });

  target.appendChild(textArea);
  textArea.focus();
  textArea.select();
  textArea.setSelectionRange(0, text.length);

  try {
    return document.execCommand("copy");
  } catch (err) {
    console.error("Fallback copy failed:", err);
    return false;
  } finally {
    if (textArea.parentNode) {
      textArea.parentNode.removeChild(textArea);
    }
  }
}
