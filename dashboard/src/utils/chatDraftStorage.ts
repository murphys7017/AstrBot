const PREFIX = "astrbot.chat.draft.";

export function readChatDraft(key: string, storage?: Storage): string {
  try {
    return (storage ?? globalThis.localStorage)?.getItem(PREFIX + key) || "";
  } catch {
    return "";
  }
}

export function writeChatDraft(key: string, draft: string, storage?: Storage): void {
  try {
    const target = storage ?? globalThis.localStorage;
    if (draft) target?.setItem(PREFIX + key, draft);
    else target?.removeItem(PREFIX + key);
  } catch {
    // Unavailable or full storage must not prevent composing or sending.
  }
}
