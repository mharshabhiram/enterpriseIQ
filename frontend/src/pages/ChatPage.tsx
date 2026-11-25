import { useEffect, useRef, useState, type FormEvent } from "react";
import ReactMarkdown from "react-markdown";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, errorMessage } from "../api/client";
import { useApi } from "../api/hooks";
import type { ChatResponse, Conversation, ConversationDetail, Message } from "../api/types";
import { SourceCard } from "../components/Sources";
import { Empty, ErrorBanner, Spinner } from "../components/ui";

/** Turn "[S1]" markers into links that the renderer below shows as clickable citation chips. */
const withCitations = (text: string, messageId: string) =>
  text.replace(/\[S(\d+)\]/g, (_, n) => `[S${n}](#src-${messageId}-${n})`);

function jumpTo(anchor: string) {
  const el = document.getElementById(anchor);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
  el.classList.remove("flash");
  void el.offsetWidth; // restart the animation
  el.classList.add("flash");
}

export function AssistantMessage({ message }: { message: Message }) {
  return (
    <div className="msg assistant stack">
      <ReactMarkdown
        components={{
          a: ({ href, children }) =>
            href?.startsWith("#src-")
              ? <button className="cite" type="button" onClick={() => jumpTo(href.slice(1))}>{children}</button>
              : <a href={href} target="_blank" rel="noreferrer">{children}</a>,
        }}
      >{withCitations(message.content, message.id)}</ReactMarkdown>
      {message.sources.length > 0 && (
        <div className="stack" style={{ gap: 8 }}>
          <div className="eyebrow">Sources</div>
          {message.sources.map((s) => <SourceCard key={s.source_number} source={s} id={`src-${message.id}-${s.source_number}`} />)}
        </div>
      )}
    </div>
  );
}

export function ChatPage() {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const list = useApi<Conversation[]>("/api/conversations");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const justCreated = useRef<string | null>(null);

  useEffect(() => {
    setError(null);
    if (!conversationId) { setMessages([]); return; }
    if (justCreated.current === conversationId) return; // already have the messages locally
    api<ConversationDetail>(`/api/conversations/${conversationId}`).then((c) => setMessages(c.messages)).catch((e) => setError(errorMessage(e)));
  }, [conversationId]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy]);

  const send = async (e?: FormEvent) => {
    e?.preventDefault();
    const text = input.trim();
    if (text.length < 2 || busy) return;
    setInput("");
    setError(null);
    setBusy(true);
    setMessages((m) => [...m, { id: `tmp-${Date.now()}`, conversation_id: conversationId ?? "", role: "user", content: text, created_at: new Date().toISOString(), sources: [] }]);
    try {
      const res = await api<ChatResponse>("/api/chat", { method: "POST", json: { message: text, conversation_id: conversationId ?? null } });
      setMessages((m) => [...m, res.message]);
      if (!conversationId) {
        justCreated.current = res.conversation_id;
        navigate(`/chat/${res.conversation_id}`, { replace: true });
      }
      void list.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const regenerate = async () => {
    if (!conversationId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api<ChatResponse>(`/api/conversations/${conversationId}/regenerate`, { method: "POST" });
      setMessages((m) => [...(m[m.length - 1]?.role === "assistant" ? m.slice(0, -1) : m), res.message]);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    try { await api(`/api/conversations/${id}`, { method: "DELETE" }); } catch (e) { setError(errorMessage(e)); }
    void list.reload();
    if (id === conversationId) navigate("/chat");
  };

  return (
    <div className="chat">
      <nav className="chat-list stack" aria-label="Conversations">
        <Link className="btn accent sm" to="/chat">New conversation</Link>
        {list.data?.map((c) => (
          <div className="row" key={c.id} style={{ flexWrap: "nowrap", gap: 4 }}>
            <Link className={`chat-item${c.id === conversationId ? " active" : ""}`} to={`/chat/${c.id}`}>{c.title}</Link>
            <button className="btn ghost sm" aria-label={`Delete ${c.title}`} onClick={() => remove(c.id)}>×</button>
          </div>
        ))}
      </nav>
      <section className="stack" style={{ minHeight: 0 }}>
        <div className="thread">
          {messages.length === 0 && !busy && (
            <Empty>
              <h2>Ask your documents</h2>
              <p>Answers come from a local model and only use documents you're allowed to see.</p>
            </Empty>
          )}
          {messages.map((m) => (m.role === "user" ? <div key={m.id} className="msg user">{m.content}</div> : <AssistantMessage key={m.id} message={m} />))}
          {busy && <div className="msg assistant row"><Spinner /> <span className="muted">Searching your documents and drafting an answer…</span></div>}
          <div ref={endRef} />
        </div>
        <ErrorBanner message={error} />
        <form className="composer" onSubmit={send}>
          <textarea aria-label="Your question" rows={2} placeholder="e.g. How many days of annual leave do I get?"
            value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }} />
          <div className="stack" style={{ gap: 6 }}>
            <button className="btn accent" type="submit" disabled={busy || input.trim().length < 2}>Send</button>
            {conversationId && messages.some((m) => m.role === "assistant") && (
              <button className="btn ghost sm" type="button" disabled={busy} onClick={regenerate}>Regenerate</button>
            )}
          </div>
        </form>
      </section>
    </div>
  );
}
