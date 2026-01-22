import React from "react";
import { Chat, ChatMessage } from "../../types";

const ChatPanel: React.FC<{
  chats: Chat[];
  chatSearch: string;
  selectedChatId: number | null;
  chatTitle: string;
  chatSubtitle: string;
  messages: ChatMessage[];
  onSearchChange: (value: string) => void;
  onRefresh: () => void;
  onLoadHistory: () => void;
  onSelectChat: (chatId: number) => void;
  onSendMessage: (message: string) => void;
}> = ({
  chats,
  chatSearch,
  selectedChatId,
  chatTitle,
  chatSubtitle,
  messages,
  onSearchChange,
  onRefresh,
  onLoadHistory,
  onSelectChat,
  onSendMessage,
}) => {
  const filtered = chats.filter((chat) => {
    const name = chat.name?.toLowerCase() || "";
    const last = chat.last_message_text?.toLowerCase() || "";
    const query = chatSearch.trim().toLowerCase();
    return !query || name.includes(query) || last.includes(query);
  });

  const [draft, setDraft] = React.useState("");

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const value = draft.trim();
    if (!value) return;
    onSendMessage(value);
    setDraft("");
  };

  return (
    <div className="panel grid gap-6 lg:grid-cols-[280px_1fr]">
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <input
            className="input"
            placeholder="Поиск чатов"
            value={chatSearch}
            onChange={(event) => onSearchChange(event.target.value)}
          />
          <button className="btn-ghost" type="button" onClick={onRefresh}>
            Обновить
          </button>
        </div>
        <div className="space-y-2 max-h-[460px] overflow-y-auto pr-1">
          {filtered.length ? (
            filtered.map((chat) => (
              <button
                key={chat.id}
                className={`w-full rounded-xl border border-slate-800 p-3 text-left transition ${
                  chat.id === selectedChatId ? "bg-slate-900" : "hover:border-amber-500/40"
                }`}
                onClick={() => onSelectChat(chat.id)}
              >
                <div className="flex items-center justify-between">
                  <div className="text-sm font-semibold">{chat.name || "Без имени"}</div>
                  <span className="text-xs text-slate-400">{chat.last_message_time || chat.time}</span>
                </div>
                <p className="mt-2 text-xs text-slate-400">{chat.last_message_text}</p>
                {chat.unread ? (
                  <span className="mt-2 inline-block rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] text-amber-300">
                    новое
                  </span>
                ) : null}
              </button>
            ))
          ) : (
            <div className="text-sm text-slate-400">Чаты не найдены.</div>
          )}
        </div>
      </div>
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold">{chatTitle}</h3>
            <p className="text-xs text-slate-400">{chatSubtitle}</p>
          </div>
          <button className="btn-ghost" type="button" onClick={onLoadHistory}>
            Загрузить историю
          </button>
        </div>
        <div className="flex-1 space-y-3 overflow-y-auto rounded-xl border border-slate-800 bg-slate-950/60 p-4">
          {messages.length ? (
            messages.map((message) => (
              <div
                key={message.id}
                className={`rounded-xl border border-slate-800 p-3 ${message.by_bot ? "bg-amber-500/10" : "bg-slate-900"}`}
              >
                <div className="text-xs text-slate-400">
                  {[message.author || "Неизвестно", message.type, message.sent_time ? `• ${message.sent_time}` : ""]
                    .filter(Boolean)
                    .join(" ")}
                </div>
                <p className="mt-2 text-sm">{message.text || "(без текста)"}</p>
                {message.image_link ? (
                  <a
                    className="mt-2 inline-block text-xs text-amber-300"
                    href={message.image_link}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Открыть изображение
                  </a>
                ) : null}
              </div>
            ))
          ) : (
            <div className="text-sm text-slate-400">Выберите чат, чтобы загрузить историю.</div>
          )}
        </div>
        <form className="flex gap-2" onSubmit={handleSubmit}>
          <textarea
            className="textarea flex-1"
            rows={2}
            placeholder="Введите сообщение..."
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <button className="btn" type="submit">
            Отправить
          </button>
        </form>
      </div>
    </div>
  );
};

export default ChatPanel;
