const KEY = "offerlens.client-id";
let memoryId: string | null = null;

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join("");
}

/** Anonymous ID for this browser. Offers are only visible to the browser that created them. */
export function getClientId(): string {
  try {
    const existing = localStorage.getItem(KEY);
    if (existing) return existing;
    const id = newId();
    localStorage.setItem(KEY, id);
    return id;
  } catch {
    // Storage blocked (private mode etc.): keep an ID for this tab's lifetime
    memoryId ??= newId();
    return memoryId;
  }
}
