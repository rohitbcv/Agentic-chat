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
  const [leftTab, setLeftTab] = useState("samples");
  const messageListRef = useRef(null);

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
          confirm_ota_search: options.confirmOta === true,
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
          confirmationPrompt: data.confirmation_prompt === true,
          originalQuery: data.original_query || query,
          otaResults: data.ota_results || [],
          otaFetchedAt: data.ota_fetched_at || null,
          otaCheckIn: data.ota_check_in || null,
          otaCheckOut: data.ota_check_out || null,
          otaDateWarnings: data.ota_date_warnings || [],
          otaNameWarnings: data.ota_name_warnings || [],
          internalPricingFound: data.internal_pricing_found === true,
          internalPrices: data.internal_prices || [],
        },
      ]);
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally {
      setIsSending(false);
    }
  }

  // ── Left panel tab content ────────────────────────────────────────────────
  const LEFT_TABS = [
    { id: "samples",    label: "Samples" },
    { id: "validation", label: "Validation" },
    { id: "pricing",    label: "Pricing" },
    { id: "agents",     label: "Agents" },
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

        {/* Tab bar */}
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

        {/* Tab content */}
        <div className="leftTabContent">
          {leftTab === "samples" && (
            <div className="chipList">
              {(config?.sample_queries || []).map((q) => (
                <button className="queryChip" key={q} type="button" onClick={() => runQuery(q)}>
                  {q}
                </button>
              ))}
            </div>
          )}

          {leftTab === "validation" && (
            <div className="probeList">
              <p className="probeNote">Each probe targets a specific validation stage.</p>
              {(config?.validation_sample_queries || []).map((item) => (
                <button className="probeCard" key={item.query} type="button" onClick={() => runQuery(item.query)}>
                  <span className="probeLabel">{item.label}</span>
                  <span className="probeQuery">{item.query}</span>
                  {item.checks ? <span className="probeChecks">{item.checks}</span> : null}
                </button>
              ))}
            </div>
          )}

          {leftTab === "pricing" && (
            <div className="probeList">
              <p className="probeNote">Tests internal pricing + OTA confirmation flow.</p>
              {(config?.pricing_sample_queries || []).map((item) => (
                <button className="probeCard probeCard--pricing" key={item.query} type="button" onClick={() => runQuery(item.query)}>
                  <span className="probeLabel">{item.label}</span>
                  <span className="probeQuery">{item.query}</span>
                  {item.checks ? <span className="probeChecks">{item.checks}</span> : null}
                </button>
              ))}
            </div>
          )}

          {leftTab === "agents" && (
            <div className="agentCardList">
              {(config?.agents || []).map((agent) => (
                <AgentSummaryCard agent={agent} key={agent.name} />
              ))}
            </div>
          )}
        </div>
      </aside>

      {/* ── Main chat panel ── */}
      <main className="mainPanel">
        {/* Top bar */}
        <div className="mainTopBar">
          <div className="mainTopBarLeft">
            <span className="mainTopBarEyebrow">Analyst Console</span>
            <h3 className="mainTopBarTitle">Smart Community Inbox: Ask Anything, Get Answers</h3>
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

                {/* OTA confirmation */}
                {message.confirmationPrompt ? (
                  <div className="otaConfirmRow">
                    <span className="otaConfirmLabel">Check OTA platforms for live prices?</span>
                    <button
                      className="btnPrimary"
                      disabled={isSending}
                      type="button"
                      onClick={() => runQuery(message.originalQuery, { confirmOta: true })}
                    >
                      Yes, search OTA
                    </button>
                    <button
                      className="btnGhost"
                      disabled={isSending}
                      type="button"
                      onClick={() =>
                        setMessages((curr) =>
                          curr.map((m) => (m === message ? { ...m, confirmationPrompt: false } : m))
                        )
                      }
                    >
                      No thanks
                    </button>
                  </div>
                ) : null}

                {/* OTA results card */}
                {message.otaResults?.length ? (
                  <div className="otaCard">
                    <div className="otaCardHeader">
                      <span className="otaCardIcon">🌐</span>
                      <span className="otaCardTitle">Live OTA Prices</span>
                      <span className="otaCardBadge">SerpAPI · Google Hotels · USD</span>
                    </div>
                    <div className="otaCardMeta">
                      {message.otaCheckIn && message.otaCheckOut ? (
                        <span>📅 {message.otaCheckIn} → {message.otaCheckOut}</span>
                      ) : null}
                      {message.otaFetchedAt ? (
                        <span>🕐 {message.otaFetchedAt.slice(0, 16).replace("T", " ")} UTC</span>
                      ) : null}
                    </div>
                    {[...(message.otaDateWarnings || []), ...(message.otaNameWarnings || [])].map((w, i) => (
                      <div className="otaWarning" key={i}>⚠ {w}</div>
                    ))}
                    <div className="otaResultsList">
                      {message.otaResults.map((r, i) => (
                        <div className="otaResultRow" key={i}>
                          {/* Hotel header */}
                          <div className="otaResultHeader">
                            <div className="otaResultName">{r.name}</div>
                            <div className="otaResultMeta">
                              {r.rate_per_night ? <span className="otaRate">from {r.rate_per_night}/night USD</span> : null}
                              {r.rating ? <span className="otaRating">★ {r.rating}</span> : null}
                              {r.reviews ? <span className="otaReviews">{r.reviews} reviews</span> : null}
                            </div>
                            {(r.check_in_time || r.check_out_time) ? (
                              <div className="otaCheckTimes">
                                {r.check_in_time ? <span>Check-in: {r.check_in_time}</span> : null}
                                {r.check_out_time ? <span>Check-out: {r.check_out_time}</span> : null}
                              </div>
                            ) : null}
                          </div>

                          {/* Room categories — shown only when SerpAPI returned real room_type data */}
                          {r.room_categories?.length ? (
                            <div className="roomCategories">
                              <div className="roomCategoriesTitle">Available Room Types</div>
                              <div className="roomCategoriesGrid">
                                {r.room_categories.map((cat, ci) => (
                                  <div className="roomCategoryCard" key={ci}>
                                    <div className="roomCategoryHeader">
                                      <span className="roomCategoryName">{cat.room_type}</span>
                                      <span className="roomCategoryLowest">from {cat.lowest_rate} USD/night</span>
                                    </div>
                                    {cat.offers?.length ? (
                                      <div className="roomCategoryOffers">
                                        {cat.offers.map((offer, oi) => (
                                          <div className="roomCategoryOffer" key={oi}>
                                            <span className="roomOfferSource">{offer.source}</span>
                                            {offer.num_guests ? (
                                              <span className="roomOfferGuests">{offer.num_guests} guest{offer.num_guests > 1 ? "s" : ""}</span>
                                            ) : null}
                                            <span className="roomOfferRate">{offer.rate || "N/A"} USD</span>
                                            {offer.link ? (
                                              <a className="roomOfferLink" href={offer.link} target="_blank" rel="noopener noreferrer">Book</a>
                                            ) : null}
                                          </div>
                                        ))}
                                      </div>
                                    ) : null}
                                  </div>
                                ))}
                              </div>
                            </div>
                          ) : r.ota_prices?.length ? (
                            /* Flat OTA list — shown when SerpAPI does not return room_type breakdown.
                               Google Hotels exposes only the cheapest available room per platform. */
                            <div className="otaFlatList">
                              <div className="otaFlatNote">
                                Prices below are the lowest available room per platform
                              </div>
                              {r.ota_prices.map((p, j) => (
                                <div className="roomCategoryOffer" key={j}>
                                  <span className="roomOfferSource">{p.source}</span>
                                  {p.num_guests ? (
                                    <span className="roomOfferGuests">{p.num_guests} guest{p.num_guests > 1 ? "s" : ""}</span>
                                  ) : null}
                                  <span className="roomOfferRate">{p.rate || "N/A"} USD</span>
                                  {p.link ? (
                                    <a className="roomOfferLink" href={p.link} target="_blank" rel="noopener noreferrer">Book</a>
                                  ) : null}
                                </div>
                              ))}
                            </div>
                          ) : null}

                          {r.link ? (
                            <a className="otaLink" href={r.link} target="_blank" rel="noopener noreferrer">
                              View full hotel on OTA →
                            </a>
                          ) : null}
                        </div>
                      ))}
                    </div>
                    <div className="otaDisclaimer">All prices in USD · External market data, not confirmed internal rates</div>
                  </div>
                ) : null}

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
      </main>

      <TracePanel response={lastResponse} />
    </div>
  );
}
