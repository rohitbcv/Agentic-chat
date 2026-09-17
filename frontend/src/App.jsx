import { useEffect, useMemo, useRef, useState } from "react";
import { AgentSummaryCard } from "./components/AgentSummaryCard";
import { TracePanel } from "./components/TracePanel";
import { PropertyChatPanel } from "./components/PropertyChatPanel";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

function apiUrl(path) {
  return `${API_BASE}${path}`;
}

const initialMessage = {
  role: "assistant",
  content:
    "Ask a structured DB question or a grounded property question. I will route it through the read-only agent system and answer only from approved data.",
};

const IconSend = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
  </svg>
);


export default function App() {
  const [config, setConfig] = useState(null);
  const [messages, setMessages] = useState([initialMessage]);
  const [selectedClientId, setSelectedClientId] = useState("");
  const [sessionClientId, setSessionClientId] = useState(null);
  const [sessionClientName, setSessionClientName] = useState(null);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [lastResponse, setLastResponse] = useState(null);
  const [error, setError] = useState("");
  const [leftTab, setLeftTab] = useState("inboxsamples");
  const [mainView, setMainView] = useState("inbox"); // "chat" | "inbox" — Q&A Chat commented out
  const messageListRef = useRef(null);

  // ── Inbox Monitor state ─────────────────────────────────────────────────
  const [inboxInput, setInboxInput] = useState("");
  const [inboxMessageType, setInboxMessageType] = useState("messages"); // comments|messages|review|mentions
  const [inboxResult, setInboxResult] = useState(null);
  const [inboxSending, setInboxSending] = useState(false);
  const [inboxError, setInboxError] = useState("");
  const [opsDecisionSent, setOpsDecisionSent] = useState(false);
  const [editedReply, setEditedReply] = useState("");
  // Conversation history — per active client (loaded from backend inbox thread + DB)
  const [convHistory, setConvHistory]       = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const historyBottomRef = useRef(null);
  const historyFetchGen = useRef(0);
  // Property chat — guest reply generated from property's answer
  const [generatedGuestReply, setGeneratedGuestReply] = useState(null);

  useEffect(() => {
    let ignore = false;
    async function loadConfig() {
      try {
        const response = await fetch(apiUrl("/api/agent-poc/config"));
        if (!response.ok) throw new Error(`Config request failed with ${response.status}`);
        const data = await response.json();
        if (!ignore) setConfig(data);
      } catch (err) {
        if (!ignore) setError(err.message || "Could not load POC config.");
      }
    }
    loadConfig();
    return () => { ignore = true; };
  }, []);

  const activeInboxClientId = sessionClientId || (selectedClientId ? Number(selectedClientId) : null);

  // ── Load this client's last 5 inbox turns when client changes ──
  const fetchConversationHistory = async (clientId, { markNewest = false } = {}) => {
    if (!clientId) {
      setConvHistory([]);
      return;
    }
    const fetchId = ++historyFetchGen.current;
    setHistoryLoading(true);
    try {
      const res = await fetch(apiUrl(`/api/agent-poc/conversation-history?client_id=${clientId}&limit=5`));
      if (!res.ok) throw new Error("History fetch failed");
      const data = await res.json();
      if (fetchId !== historyFetchGen.current) return;
      const history = (data.history || []).slice(-5);
      if (markNewest && history.length > 0) {
        history[history.length - 1] = { ...history[history.length - 1], _isNew: true };
      }
      setConvHistory(history);
    } catch (_) {
      if (fetchId === historyFetchGen.current) setConvHistory([]);
    } finally {
      if (fetchId === historyFetchGen.current) setHistoryLoading(false);
    }
  };

  useEffect(() => {
    if (mainView !== "inbox") return;
    if (activeInboxClientId) {
      fetchConversationHistory(activeInboxClientId);
    } else {
      setConvHistory([]);
    }
  }, [mainView, activeInboxClientId]);

  // Scroll history to bottom when it changes
  useEffect(() => {
    if (historyBottomRef.current) {
      historyBottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [convHistory]);

  const selectedClient = useMemo(
    () => (config?.clients || []).find((c) => String(c.id) === String(selectedClientId)),
    [config, selectedClientId]
  );

  useEffect(() => {
    const list = messageListRef.current;
    if (!list) return;
    list.scrollTo({ top: list.scrollHeight, behavior: "smooth" });
  }, [messages.length, isSending]);

  const effectiveClientId = selectedClientId ? Number(selectedClientId) : (sessionClientId || null);

  function clearSessionContext() {
    setSessionClientId(null);
    setSessionClientName(null);
  }

  async function runQuery(rawQuery, options = {}) {
    const query = rawQuery.trim();
    if (!query || isSending) return;
    const requestHistory = [...messages, { role: "user", content: query }]
      .slice(-12)
      .map((m) => ({ role: m.role, content: m.content }));

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
          client_id: effectiveClientId,
          mode: "read_only",
          history: requestHistory,
        }),
      });

      if (!response.ok) {
        let message = `Agent request failed with ${response.status}`;
        try {
          const errorBody = await response.json();
          if (errorBody?.message) message = errorBody.message;
        } catch { /* keep default */ }
        throw new Error(message);
      }

      const data = await response.json();
      setLastResponse(data);

      if (data.client_id && !selectedClientId) {
        const resolvedClient = (config?.clients || []).find((c) => Number(c.id) === Number(data.client_id));
        const resolvedId = Number(data.client_id);
        if (resolvedId !== sessionClientId) {
          setSessionClientId(resolvedId);
          setSessionClientName(resolvedClient?.name || `Client ${resolvedId}`);
        }
      }

      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: data.answer,
          mediaPreviews: data.media_previews || [],
          followUps: data.follow_up_questions || [],
          agentName: data.route?.next_agent || null,
          capability: data.route?.capability || null,
          agentTrace: data.agent_trace || [],
          mode: data.mode || null,
          decisionValidation: data.decision_validation || null,
          evidenceValidation: data.evidence_validation || null,
        },
      ]);
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally {
      setIsSending(false);
    }
  }

  // ── Inbox Monitor: process message ────────────────────────────────────────
  async function processInboxMessage() {
    const msg = inboxInput.trim();
    if (!msg) return;
    const clientId = sessionClientId || (selectedClientId ? Number(selectedClientId) : null);
    if (!clientId) {
      setInboxError("Please select a client first.");
      return;
    }
    setInboxSending(true);
    setInboxError("");
    setInboxResult(null);
    setOpsDecisionSent(false);
    setEditedReply("");
    setGeneratedGuestReply(null);
    try {
      const res = await fetch(apiUrl("/api/agent-poc/process-message"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message_content: msg,
          client_id: clientId,
          message_type: inboxMessageType,
          conversation_history: convHistory.slice(-5).map((item) => ({
            content: item.content || "",
            reply_text: item.reply_text || "",
            category: item.category || null,
            triage_state: item.triage_state || null,
            ts: item.ts || null,
            author: item.author || "Guest",
          })),
        }),
      });
      if (!res.ok) throw new Error(`Request failed: ${res.status}`);
      const data = await res.json();
      setInboxResult(data);
      // Populate editable reply from whichever draft is available
      const draft =
        data.escalation_packet?.suggested_reply
        || data.auto_answer_draft
        || data.pending_reply_draft
        || "";
      setEditedReply(draft);
      await fetchConversationHistory(clientId, { markNewest: true });
    } catch (err) {
      setInboxError(err.message || "Something went wrong.");
    } finally {
      setInboxSending(false);
    }
  }

  async function sendOpsDecision(action) {
    if (!inboxResult) return;
    const clientId = sessionClientId || (selectedClientId ? Number(selectedClientId) : null);
    try {
      await fetch(apiUrl("/api/agent-poc/process-message/ops-decision"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId,
          guest_message: inboxResult.message_content,
          ops_action: action,
          final_answer: editedReply,
          original_draft: inboxResult.escalation_packet?.suggested_reply || inboxResult.auto_answer_draft,
          category: inboxResult.classification?.category,
          urgency_level: inboxResult.classification?.urgency_level,
          source_excerpt: inboxResult.auto_answer_source_excerpt,
        }),
      });
      setOpsDecisionSent(true);
      if (clientId) await fetchConversationHistory(clientId);
    } catch (err) {
      setInboxError("Failed to record ops decision.");
    }
  }

  // ── Left panel tabs ────────────────────────────────────────────────────────
  const LEFT_TABS = [
    { id: "inboxsamples",  label: "📬 Inbox" },
  ];

  return (
    <div className="appShell">

      {/* ── Left panel ── */}
      <aside className="leftPanel">
        {/* Client scope header */}
        <div className="leftPanelHeader">
          <div className="leftPanelTitle">
            <span className="leftPanelEyebrow">Control Plane</span>
            <h2>Client Scope</h2>
          </div>
          <span className={`statusPill ${isSending ? "statusPill--busy" : "statusPill--ready"}`}>
            {isSending ? "Working…" : "Ready"}
          </span>
        </div>

        <div className="clientScopeBox">
          <label className="fieldLabel" htmlFor="clientSelect">Client context</label>
          <select
            id="clientSelect"
            className="clientSelect"
            value={selectedClientId}
            onChange={(e) => {
              setSelectedClientId(e.target.value);
              if (e.target.value) { setSessionClientId(null); setSessionClientName(null); }
              setInboxResult(null);
              setInboxInput("");
              setOpsDecisionSent(false);
              setGeneratedGuestReply(null);
            }}
          >
            <option value="">Auto-detect from query</option>
            {(config?.clients || []).map((client) => (
              <option key={client.id} value={client.id}>{client.name}</option>
            ))}
          </select>
          {selectedClient ? (
            <p className="clientMeta">{selectedClient.city} · {selectedClient.domain}</p>
          ) : sessionClientId ? (
            <div className="sessionChip">
              <span className="sessionDot" />
              <span className="sessionName">{sessionClientName}</span>
              <button className="sessionClear" onClick={clearSessionContext} type="button">×</button>
            </div>
          ) : (
            <p className="mutedNote">Auto-detects hotel from query text or client ID.</p>
          )}
        </div>

        {/* Tab bar — Samples and Validation hidden; Inbox samples only
        <div className="leftTabBar">
          {LEFT_TABS.map((t) => (
            <button
              key={t.id}
              className={`leftTab ${leftTab === t.id ? "leftTab--active" : ""}`}
              onClick={() => setLeftTab(t.id)}
              type="button"
            >
              {t.label}
            </button>
          ))}
        </div>
        */}

        {/* Tab content */}
        <div className="leftTabContent">
          {/* Samples tab hidden
          {leftTab === "samples" && (
            <div className="chipList">
              {(config?.sample_queries || []).map((q) => (
                <button className="queryChip" key={q} type="button" onClick={() => { runQuery(q); }}>
                  {q}
                </button>
              ))}
            </div>
          )}
          */}

          <div className="inboxSamples inboxSamples--tab">
            <p className="probeNote">Click a sample to load it into the Inbox Monitor.</p>
            {[
              { label: "Routine question",        msg: "Is this hotel pet-friendly?" },
              { label: "Policy query",            msg: "What time is check-in and check-out?" },
              { label: "In-house request (cab)",  msg: "Hi, my flight is delayed and I need to change my cab from 12 PM to 2 PM. Can you help?" },
              { label: "Lost item (bag)",         msg: "Hi. My husband accidentally left behind a clear bag with the NY Giants logo on it with 3 water bottles in it. If you find it, would you be able to hold it for us until Tuesday?" },
              { label: "Lost item follow-up",     msg: "Is my bag safe? I am coming to pick it up — is my bag found?" },
              { label: "Complaint",               msg: "I'm very unhappy. The room was dirty and no one came to fix it after 3 hours." },
              { label: "Appreciation",            msg: "Thank you so much for the wonderful stay! The staff were incredibly helpful." },
              { label: "Crisis",                  msg: "There is smoke coming from the room next to mine, I think there might be a fire!" },
              { label: "Booking issue",           msg: "I booked for September 28th but my confirmation says October 28th. This is incorrect." },
            ].map((s) => (
              <button
                key={s.label}
                className="inboxSampleBtn"
                type="button"
                onClick={() => { setMainView("inbox"); setInboxInput(s.msg); }}
              >
                <span className="inboxSampleLabel">{s.label}</span>
                <span className="inboxSampleMsg">{s.msg}</span>
              </button>
            ))}
          </div>

          {/* Validation tab hidden
          {leftTab === "validation" && (
            <div className="probeList">
              <p className="probeNote">Each probe targets a specific validation stage.</p>
              {(config?.validation_sample_queries || []).map((item) => (
                <button className="probeCard" key={item.query} type="button" onClick={() => { runQuery(item.query); }}>
                  <span className="probeLabel">{item.label}</span>
                  <span className="probeQuery">{item.query}</span>
                  {item.checks ? <span className="probeChecks">{item.checks}</span> : null}
                </button>
              ))}
            </div>
          )}
          */}
        </div>
      </aside>

      {/* ── Main panel ── */}
      <main className="mainPanel">
        {/* Top bar with view toggle */}
        <div className="mainTopBar">
          <div className="mainTopBarLeft">
            <span className="mainTopBarEyebrow">Smart Community Inbox</span>
            <div className="mainViewToggle">
              {/* Q&A Chat temporarily hidden
              <button
                className={`mainViewBtn ${mainView === "chat" ? "mainViewBtn--active" : ""}`}
                type="button"
                onClick={() => setMainView("chat")}
              >
                💬 Q&amp;A Chat
              </button>
              */}
              <button
                className={`mainViewBtn ${mainView === "inbox" ? "mainViewBtn--active" : ""}`}
                type="button"
                onClick={() => setMainView("inbox")}
              >
                📬 Inbox Monitor
              </button>
            </div>
          </div>
          <div className="mainTopBarRight">
            {sessionClientId && !selectedClientId ? (
              <span className="sessionBadge">
                <span className="sessionDot" /> {sessionClientName}
              </span>
            ) : selectedClient ? (
              <span className="sessionBadge sessionBadge--selected">
                {selectedClient.name}
              </span>
            ) : null}
            <span className={`statusPill ${isSending ? "statusPill--busy" : "statusPill--ready"}`}>
              {isSending ? "Agents working…" : "Ready"}
            </span>
          </div>
        </div>

        {/* ── Inbox Monitor view ───────────────────────────────────────────── */}
        {mainView === "inbox" && (
          <div className="inboxMainPanel">
            {/* Channel selector */}
            <div className="inboxChannelBar">
              <span className="inboxChannelLabel">Source channel:</span>
              {[
                { id: "messages", label: "💬 DM / Message",    icon: "💬" },
                { id: "comments", label: "🌐 Social Comment",  icon: "🌐" },
                { id: "review",   label: "⭐ Platform Review", icon: "⭐" },
                { id: "mentions", label: "📢 Brand Mention",   icon: "📢" },
              ].map((ch) => (
                <button
                  key={ch.id}
                  className={`inboxChannelBtn ${inboxMessageType === ch.id ? "inboxChannelBtn--active" : ""}`}
                  type="button"
                  onClick={() => setInboxMessageType(ch.id)}
                >
                  {ch.label}
                </button>
              ))}
            </div>

            <div className="inboxMainComposer">
              <textarea
                className="inboxMainInput"
                rows={4}
                placeholder="Paste a guest message here — e.g. 'Is this hotel pet-friendly?' or 'My flight is delayed, I need to change my cab from 12 PM to 2 PM'"
                value={inboxInput}
                onChange={(e) => setInboxInput(e.target.value)}
                disabled={inboxSending}
              />
              <button
                className="inboxMainBtn"
                type="button"
                disabled={inboxSending || !inboxInput.trim()}
                onClick={processInboxMessage}
              >
                {inboxSending ? "Processing…" : "Process Message →"}
              </button>
            </div>

            {inboxError && <p className="inboxError">{inboxError}</p>}

            {inboxResult && (
              <div className="inboxMainResult">
                {/* Original message */}
                <div className="inboxOrigMsg">
                  <span className="inboxOrigLabel">Guest message</span>
                  <p className="inboxOrigText">{inboxResult.message_content}</p>
                </div>

                {/* Classification row */}
                <div className="inboxClassRow">
                  <span className={`catBadge catBadge--${inboxResult.classification?.category}`}>
                    {inboxResult.classification?.category?.replace(/_/g, " ")}
                  </span>
                  <span className={`urgencyPill urgencyPill--${inboxResult.classification?.urgency_level}`}>
                    {inboxResult.classification?.urgency_level?.toUpperCase()}
                  </span>
                  {inboxResult.channel_label && (
                    <span className={`channelBadge channelBadge--${inboxResult.message_type}`}>
                      { { messages: "💬", comments: "🌐", review: "⭐", mentions: "📢" }[inboxResult.message_type] || "📨" }
                      {" "}{inboxResult.channel_label}
                    </span>
                  )}
                  {inboxResult.used_conversation_context && (
                    <span className="inboxConfBadge">Used matching prior message in thread</span>
                  )}
                  {inboxResult.used_prior_property_response && (
                    <span className="inboxConfBadge">Reused earlier property reply — not re-asked</span>
                  )}
                  <span className="classMethod">{inboxResult.classification?.classification_method}</span>
                  <span className="classConf">conf {Math.round((inboxResult.classification?.confidence || 0) * 100)}%</span>
                  <span className="inboxTriagePill">Triage: <strong>{inboxResult.triage_state}</strong></span>
                </div>

                {/* Extracted entities */}
                {(() => {
                  const ent = inboxResult.classification?.entities || {};
                  const items = [
                    ...(ent.dates || []).map(d => `📅 ${d}`),
                    ...(ent.times || []).map(t => `⏰ ${t}`),
                    ...(ent.booking_refs || []).map(r => `🔖 ${r}`),
                    ...(ent.guest_names || []).map(n => `👤 ${n}`),
                  ];
                  return items.length ? (
                    <div className="inboxEntities">
                      {items.map((item, i) => <span key={i} className="entityTag">{item}</span>)}
                    </div>
                  ) : null;
                })()}

                {/* Draft reply — always shown for review */}
                {!opsDecisionSent && (inboxResult.auto_answer_draft || inboxResult.pending_reply_draft || inboxResult.escalation_packet?.suggested_reply) && (() => {
                  const isAutoHigh = inboxResult.auto_answered;
                  const isEscalation = !!inboxResult.escalation_packet;
                  const isPendingReply = !!inboxResult.pending_reply_draft && !isAutoHigh && !isEscalation;

                  return (
                    <div className={`inboxDraftSection ${isEscalation ? "inboxDraftSection--escalation" : isAutoHigh ? "inboxDraftSection--auto" : "inboxDraftSection--pending"}`}>
                      <div className="inboxSectionLabel">
                        {isEscalation ? "⚠ Ops Escalation — " : isAutoHigh ? "✅ High-confidence auto-reply — " : "💬 Suggested reply — "}
                        {isAutoHigh && <span className="inboxConfBadge">{Math.round((inboxResult.auto_answer_confidence || 0) * 100)}% confidence</span>}
                        {isEscalation && (
                          <span className={`urgencyPill urgencyPill--${inboxResult.classification?.urgency_level}`}>
                            {inboxResult.escalation_packet.urgency_label}
                          </span>
                        )}
                        {isPendingReply && <span className="inboxConfBadge inboxConfBadge--neutral">Review before sending</span>}
                      </div>

                      {isEscalation && inboxResult.escalation_packet.ops_action_label && (
                        <div className="inboxActionTag">Action needed: <strong>{inboxResult.escalation_packet.ops_action_label}</strong></div>
                      )}

                      {isEscalation && inboxResult.escalation_packet.available_context?.length > 0 && (
                        <div className="inboxContextList">
                          <div className="inboxContextTitle">Relevant property info found:</div>
                          {inboxResult.escalation_packet.available_context.slice(0, 3).map((ctx, i) => (
                            <div className="inboxContextRow" key={i}>
                              <span className="inboxCtxTitle">{ctx.title}</span>
                              <span className="inboxCtxExcerpt">{ctx.excerpt?.slice(0, 150)}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {isPendingReply && inboxResult.auto_answer_source_excerpt && (
                        <div className="inboxSourceNote">
                          Source: FAQ / property details — "{inboxResult.auto_answer_source_excerpt.slice(0, 120)}…"
                        </div>
                      )}

                      {isAutoHigh && (inboxResult.auto_answer_source_label || inboxResult.auto_answer_source_excerpt) && (
                        <div className="inboxSourceNote">
                          Source: {inboxResult.auto_answer_source_label || inboxResult.auto_answer_source_table || "verified property data"}
                          {inboxResult.auto_answer_source_excerpt ? ` — "${inboxResult.auto_answer_source_excerpt.slice(0, 140)}…"` : ""}
                        </div>
                      )}

                      <div className="inboxSectionLabel" style={{ marginTop: 8, marginBottom: 2 }}>Reply to send (edit if needed):</div>
                      <textarea
                        className="inboxEditReply"
                        rows={5}
                        value={editedReply}
                        onChange={(e) => setEditedReply(e.target.value)}
                      />

                      {isEscalation && inboxResult.escalation_packet.suggested_action && (
                        <div className="inboxSuggestedAction">💡 Suggested action: {inboxResult.escalation_packet.suggested_action}</div>
                      )}

                      <div className="opsButtonRow">
                        <button className="opsBtn opsBtn--approve" type="button" onClick={() => sendOpsDecision("approved")}>✓ Approve &amp; Send</button>
                        <button className="opsBtn opsBtn--edit"    type="button" onClick={() => sendOpsDecision("edited")}>✎ Send Edited</button>
                        <button className="opsBtn opsBtn--reject"  type="button" onClick={() => sendOpsDecision("rejected")}>✕ Reject</button>
                      </div>
                    </div>
                  );
                })()}

                {opsDecisionSent && (
                  <div className="inboxDecisionConfirm">✅ Decision recorded. The system has logged this for accuracy tracking.</div>
                )}
              </div>
            )}

            {/* ── Conversation History ──────────────────────────────────── */}
            <div className="convHistoryPanel">
              <div className="convHistoryHeader">
                <h5 className="convHistoryTitle">📋 Recent Conversations — Last 5 Messages</h5>
                {historyLoading && <span className="convHistoryLoading">Loading…</span>}
                {!historyLoading && convHistory.length > 0 && (
                  <span className="convHistoryCount">{convHistory.length} message{convHistory.length !== 1 ? "s" : ""}</span>
                )}
              </div>

              {!historyLoading && convHistory.length === 0 && (
                <p className="convHistoryEmpty">No recent messages for this client yet. Process a guest message to start this thread.</p>
              )}

              <div className="convHistoryList">
                {convHistory.map((item, idx) => {
                  const channelIcon = { messages: "💬", comments: "🌐", review: "⭐", mentions: "📢" }[item.message_type] || "📨";
                  const urgencyColor = { critical: "#dc2626", high: "#ea580c", medium: "#d97706", low: "#16a34a" }[item.urgency_level] || "#6b7280";
                  const isNew = !!item._isNew;

                  // Format timestamp
                  let dateStr = "";
                  let timeStr = "";
                  if (item.ts) {
                    const d = new Date(item.ts);
                    dateStr = d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
                    timeStr = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
                  }

                  return (
                    <div key={idx} className={`convHistoryItem ${isNew ? "convHistoryItem--new" : ""}`}>
                      {/* Date-time + channel row */}
                      <div className="convHistoryMeta">
                        <span className="convHistoryTime">{dateStr}{timeStr ? ` · ${timeStr}` : ""}</span>
                        <span className={`channelBadge channelBadge--${item.message_type}`}>{channelIcon} {item.channel_label?.replace(/💬|🌐|⭐|📢/g, "").trim()}</span>
                        {item.category && (
                          <span className={`catBadge catBadge--${item.category}`}>{item.category.replace(/_/g, " ")}</span>
                        )}
                        {item.urgency_level && (
                          <span className="convUrgencyDot" style={{ background: urgencyColor }} title={item.urgency_level} />
                        )}
                      </div>

                      {/* Guest message bubble */}
                      <div className="convMsgBubble convMsgBubble--guest">
                        <span className="convMsgAuthor">{item.author || "Guest"}</span>
                        <p className="convMsgText">{item.content}</p>
                      </div>

                      {/* Response bubble (if any) */}
                      {item.reply_text && (
                        <div className="convMsgBubble convMsgBubble--hotel">
                          <span className="convMsgAuthor">
                            Hotel
                            {item.ops_action && (
                              <span className={`convOpsTag convOpsTag--${item.ops_action}`}>{
                                { auto_replied: "auto", approved: "ops ✓", edited: "ops ✎", rejected: "rejected", pending: "pending", escalated: "escalated" }[item.ops_action] || item.ops_action
                              }</span>
                            )}
                          </span>
                          <p className="convMsgText">{item.reply_text}</p>
                        </div>
                      )}
                    </div>
                  );
                })}
                <div ref={historyBottomRef} />
              </div>
            </div>
          </div>
        )}

        {/* ── Chat Q&A view (temporarily hidden) ─────────────────────────────── */}
        {false && mainView === "chat" && <>

        {/* Message list */}
        <div className="messageList" ref={messageListRef}>
          {messages.map((message, index) => (
            <article
              key={`${message.role}-${index}`}
              className={`msgRow ${message.role === "user" ? "msgRow--user" : "msgRow--assistant"}`}
            >
              <div className="msgAvatar">
                {message.role === "user" ? "You" : "AI"}
              </div>

              <div className="msgBody">
                {/* Agent run card */}
                {message.agentName ? (
                  <div className="agentCard">
                    <div className="agentCardHeader">
                      <div className="agentCardLeft">
                        <span className="agentDot" />
                        <div>
                          <p className="agentCardEyebrow">Agent Called</p>
                          <strong className="agentCardName">{message.agentName}</strong>
                          {message.capability ? (
                            <span className="capabilityTag">
                              {message.capability.replace(/_/g, " ")}
                            </span>
                          ) : null}
                        </div>
                      </div>
                      <div className="validationBadges">
                        {message.decisionValidation ? (
                          <span className={`valBadge valBadge--${message.decisionValidation.status}`}>
                            {message.decisionValidation.passed ? "✓" : message.decisionValidation.status === "warning" ? "⚠" : "✗"}{" "}
                            Decision
                          </span>
                        ) : null}
                        {message.evidenceValidation ? (
                          <span className={`valBadge valBadge--${message.evidenceValidation.status}`}>
                            {message.evidenceValidation.passed ? "✓" : message.evidenceValidation.status === "warning" ? "⚠" : "✗"}{" "}
                            Evidence
                          </span>
                        ) : null}
                      </div>
                    </div>

                    {/* Blocking issues */}
                    {[
                      ...(message.decisionValidation?.blocking_issues || []),
                      ...(message.evidenceValidation?.blocking_issues || []),
                    ].map((issue, i) => (
                      <p key={i} className="agentIssue agentIssue--block">✗ {issue}</p>
                    ))}

                    {/* Warnings */}
                    {![...(message.decisionValidation?.blocking_issues || []), ...(message.evidenceValidation?.blocking_issues || [])].length &&
                      [...(message.decisionValidation?.warnings || []), ...(message.evidenceValidation?.warnings || [])].slice(0, 3).map((w, i) => (
                        <p key={i} className="agentIssue agentIssue--warn">⚠ {w}</p>
                      ))
                    }
                  </div>
                ) : null}

                {/* Message text */}
                <div className="msgContent">
                  <p style={{ whiteSpace: "pre-wrap", margin: 0 }}>{message.content}</p>
                </div>

                {/* Media previews */}
                {message.mediaPreviews?.length ? (
                  <div className="mediaGrid">
                    {message.mediaPreviews.map((media) => (
                      <div className="mediaCard" key={`${media.media_id}-${media.name}`}>
                        <div className="mediaThumb">
                          {media.thumbnail_url
                            ? <img src={media.thumbnail_url} alt={media.alt_text || media.name} />
                            : <span>{media.name}</span>}
                        </div>
                        <div className="mediaInfo">
                          <strong>{media.name}</strong>
                          <span>ID {media.media_id}</span>
                          <p>{media.description || media.alt_text}</p>
                          {media.tags?.length ? (
                            <div className="mediaTags">
                              {media.tags.slice(0, 4).map((t) => <em key={t}>{t}</em>)}
                            </div>
                          ) : null}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}

                {/* Follow-ups */}
                {message.followUps?.length ? (
                  <div className="followUpRow">
                    <span className="followUpLabel">Suggested next</span>
                    <div className="followUpChips">
                      {message.followUps.map((q) => (
                        <button
                          key={q}
                          className="followUpChip"
                          disabled={isSending}
                          type="button"
                          onClick={() => runQuery(q)}
                        >
                          {q}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </article>
          ))}

          {isSending && (
            <div className="msgRow msgRow--assistant">
              <div className="msgAvatar">AI</div>
              <div className="msgBody">
                <div className="msgContent typingIndicator">
                  <span /><span /><span />
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Error */}
        {error ? <div className="errorBanner">⚠ {error}</div> : null}

        {/* Composer */}
        <div className="composer">
          <form
            className="composerForm"
            onSubmit={(e) => { e.preventDefault(); runQuery(input); }}
          >
            <textarea
              className="composerInput"
              id="queryInput"
              placeholder="Try: Which guest complaints are unresolved for Snow Villa?"
              rows={3}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); runQuery(input); }
              }}
            />
            <div className="composerActions">
              <span className="composerHint">Read-only · Answers grounded in DB only · Shift+Enter for new line</span>
              <button
                className="sendBtn"
                type="submit"
                disabled={isSending || !input.trim()}
              >
                <IconSend />
                {isSending ? "Routing…" : "Send"}
              </button>
            </div>
          </form>
        </div>

        </>}
      </main>

      {/* <TracePanel response={lastResponse} /> */}

      {/* ── Property Chat Panel (right, appears on escalation) ── */}
      {mainView === "inbox" && inboxResult?.escalation_packet && (
        <PropertyChatPanel
          inboxResult={inboxResult}
          clientId={sessionClientId || (selectedClientId ? Number(selectedClientId) : null)}
          clientName={inboxResult?.client_name}
          onGuestReplyGenerated={async (reply) => {
            setGeneratedGuestReply(reply);
            const clientId = sessionClientId || (selectedClientId ? Number(selectedClientId) : null);
            if (clientId) await fetchConversationHistory(clientId);
          }}
        />
      )}

      {/* Generated guest reply banner — shown in inbox monitor */}
      {mainView === "inbox" && generatedGuestReply && (
        <div className="generatedReplyBanner">
          <div className="generatedReplyBannerInner">
            <span className="generatedReplyBannerIcon">✅</span>
            <div>
              <div className="generatedReplyBannerTitle">Guest reply auto-generated from property answer</div>
              <p className="generatedReplyBannerText">{generatedGuestReply}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
