import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

const INITIAL_MESSAGE = {
  who: "agent",
  text: 'Ask me about anything that\'s already been analyzed - e.g. "Which columns in this table need review?" or "Summarize the last run." I only read from the metadata store, I can\'t change a verdict or run a new analysis myself.',
};

export default function QueryAgentChat({ selectedTable }) {
  const [messages, setMessages] = useState([INITIAL_MESSAGE]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const logRef = useRef(null);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [messages]);

  async function askAgent() {
    const question = input.trim();
    if (!question) return;

    setMessages((prev) => [...prev, { who: "user", text: question }, { who: "agent", text: "Thinking...", thinking: true }]);
    setInput("");
    setBusy(true);

    try {
      const data = await api.askAgent(question, selectedTable);
      setMessages((prev) => {
        const next = prev.filter((m) => !m.thinking);
        return [...next, { who: "agent", text: data.answer }];
      });
    } catch (err) {
      setMessages((prev) => {
        const next = prev.filter((m) => !m.thinking);
        return [...next, { who: "agent", text: "Error reaching the query agent: " + err.message }];
      });
    } finally {
      setBusy(false);
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Enter") askAgent();
  }

  return (
    <section>
      <h2>Ask the platform (Conversational Query Agent)</h2>
      <div id="chatPanel">
        <div id="chatLog" ref={logRef}>
          {messages.map((m, i) => (
            <div key={i} className={`chatMsg ${m.who}`}>
              <div className="who">{m.who === "user" ? "You" : "Agent"}</div>
              {/* Rendered as text, never HTML - agent output is never trusted as markup */}
              <div className="bubble">{m.text}</div>
            </div>
          ))}
        </div>
        <div className="chatRow">
          <input
            type="text"
            id="chatInput"
            placeholder='e.g. "Which columns need review in the last run?"'
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button onClick={askAgent} disabled={busy}>Ask</button>
        </div>
        <div className="agentNote">
          Read-only. Scoped to the table currently selected above, or all tables if none is selected.
        </div>
      </div>
    </section>
  );
}
