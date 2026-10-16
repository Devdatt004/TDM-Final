"""
agents/query_agent.py

Conversational Query Agent - Section 6.4 of the TDD, build item #1:
"Conversational Query Agent - lowest risk (read-only), useful as soon as
any real metadata exists."

What it is:
    A natural-language interface over what the platform has ALREADY
    discovered - profiling stats (null%, distinct count) and pattern/PHI
    classification verdicts (high_confidence / needs_review) - for
    whichever tables have been through POST /analyze.

What it deliberately does NOT do (Section 6.3 - "agents draft, humans
approve"):
    - It never writes to analysis_runs / column_results.
    - It never triggers a new /analyze run on your behalf.
    - It never approves or changes a verdict. If asked to, it says a
      human reviewer needs to do that.
    - It never touches hospital.db (or any source system) directly - its
      entire universe is the metadata store, i.e. the "materialized read"
      pattern already used by /summary and /results in api/main.py.

Why this is a good first agent to demo:
    Nothing new needs to be wired up in the source pipeline - it attaches
    to metadata that /analyze already produces. Run analysis on a table
    once, then you can ask this agent things like:
        "Which columns in this table need review?"
        "Summarize the last run."
        "Is there a column that looks like an SSN but wasn't flagged?"
"""

import os
from sqlalchemy.orm import Session

from metadata_store.models import AnalysisRun

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

# Keep the model name in one place so upgrading is a one-line change.
MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a read-only assistant for the TDM (Test Data \
Management) Platform. You answer questions about data-profiling and \
PHI/PII-classification results that have already been computed and stored \
in the metadata store.

Rules:
- Only use the metadata given to you below. Never invent columns, tables, \
patterns, or numbers that are not in the context provided.
- If the context doesn't contain enough information to answer, say so \
plainly and suggest running an analysis on the relevant table first \
(POST /analyze/{table_name}).
- You are read-only: you cannot change a classification, trigger a new \
analysis run, or approve anything. If asked to do one of those, say that \
a human reviewer needs to do it in the Review Workbench.
- Be concise and specific - reference actual column names and numbers from \
the context rather than speaking in generalities.
"""


def _gather_context(db: Session, table_name: str = None, max_runs: int = 5) -> str:
    """
    Render the relevant slice of the metadata store (analysis_runs +
    their column_results) as plain text for the LLM prompt.

    This function IS the agent's entire world - it can only ever answer
    based on what gets returned here, which is exactly what "read-only,
    attaches to existing layers" (Section 6.2) means in practice: no new
    database, no new source connector, just a read path over metadata
    that /analyze (api/main.py) already writes.
    """
    query = db.query(AnalysisRun)
    if table_name:
        query = query.filter(AnalysisRun.source_table == table_name)
    runs = query.order_by(AnalysisRun.run_timestamp.desc()).limit(max_runs).all()

    if not runs:
        scope = f"for table '{table_name}'" if table_name else "for any table"
        return f"No analysis runs found {scope}. Nothing has been analyzed yet."

    lines = []
    for run in runs:
        lines.append(
            f"\n--- Run #{run.id} | table: {run.source_table} | "
            f"{run.run_timestamp.isoformat()} | sample_size={run.sample_size} | "
            f"{run.high_confidence_count} high_confidence / "
            f"{run.needs_review_count} needs_review (of {run.total_fields} fields) ---"
        )
        for col in run.columns:
            lines.append(
                f"  - column={col.column_name} | pattern_type={col.pattern_type} | "
                f"pattern={col.pattern} | match={col.match_percentage}% | "
                f"null={col.null_percent}% | distinct={col.distinct_count} | "
                f"verdict={col.verdict}"
            )
    return "\n".join(lines)


def ask(db: Session, question: str, table_name: str = None) -> dict:
    """
    Answer a natural-language question using only what's in the metadata
    store. Returns both the answer AND the raw context used to produce it,
    so a reviewer can see exactly what the agent based its answer on -
    that traceability is the same governance instinct behind Section 6.3
    ("every agent-drafted proposal is versioned and logged"), scaled down
    to fit a read-only agent that doesn't produce a proposal at all.
    """
    context = _gather_context(db, table_name)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not Anthropic or not api_key:
        # Degrade gracefully rather than 500 - useful for a live demo where
        # the key might not be set on whichever machine is presenting.
        return {
            "answer": (
                "(No ANTHROPIC_API_KEY configured, so this is the raw "
                "metadata the agent would have reasoned over, unsummarized.)"
                f"\n\n{context}"
            ),
            "context_used": context,
        }

    client = Anthropic(api_key=api_key)
    message = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Metadata store contents:\n{context}\n\n"
                    f"Question: {question}"
                ),
            }
        ],
    )
    answer_text = "".join(
        block.text for block in message.content if getattr(block, "type", None) == "text"
    )
    return {"answer": answer_text, "context_used": context}


# ------------------------------------------------------------------
# Self-test: ask a question against whatever is already in
# metadata_store.db. Run `python agents/query_agent.py` from the
# "TDM Platform" root after you've run at least one /analyze call.
# ------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from metadata_store.db import SessionLocal

    db = SessionLocal()
    try:
        q = sys.argv[1] if len(sys.argv) > 1 else "What tables have been analyzed, and what needs review?"
        result = ask(db, q)
        print("\n--- Answer ---\n")
        print(result["answer"])
    finally:
        db.close()
