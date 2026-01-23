type WSHandlers = {
  onOpen?: (event: Event) => void;
  onMessage?: (event: MessageEvent) => void;
  onClose?: (event: CloseEvent) => void;
  onError?: (event: Event) => void;
};

export const connectChatWS = (handlers: WSHandlers = {}) => {
  const base = window.location.origin.replace("http", "ws");
  const ws = new WebSocket(`${base}/ws`);
  if (handlers.onOpen) ws.addEventListener("open", handlers.onOpen);
  if (handlers.onMessage) ws.addEventListener("message", handlers.onMessage);
  if (handlers.onClose) ws.addEventListener("close", handlers.onClose);
  if (handlers.onError) ws.addEventListener("error", handlers.onError);
  return ws;
};
