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
  const decisionValidation = response.decision_validation ?? null;
  const evidenceValidation = response.evidence_validation ?? null;

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

      {(decisionValidation || evidenceValidation) ? (
        <section className="tracePanelCard tracePanelCard--validation">
          <div className="traceHeader">
            <div>
              <p className="eyebrow">Validation Agent</p>
              <h3>Query Checks</h3>
            </div>
            <span className={`statusBadge ${
              [decisionValidation, evidenceValidation].every(v => !v || v.passed)
                ? "statusBadge--safe"
                : [decisionValidation, evidenceValidation].some(v => v?.status === "blocked")
                ? "statusBadge--blocked"
                : "statusBadge--warning"
            }`}>
              {[decisionValidation, evidenceValidation].every(v => !v || v.passed)
                ? "All passed"
                : [decisionValidation, evidenceValidation].some(v => v?.status === "blocked")
                ? "Blocked"
                : "Warnings"}
            </span>
          </div>

          <div className="validationStageGrid">
            {[
              { label: "Stage 1 — Decision", v: decisionValidation },
              { label: "Stage 2 — Evidence", v: evidenceValidation },
            ].map(({ label, v }) => v ? (
              <div key={label} className={`validationStageCard validationStageCard--${v.status}`}>
                <div className="validationStageTop">
                  <span className="validationStageIcon">
                    {v.passed ? "✓" : v.status === "warning" ? "⚠" : "✗"}
                  </span>
                  <div>
                    <p className="validationStageLabel">{label}</p>
                    <strong className={`validationStageResult validationStageResult--${v.status}`}>
                      {v.status.charAt(0).toUpperCase() + v.status.slice(1)}
                    </strong>
                  </div>
                </div>
                {v.blocking_issues?.length ? (
                  <div className="validationStageIssues">
                    {v.blocking_issues.map((issue, i) => (
                      <p key={i} className="validationStageIssue validationStageIssue--blocking">{issue}</p>
                    ))}
                  </div>
                ) : null}
                {v.warnings?.length ? (
                  <div className="validationStageIssues">
                    {v.warnings.slice(0, 2).map((w, i) => (
                      <p key={i} className="validationStageIssue validationStageIssue--warning">{w}</p>
                    ))}
                  </div>
                ) : null}
                {v.notes?.length ? (
                  <p className="validationStageNote">{v.notes[0]}</p>
                ) : null}
              </div>
            ) : null)}
          </div>
        </section>
      ) : null}

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

      <section className="tracePanelCard">
        <div className="traceHeader">
          <div>
            <p className="eyebrow">Agent Pipeline</p>
            <h3>Run Timeline</h3>
          </div>
          <span className="confidenceBadge">{(response.agent_trace || []).length} steps</span>
        </div>
        <div className="traceTimeline">
          {(response.agent_trace || []).map((step, index) => (
            <div className={`traceStep traceStep--${step.status?.replace(/[^a-z]/gi, "_") || "completed"}`} key={index}>
              <div className="traceDot" />
              <div className="traceStepBody">
                <div className="traceStepHeading">
                  <strong>{step.agent}</strong>
                  <span className={`traceStatusChip traceStatusChip--${step.status?.replace(/[^a-z]/gi, "_") || "completed"}`}>
                    {step.status || "completed"}
                  </span>
                </div>
                <p className="mutedCopy traceStepSummary">{step.summary}</p>
                {step.blocking_issues?.length ? (
                  <div className="traceIssueList">
                    {step.blocking_issues.map((issue, i) => (
                      <p key={i} className="traceIssue traceIssue--blocking">{issue}</p>
                    ))}
                  </div>
                ) : null}
                {step.warnings?.length ? (
                  <div className="traceIssueList">
                    {step.warnings.slice(0, 2).map((w, i) => (
                      <p key={i} className="traceIssue traceIssue--warning">{w}</p>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </section>

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
