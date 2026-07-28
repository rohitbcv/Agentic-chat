import { useEffect, useMemo, useRef, useState } from "react";
import { AgentSummaryCard } from "./components/AgentSummaryCard";
import { TracePanel } from "./components/TracePanel";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

function apiUrl(path) {
  return `${API_BASE}${path}`;
}

const initialMessage = {
  role: "assistant",
  content:
    "Ask a structured DB question or a grounded property question. I will route it through the read-only agent system and answer only from approved data.",
};

export default function App() {
  const [config, setConfig] = useState(null);
  const [messages, setMessages] = useState([initialMessage]);
  const [selectedClientId, setSelectedClientId] = useState("");
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [lastResponse, setLastResponse] = useState(null);
  const [error, setError] = useState("");
  const messageListRef = useRef(null);

  useEffect(() => {
    let ignore = false;

    async function loadConfig() {
      try {
        const response = await fetch(apiUrl("/api/agent-poc/config"));
        if (!response.ok) {
          throw new Error(`Config request failed with ${response.status}`);
        }
        const data = await response.json();
        if (!ignore) {
          setConfig(data);
        }
      } catch (err) {
        if (!ignore) {
          setError(err.message || "Could not load POC config.");
        }
      }
    }

    loadConfig();
    return () => {
      ignore = true;
    };
  }, []);

  const selectedClient = useMemo(() => {
    return (config?.clients || []).find((client) => String(client.id) === String(selectedClientId));
  }, [config, selectedClientId]);

  useEffect(() => {
    const list = messageListRef.current;
    if (!list) return;
    list.scrollTo({
      top: list.scrollHeight,
      behavior: "smooth",
    });
  }, [messages.length, isSending]);

  async function runQuery(rawQuery) {
    const query = rawQuery.trim();
    if (!query || isSending) return;
    const requestHistory = [...messages, { role: "user", content: query }]
      .slice(-12)
      .map((message) => ({
        role: message.role,
        content: message.content,
      }));

    setError("");
    setMessages((current) => [...current, { role: "user", content: query }]);
    setInput("");
    setIsSending(true);

    try {
      const response = await fetch(apiUrl("/api/agent-poc/chat"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query,
          client_id: selectedClientId ? Number(selectedClientId) : null,
          mode: "read_only",
          history: requestHistory,
        }),
      });

      if (!response.ok) {
        let message = `Agent request failed with ${response.status}`;
        try {
          const errorBody = await response.json();
          if (errorBody?.message) {
            message = errorBody.message;
          }
        } catch {
          // Keep the default message if the error body is not JSON.
        }
        throw new Error(message);
      }

      const data = await response.json();
      setLastResponse(data);
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: data.answer,
          mediaPreviews: data.media_previews || [],
          followUps: data.follow_up_questions || [],
        },
      ]);
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally {
      setIsSending(false);
    }
  }

  return (
    <div className="studioShell">
      <div className="studioBackdrop" />

      <aside className="leftRail">
        <section className="railCard railCard--scope">
          <div className="panelTitleRow">
            <div>
              <p className="eyebrow">Control Plane</p>
              <h2>Client Scope</h2>
            </div>
            <span className="pillStatus">Scoped</span>
          </div>
          <label className="fieldLabel" htmlFor="clientSelect">
            Client context
          </label>
          <select
            id="clientSelect"
            className="clientSelect"
            value={selectedClientId}
            onChange={(event) => setSelectedClientId(event.target.value)}
          >
            <option value="">Auto-detect from query</option>
            {(config?.clients || []).map((client) => (
              <option key={client.id} value={client.id}>
                {client.name}
              </option>
            ))}
          </select>
          {selectedClient ? (
            <p className="selectedClientMeta">
              {selectedClient.city} · {selectedClient.domain}
            </p>
          ) : (
            <p className="mutedCopy">
              Leave blank for auto-detection. The Orchestrator will infer the
              property when the query includes a recognizable name or client ID.
            </p>
          )}
        </section>

        <section className="railCard railCard--samples">
          <div className="panelTitleRow">
            <div>
              <p className="eyebrow">Command Palette</p>
              <h2>Sample Questions</h2>
            </div>
          </div>
          <div className="chipStack">
            {(config?.sample_queries || []).map((query) => (
              <button
                className="sampleChip"
                key={query}
                type="button"
                onClick={() => runQuery(query)}
              >
                {query}
              </button>
            ))}
          </div>
        </section>

        <section className="railCard">
          <div className="panelTitleRow">
            <div>
              <p className="eyebrow">Specialists</p>
              <h2>Agent Bench</h2>
            </div>
          </div>
          <div className="agentGrid">
            {(config?.agents || []).map((agent) => (
              <AgentSummaryCard agent={agent} key={agent.name} />
            ))}
          </div>
        </section>
      </aside>

      <main className="conversationStage">
        <section className="chatCard">
          <div className="chatHeader">
            <div>
              <p className="eyebrow">Analyst Console</p>
              <h3>Ask anything the DB can prove</h3>
            </div>
            <span className={`runState ${isSending ? "runState--busy" : ""}`}>
              {isSending ? "Agents working..." : "Ready"}
            </span>
          </div>

          <div className="messageList" ref={messageListRef}>
            {messages.map((message, index) => (
              <article
                className={`messageBubble ${
                  message.role === "user" ? "messageBubble--user" : "messageBubble--assistant"
                }`}
                key={`${message.role}-${index}`}
              >
                <div className="messageMeta">
                  <span>{message.role === "user" ? "You" : "Assistant"}</span>
                </div>
                <p>{message.content}</p>
                {message.mediaPreviews?.length ? (
                  <div className="mediaPreviewBlock">
                    <span className="mediaPreviewTitle">Media used</span>
                    <div className="mediaPreviewGrid">
                      {message.mediaPreviews.map((media) => (
                        <article className="mediaPreviewCard" key={`${media.media_id}-${media.name}`}>
                          <div className="mediaThumb">
                            {media.thumbnail_url ? (
                              <img src={media.thumbnail_url} alt={media.alt_text || media.name} />
                            ) : (
                              <span>{media.name}</span>
                            )}
                          </div>
                          <div className="mediaPreviewBody">
                            <strong>{media.name}</strong>
                            <span>Media ID {media.media_id}</span>
                            <p>{media.description || media.alt_text}</p>
                            {media.tags?.length ? (
                              <div className="mediaTagRow">
                                {media.tags.slice(0, 4).map((tag) => (
                                  <em key={tag}>{tag}</em>
                                ))}
                              </div>
                            ) : null}
                          </div>
                        </article>
                      ))}
                    </div>
                  </div>
                ) : null}
                {message.followUps?.length ? (
                  <div className="followupBlock">
                    <span className="followupTitle">Follow-ups</span>
                    <div className="followupStack">
                      {message.followUps.map((question) => (
                        <button
                          className="followupChip"
                          disabled={isSending}
                          key={question}
                          type="button"
                          onClick={() => runQuery(question)}
                        >
                          {question}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
              </article>
            ))}
          </div>

          <form
            className="composer"
            onSubmit={(event) => {
              event.preventDefault();
              runQuery(input);
            }}
          >
            <label className="srOnly" htmlFor="queryInput">
              Ask a question
            </label>
            <textarea
              id="queryInput"
              className="composerInput"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Try: Which guest complaints are unresolved for Snow Villa?"
              rows={4}
            />
            <div className="composerFooter">
              <p className="mutedCopy">
                Read-only only. Answers must be grounded in SQL rows, embeddings, or relationship paths.
              </p>
              <button className="sendButton" type="submit" disabled={isSending || !input.trim()}>
                {isSending ? "Routing..." : "Run Agent Query"}
              </button>
            </div>
          </form>

          {error ? <div className="errorBanner">{error}</div> : null}
        </section>
      </main>

      <TracePanel response={lastResponse} />
    </div>
  );
}
