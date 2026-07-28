function SourcePill({ value }) {
  return <span className="sourcePill">{value}</span>;
}

export function TracePanel({ response }) {
  if (!response) {
    return (
      <aside className="tracePanelCard tracePanelCard--empty">
        <p className="eyebrow">Agent Run</p>
        <h3>Awaiting first question</h3>
        <p className="mutedCopy">
          Once you ask something, the panel will show the Router Agent decision,
          the chosen specialist, the SQL or knowledge sources used, and the
          read-only safety posture.
        </p>
      </aside>
    );
  }

  const route = response.route ?? {};
  const sqlPlan = response.sql_plan;
  const knowledgePlan = response.knowledge_plan;
  const sqlRows = sqlPlan?.rows ?? sqlPlan?.mock_rows ?? [];
  const context = response.context ?? {};
  const safety = response.safety ?? {};
  const auditEvent = response.audit_event ?? {};

  return (
    <aside className="tracePanelStack">
      <section className="tracePanelCard">
        <div className="traceHeader">
          <div>
            <p className="eyebrow">Active Route</p>
            <h3>{route.next_agent}</h3>
          </div>
          <span className="confidenceBadge">
            {(Number(route.confidence || 0) * 100).toFixed(0)}% confidence
          </span>
        </div>
        <p className="mutedCopy">{route.rationale}</p>
        <div className="routeMeta">
          <SourcePill value={`Intent: ${route.intent}`} />
          <SourcePill value={`Mode: ${response.mode}`} />
          <SourcePill value={`Support: ${route.support_level || response.capability_state || "unknown"}`} />
          {(route.retriever_modes || []).map((mode) => (
            <SourcePill key={mode} value={`${mode.toUpperCase()} path`} />
          ))}
          <SourcePill value="Read-only" />
        </div>
      </section>

      <section className="tracePanelCard">
        <p className="eyebrow">Grounding</p>
        <div className="contextGrid">
          <div className="miniStat">
            <span>Confidence</span>
            <strong>{context.confidence_label || "pending"}</strong>
          </div>
          <div className="miniStat">
            <span>Evidence</span>
            <strong>{context.evidence_count ?? 0}</strong>
          </div>
          <div className="miniStat">
            <span>Primary</span>
            <strong>{context.primary_retrieval || "none"}</strong>
          </div>
        </div>
        {(context.notes || []).length ? (
          <div className="noteList">
            {context.notes.slice(0, 3).map((note) => (
              <p key={note}>{note}</p>
            ))}
          </div>
        ) : null}
      </section>

      <section className="tracePanelCard">
        <div className="traceHeader">
          <div>
            <p className="eyebrow">Safety</p>
            <h3>{safety.status || "pending"}</h3>
          </div>
          <span className={`statusBadge ${safety.read_only ? "statusBadge--safe" : ""}`}>
            {safety.read_only ? "Read-only" : "Review"}
          </span>
        </div>
        <p className="mutedCopy">{safety.claim_policy}</p>
        <div className="routeMeta">
          <SourcePill value={`Audit: ${auditEvent.persisted ? "persisted" : "response-only"}`} />
          <SourcePill value={`State: ${safety.capability_state || "unknown"}`} />
        </div>
      </section>

      {/*
      <section className="tracePanelCard">
        <p className="eyebrow">Agent Timeline</p>
        <div className="traceTimeline">
          {(response.agent_trace || []).map((step) => (
            <div className="traceStep" key={step.agent}>
              <div className="traceDot" />
              <div className="traceStepBody">
                <div className="traceStepHeading">
                  <strong>{step.agent}</strong>
                  <span>{step.status}</span>
                </div>
                <p className="mutedCopy">{step.summary}</p>
              </div>
            </div>
          ))}
        </div>
      </section>
      */}

      {sqlPlan ? (
        <section className="tracePanelCard">
          <p className="eyebrow">SQL Plan</p>
          <div className="routeMeta">
            {(sqlPlan.tables || []).map((table) => (
              <SourcePill key={table} value={table} />
            ))}
          </div>
          <pre className="sqlPreview">
            <code>{sqlPlan.query}</code>
          </pre>
          <div className="mockTable">
            <div className="mockTableHeader">
              <span>Rows</span>
              <span>{sqlRows.length} rows</span>
            </div>
            {sqlRows.length ? (
              <div className="mockRows">
                {sqlRows.map((row, index) => (
                  <pre className="mockRowCard" key={index}>
                    <code>{JSON.stringify(row, null, 2)}</code>
                  </pre>
                ))}
              </div>
            ) : (
              <p className="mutedCopy">
                This route does not have row output yet, but the SQL strategy is
                still shown.
              </p>
            )}
          </div>
        </section>
      ) : null}

      {knowledgePlan ? (
        <section className="tracePanelCard">
          <p className="eyebrow">Knowledge Plan</p>
          <div className="knowledgeSources">
            {(knowledgePlan.sources || []).map((source, index) => (
              <article className="knowledgeSourceCard" key={`${source.table}-${index}`}>
                <strong>{source.title}</strong>
                <span>{source.table}</span>
                <p>{source.excerpt}</p>
              </article>
            ))}
          </div>
          {(knowledgePlan.matches || []).length ? (
            <div className="knowledgeMatches">
              <p className="eyebrow">Semantic matches</p>
              {knowledgePlan.matches.map((match) => (
                <article className="knowledgeMatchCard" key={match.media_id || match.label}>
                  <strong>{match.label}</strong>
                  <p>{match.fit}</p>
                </article>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}
    </aside>
  );
}
