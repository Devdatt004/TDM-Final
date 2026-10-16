import QueryAgentChat from "../components/QueryAgentChat.jsx";

export default function QueryAgentPage({ selectedTable }) {
  return (
    <>
      <div className="pageIntro">
        <h1>Query Agent</h1>
        <p className="subtitle">
          Read-only conversational agent - answers from metadata already in the store, never
          triggers a new analysis and never writes anything.
        </p>
      </div>
      <QueryAgentChat selectedTable={selectedTable} />
    </>
  );
}
