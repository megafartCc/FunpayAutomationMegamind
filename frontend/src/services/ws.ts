type WSHandlers = {
  onOpen?: (event: Event) => void;
  onMessage?: (event: MessageEvent) => void;
  onClose?: (event: CloseEvent) => void;
  onError?: (event: Event) => void;
};

export const connectChatWS = (handlers: WSHandlers = {}, keyId?: number | string | null) => {
  const base = window.location.origin.replace("http", "ws");
  const url = new URL(`${base}/ws`);
  if (keyId !== undefined && keyId !== null && keyId !== "all") {
    url.searchParams.set("key_id", String(keyId));
  }
  const ws = new WebSocket(url.toString());
  if (handlers.onOpen) ws.addEventListener("open", handlers.onOpen);
  if (handlers.onMessage) ws.addEventListener("message", handlers.onMessage);
  if (handlers.onClose) ws.addEventListener("close", handlers.onClose);
  if (handlers.onError) ws.addEventListener("error", handlers.onError);
  return ws;
};
