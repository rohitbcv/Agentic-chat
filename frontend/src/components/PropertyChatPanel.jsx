import { useEffect, useRef, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "";
const apiUrl  = (path) => `${API_BASE}${path}`;

const CHANNEL_ICONS = {
  messages: "💬", comments: "🌐", review: "⭐", mentions: "📢",
};
const CATEGORY_COLORS = {
  crisis: "#dc2626", complaint: "#ea580c", in_house_request: "#d97706",
  booking_related: "#7c3aed", question: "#2563eb", appreciation: "#16a34a",
  external_dm: "#0891b2", spam: "#6b7280",
};

export function PropertyChatPanel({ inboxResult, clientId, clientName, onGuestReplyGenerated }) {
  const [messages, setMessages]   = useState([]);
  const [input, setInput]         = useState("");
  const [sending, setSending]     = useState(false);
  const [error, setError]         = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const bottomRef = useRef(null);

  // Derive a stable chat key from the inbox result
  const chatKey = inboxResult
    ? (inboxResult.escalation_packet?.alert_id
        ? String(inboxResult.escalation_packet.alert_id)
        : `msg-${btoa(inboxResult.message_content || "").slice(0, 12)}`)
    : null;

  const classification = inboxResult?.classification || {};
  const escalation     = inboxResult?.escalation_packet || {};
  const category       = classification.category || "question";
  const urgency        = classification.urgency_level || "low";
  const channelIcon    = CHANNEL_ICONS[inboxResult?.message_type] || "📨";
  const catColor       = CATEGORY_COLORS[category] || "#6b7280";

  // Load existing chat on mount / when chatKey changes
  useEffect(() => {
    if (!chatKey || !clientId) return;
    setMessages([]);
    fetch(apiUrl(`/api/agent-poc/property-chat/${chatKey}?client_id=${clientId}`))
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d?.messages) setMessages(d.messages); })
      .catch(() => {});
  }, [chatKey, clientId]);

  // Scroll to bottom on new message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendReply() {
    const text = input.trim();
    if (!text || !chatKey) return;
    setSending(true);
    setError("");
    try {
      const res = await fetch(apiUrl("/api/agent-poc/property-reply"), {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_key:       chatKey,
          client_id:      clientId,
          client_name:    clientName || "the hotel",
          guest_message:  inboxResult?.message_content || "",
          property_reply: text,
          category,
          urgency_level:  urgency,
        }),
      });
      if (!res.ok) throw new Error("Failed to send reply");
      const data = await res.json();
      setMessages(data.messages || []);
      setInput("");
      // Bubble the generated guest reply up to Inbox Monitor
      if (data.guest_reply && onGuestReplyGenerated) {
        onGuestReplyGenerated(data.guest_reply);
      }
    } catch (e) {
      setError(e.message || "Something went wrong.");
    } finally {
      setSending(false);
    }
  }

  // Don't render if no escalation
  if (!inboxResult?.escalation_packet) return null;

  return (
    <aside className={`propertyChatPanel ${collapsed ? "propertyChatPanel--collapsed" : ""}`}>

      {/* Header */}
      <div className="propChatHeader">
        <div className="propChatHeaderLeft">
          <span className="propChatIcon">🏨</span>
          <div>
            <div className="propChatTitle">Property Chat</div>
            <div className="propChatSub">Reply as property team</div>
          </div>
        </div>
        <button
          className="propChatCollapseBtn"
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          title={collapsed ? "Expand" : "Collapse"}
        >
          {collapsed ? "▶" : "◀"}
        </button>
      </div>

      {!collapsed && (
        <>
          {/* Alert context card */}
          <div className="propChatContext">
            <div className="propChatContextRow">
              <span className="propChatChannelIcon">{channelIcon}</span>
              <span className={`catBadge catBadge--${category}`}>{category.replace(/_/g, " ")}</span>
              <span className={`urgencyPill urgencyPill--${urgency}`}>{urgency.toUpperCase()}</span>
              {escalation.ops_action_label && (
                <span className="propChatActionTag">{escalation.ops_action_label}</span>
              )}
            </div>

            <div className="propChatGuestMsg">
              <span className="propChatGuestLabel">Guest message</span>
              <p className="propChatGuestText">{inboxResult.message_content}</p>
            </div>

            {escalation.suggested_reply && (
              <div className="propChatAiSuggestion">
                <span className="propChatAiLabel">💡 AI suggested reply</span>
                <p className="propChatAiText">{escalation.suggested_reply}</p>
              </div>
            )}
          </div>

          {/* Chat messages */}
          <div className="propChatMessages">
            {messages.length === 0 && (
              <p className="propChatEmpty">
                Type your reply below. The system will auto-generate a guest-facing response from your answer.
              </p>
            )}
            {messages.map((msg, i) => (
              <div
                key={i}
                className={`propChatMsg ${
                  msg.is_guest_reply
                    ? "propChatMsg--guestReply"
                    : msg.sender === "property"
                    ? "propChatMsg--property"
                    : "propChatMsg--system"
                }`}
              >
                <span className="propChatMsgSender">
                  {msg.is_guest_reply ? "✅ Guest reply (auto-generated)" : msg.sender === "property" ? "🏨 Property" : "🤖 System"}
                </span>
                <p className="propChatMsgText">{msg.text}</p>
                <span className="propChatMsgTs">{msg.ts ? new Date(msg.ts).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : ""}</span>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>

          {/* Composer */}
          {messages.some((m) => m.is_guest_reply) ? (
            <div className="propChatDone">
              <span>✅ Guest reply sent to inbox</span>
              <button
                className="propChatResetBtn"
                type="button"
                onClick={() => { setMessages([]); setInput(""); }}
              >
                New reply
              </button>
            </div>
          ) : (
            <div className="propChatComposer">
              {error && <p className="propChatError">{error}</p>}
              <textarea
                className="propChatInput"
                rows={3}
                placeholder="Type your property team reply here…"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                disabled={sending}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendReply(); }
                }}
              />
              <button
                className="propChatSendBtn"
                type="button"
                disabled={sending || !input.trim()}
                onClick={sendReply}
              >
                {sending ? "Generating…" : "Send Reply →"}
              </button>
            </div>
          )}
        </>
      )}
    </aside>
  );
}
