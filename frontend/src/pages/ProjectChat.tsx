import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ChatMessage,
  Conversation,
  createConversation,
  createConversationMessage,
  getConversationMessages,
  getLatestConversation,
  getProject,
  getProjectContext,
  listConversations,
  ProjectDetail,
  ProjectContext,
} from "../lib/api";

export default function ProjectChat() {
  const { projectId } = useParams<{ projectId: string }>();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversation, setActiveConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [isContextLoading, setIsContextLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [contextPreview, setContextPreview] = useState<ProjectContext | null>(null);
  const messageEndRef = useRef<HTMLDivElement>(null);

  const workspaceId = useMemo(() => project?.workspaces[0]?.id, [project]);

  const refreshConversations = async (id: string) => {
    const items = await listConversations(id);
    setConversations(items);
    return items;
  };

  useEffect(() => {
    if (!projectId) return;
    const id = projectId;
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      setError(null);
      try {
        const [projectResult, conversationResult] = await Promise.all([
          getProject(id),
          getLatestConversation(id),
        ]);
        if (cancelled) return;
        setProject(projectResult);
        const all = await refreshConversations(id);
        if (cancelled) return;
        const selected = conversationResult ?? all[0] ?? null;
        setActiveConversation(selected);
        if (selected) {
          setMessages(await getConversationMessages(selected.id));
        } else {
          setMessages([]);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load project chat");
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length]);

  const selectConversation = async (conversation: Conversation) => {
    setActiveConversation(conversation);
    setError(null);
    setContextPreview(null);
    try {
      setMessages(await getConversationMessages(conversation.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load messages");
    }
  };

  const startConversation = async () => {
    if (!projectId || !workspaceId) return;
    setError(null);
    try {
      const conversation = await createConversation(projectId, {
        workspace_id: workspaceId,
        title: "New conversation",
      });
      setActiveConversation(conversation);
      setMessages([]);
      setContextPreview(null);
      await refreshConversations(projectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start conversation");
    }
  };

  const viewContext = async () => {
    if (!projectId || !activeConversation) return;
    setIsContextLoading(true);
    setError(null);
    try {
      setContextPreview(await getProjectContext(projectId, activeConversation.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load project context");
    } finally {
      setIsContextLoading(false);
    }
  };

  const sendMessage = async (event: FormEvent) => {
    event.preventDefault();
    if (!projectId || !input.trim()) return;

    let conversation = activeConversation;
    setIsSending(true);
    setError(null);
    try {
      if (!conversation) {
        conversation = await createConversation(projectId, {
          workspace_id: workspaceId,
          title: "New conversation",
        });
        setActiveConversation(conversation);
      }

      const response = await createConversationMessage(conversation.id, {
        role: "user",
        content: input,
        metadata_json: { status: "submitted" },
      });
      setInput("");
      const nextMessages = [response.message, ...(response.assistant_message ? [response.assistant_message] : [])];
      setMessages((current) => [...current, ...nextMessages]);
      await refreshConversations(projectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Message was saved or sent incompletely");
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#030810] text-slate-100">
      <header className="border-b border-slate-800/70 bg-[#030810]/90">
        <div className="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-4 min-w-0">
            <Link to="/projects" className="text-sm font-mono font-bold text-slate-300 hover:text-cyan-400">
              Swarm<span className="text-cyan-400">Factory</span>
            </Link>
            <span className="truncate text-xs font-mono text-slate-500">
              {project?.name ?? "Project chat"}
            </span>
          </div>
          <Link to="/" className="text-[10px] font-mono text-slate-600 hover:text-slate-400">
            New generation job
          </Link>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-4 grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-4">
        <aside className="rounded-lg border border-slate-800 bg-[#070e17] min-h-[420px]">
          <div className="border-b border-slate-800 px-4 py-3 flex items-center justify-between">
            <span className="text-xs font-mono text-slate-300">Conversations</span>
            <button onClick={startConversation} className="text-[10px] font-mono text-cyan-400 hover:text-cyan-300">
              New
            </button>
          </div>
          {isLoading ? (
            <p className="p-4 text-xs font-mono text-slate-500">Loading...</p>
          ) : conversations.length === 0 ? (
            <p className="p-4 text-xs font-mono text-slate-500">No conversations yet.</p>
          ) : (
            <div className="divide-y divide-slate-800">
              {conversations.map((conversation) => (
                <button
                  key={conversation.id}
                  onClick={() => selectConversation(conversation)}
                  className={`w-full text-left px-4 py-3 transition-colors ${
                    activeConversation?.id === conversation.id ? "bg-cyan-950/30" : "hover:bg-slate-900/40"
                  }`}
                >
                  <p className="truncate text-xs font-mono text-slate-200">{conversation.title}</p>
                  <p className="mt-1 text-[10px] font-mono text-slate-600">
                    {new Date(conversation.updated_at).toLocaleString()}
                  </p>
                </button>
              ))}
            </div>
          )}
        </aside>

        <section className="rounded-lg border border-slate-800 bg-[#070e17] min-h-[calc(100vh-7rem)] flex flex-col">
          <div className="border-b border-slate-800 px-5 py-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h1 className="text-sm font-mono font-semibold text-slate-100">
                  {activeConversation?.title ?? "Project chat"}
                </h1>
                <p className="mt-1 text-xs font-mono text-slate-600">
                  Project memory active: recent chat context will be used for future agent instructions.
                </p>
              </div>
              {activeConversation && (
                <button
                  onClick={viewContext}
                  disabled={isContextLoading}
                  className="self-start rounded border border-slate-700 px-3 py-2 text-[10px] font-mono text-slate-300 hover:border-cyan-800 hover:text-cyan-300 disabled:opacity-40"
                >
                  {isContextLoading ? "Loading..." : "View Context"}
                </button>
              )}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
            {error && (
              <div className="rounded border border-red-800/60 bg-red-950/30 px-3 py-2 text-xs font-mono text-red-300">
                {error}
              </div>
            )}
            {contextPreview && (
              <ContextPreviewPanel context={contextPreview} onClose={() => setContextPreview(null)} />
            )}
            {!isLoading && messages.length === 0 && (
              <div className="h-full min-h-80 flex items-center justify-center text-center">
                <p className="max-w-sm text-xs font-mono text-slate-600">
                  Start the first conversation for this project. Your messages and agent replies will persist when you reopen it.
                </p>
              </div>
            )}
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
            <div ref={messageEndRef} />
          </div>

          <form onSubmit={sendMessage} className="border-t border-slate-800 p-4">
            <div className="flex flex-col sm:flex-row gap-3">
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                className="min-h-20 flex-1 resize-y rounded border border-slate-800 bg-[#030810] px-3 py-2 text-sm font-mono text-slate-100 outline-none focus:border-cyan-700"
                placeholder="Ask for an improvement, bug fix, feature, or explanation..."
              />
              <button
                disabled={isSending || !input.trim()}
                className="sm:w-32 rounded border border-cyan-800/70 bg-cyan-950/40 px-4 py-2 text-xs font-mono text-cyan-300 disabled:opacity-40"
              >
                {isSending ? "Saving..." : "Send"}
              </button>
            </div>
          </form>
        </section>
      </main>
    </div>
  );
}

function ContextPreviewPanel({ context, onClose }: { context: ProjectContext; onClose: () => void }) {
  return (
    <div className="rounded-lg border border-cyan-900/70 bg-cyan-950/20 p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-mono font-semibold text-cyan-200">Project context preview</p>
          <p className="mt-1 text-xs font-mono text-slate-500">{context.summary}</p>
        </div>
        <button onClick={onClose} className="text-[10px] font-mono text-slate-500 hover:text-slate-300">
          Close
        </button>
      </div>
      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
        <ContextMessageList title="Recent messages" messages={context.recent_messages} />
        <ContextMessageList title="Relevant previous messages" messages={context.relevant_messages} />
      </div>
      {context.known_limitations.length > 0 && (
        <div className="mt-4 border-t border-cyan-900/40 pt-3">
          <p className="text-[10px] font-mono uppercase tracking-widest text-slate-500">Limitations</p>
          <ul className="mt-2 space-y-1">
            {context.known_limitations.map((item) => (
              <li key={item} className="text-xs font-mono text-slate-500">
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ContextMessageList({ title, messages }: { title: string; messages: ProjectContext["recent_messages"] }) {
  return (
    <div className="rounded border border-slate-800 bg-[#030810] p-3">
      <p className="text-[10px] font-mono uppercase tracking-widest text-slate-500">
        {title} ({messages.length})
      </p>
      {messages.length === 0 ? (
        <p className="mt-3 text-xs font-mono text-slate-600">No messages selected.</p>
      ) : (
        <div className="mt-3 space-y-3">
          {messages.slice(0, 5).map((message) => (
            <div key={message.id}>
              <p className="text-[10px] font-mono uppercase text-slate-600">{message.role}</p>
              <p className="mt-1 line-clamp-3 text-xs font-mono text-slate-300">{message.content}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[760px] rounded-lg border px-4 py-3 ${
          isUser
            ? "border-cyan-800/60 bg-cyan-950/30"
            : "border-slate-800 bg-[#030810]"
        }`}
      >
        <div className="mb-2 flex items-center justify-between gap-4">
          <span className="text-[10px] font-mono uppercase tracking-widest text-slate-500">
            {isUser ? "You" : message.agent_name || message.role}
          </span>
          <span className="text-[10px] font-mono text-slate-700">
            {new Date(message.created_at).toLocaleString()}
          </span>
        </div>
        <p className="whitespace-pre-wrap break-words text-sm font-mono leading-6 text-slate-200">
          {message.content}
        </p>
      </div>
    </div>
  );
}
