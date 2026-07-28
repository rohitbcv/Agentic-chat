export function AgentSummaryCard({ agent }) {
  return (
    <article className="agentSummaryCard">
      <p className="eyebrow">{agent.name}</p>
      <p className="agentSummaryText">{agent.purpose}</p>
    </article>
  );
}
