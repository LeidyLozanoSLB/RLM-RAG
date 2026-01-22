#!/usr/bin/env python3
"""Streamlit UI for inspecting the RLM RAG query flow.

Usage:
    streamlit run examples/streamlit_app.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from custom_rag.rlm import RLMConfig, RLMFilesystemRAG


load_dotenv()


def ensure_api_key() -> None:
    """Stop the app early if the OpenAI key is missing."""
    if not os.getenv("OPENAI_API_KEY"):
        st.error("OPENAI_API_KEY not set. Add it to .env before running.")
        st.stop()


def reset_state() -> None:
    rag = st.session_state.get("rag")
    if rag is not None:
        try:
            rag.close()
        except Exception:
            pass
    for key in (
        "rag",
        "rag_config",
        "prep_info",
        "prepared",
        "last_result",
        "last_docs_path",
    ):
        st.session_state.pop(key, None)


def get_rag(config: RLMConfig) -> RLMFilesystemRAG:
    config_dict = config.to_dict()
    rag = st.session_state.get("rag")
    if rag is None or st.session_state.get("rag_config") != config_dict:
        if rag is not None:
            try:
                rag.close()
            except Exception:
                pass
        rag = RLMFilesystemRAG(rlm_config=config)
        st.session_state["rag"] = rag
        st.session_state["rag_config"] = config_dict
        st.session_state["prepared"] = False
    return rag


def render_trace(trace: dict) -> None:
    steps = trace.get("steps", [])
    files = trace.get("files_accessed", [])

    st.write(f"Total steps: {trace.get('total_steps', len(steps))}")
    if files:
        st.write("Files accessed:")
        st.code("\n".join(sorted(files)))

    for step in steps:
        step_num = step.get("step", "?")
        status = "ok" if step.get("success") else "error"
        with st.expander(f"Step {step_num} ({status})"):
            if step.get("time") is not None:
                st.write(f"Time: {step['time']:.2f}s")
            if step.get("error"):
                st.error(step["error"])
            if step.get("code"):
                st.code(step["code"], language="python")
            if step.get("output"):
                st.code(step["output"])
            variables = step.get("variables") or []
            if variables:
                st.write(f"Variables set: {', '.join(variables)}")


def main() -> None:
    st.set_page_config(page_title="RLM RAG Inspector", layout="wide")
    st.title("RLM RAG Inspector")
    st.caption("Inspect question, steps, and actions during a RAG query.")

    ensure_api_key()

    root = Path(__file__).parent.parent
    default_docs = str(root / "data" / "manual_test")

    with st.sidebar:
        st.header("Setup")
        docs_path = st.text_input("Documents path", value=default_docs)
        force_prepare = st.checkbox("Force prepare", value=False)

        st.divider()
        st.subheader("RLM Config")
        security_mode = st.selectbox(
            "Security mode",
            options=["lite", "full"],
            index=0,
        )
        orchestrator_model = st.text_input("Orchestrator model", value="gpt-5-mini")
        worker_model = st.text_input("Worker model", value="gpt-5-nano")

        with st.expander("Advanced settings"):
            max_repl_steps = st.number_input("Max REPL steps", min_value=1, value=15)
            max_file_reads = st.number_input("Max file reads", min_value=1, value=12)
            max_sub_calls = st.number_input("Max sub calls", min_value=1, value=8)
            max_read_bytes = st.number_input("Max read bytes", min_value=1000, value=50000)
            max_read_lines = st.number_input("Max read lines", min_value=100, value=1000)
            max_tokens = st.number_input("Max tokens", min_value=1000, value=80000)
            small_corpus_threshold = st.number_input(
                "Small corpus threshold", min_value=1, value=10
            )
            chunk_size = st.number_input("Chunk size", min_value=100, value=1000)
            chunk_overlap = st.number_input("Chunk overlap", min_value=0, value=200)
            use_llm_summaries = st.checkbox("Use LLM summaries", value=True)
            use_llm_topics = st.checkbox("Use LLM topics", value=True)
            max_topics_per_doc = st.number_input(
                "Max topics per doc", min_value=1, value=5
            )
            log_level = st.selectbox(
                "Log level",
                options=["DEBUG", "INFO", "WARNING", "ERROR"],
                index=1,
            )

        if st.button("Reset session"):
            reset_state()
            st.success("Session reset.")

    if "last_docs_path" not in st.session_state:
        st.session_state["last_docs_path"] = docs_path
    if docs_path != st.session_state["last_docs_path"]:
        st.session_state["last_docs_path"] = docs_path
        st.session_state["prepared"] = False
        st.session_state["prep_info"] = None

    config = RLMConfig(
        security_mode=security_mode,
        orchestrator_model=orchestrator_model,
        worker_model=worker_model,
        max_repl_steps=int(max_repl_steps),
        max_file_reads=int(max_file_reads),
        max_sub_calls=int(max_sub_calls),
        max_read_bytes=int(max_read_bytes),
        max_read_lines=int(max_read_lines),
        max_tokens=int(max_tokens),
        small_corpus_threshold=int(small_corpus_threshold),
        chunk_size=int(chunk_size),
        chunk_overlap=int(chunk_overlap),
        use_llm_summaries=use_llm_summaries,
        use_llm_topics=use_llm_topics,
        max_topics_per_doc=int(max_topics_per_doc),
        log_level=log_level,
    )

    st.subheader("Preparation")
    if st.button("Prepare documents"):
        rag = get_rag(config)
        try:
            if not docs_path.strip():
                st.error("Documents path is required.")
            else:
                with st.spinner("Preparing documents..."):
                    prep_info = rag.prepare_documents(docs_path, force=force_prepare)
                st.session_state["prep_info"] = prep_info
                st.session_state["prepared"] = True
                st.success("Preparation complete.")
        except Exception as exc:
            st.session_state["prepared"] = False
            st.error(f"Preparation failed: {exc}")

    prep_info = st.session_state.get("prep_info")
    if prep_info:
        st.json(prep_info)

    st.subheader("Query")
    question = st.text_area("Question", height=120)
    top_k = st.number_input("Top K (simple mode only)", min_value=1, value=5)
    run_query = st.button("Run query")

    if run_query:
        rag = get_rag(config)
        try:
            if not question.strip():
                st.warning("Enter a question before running a query.")
            else:
                with st.spinner("Running query..."):
                    result = rag.query(question, top_k=int(top_k))
                st.session_state["last_result"] = result
        except Exception as exc:
            st.error(f"Query failed: {exc}")

    result = st.session_state.get("last_result")
    if result:
        st.subheader("Answer")
        st.write(result.get("answer", ""))

        metadata = result.get("metadata", {})
        sources = metadata.get("sources", [])
        token_usage = metadata.get("token_usage", {})

        st.subheader("Metadata")
        meta_cols = st.columns(4)
        meta_cols[0].metric(
            "Retrieval time (s)", f"{metadata.get('retrieval_time', 0.0):.2f}"
        )
        meta_cols[1].metric(
            "Generation time (s)", f"{metadata.get('generation_time', 0.0):.2f}"
        )
        meta_cols[2].write(f"Mode: {metadata.get('mode', 'rlm_agent')}")
        meta_cols[3].write(f"Security: {metadata.get('security_mode', security_mode)}")

        if metadata.get("confidence"):
            st.write(f"Confidence: {metadata['confidence']}")
        if sources:
            st.write(f"Sources: {', '.join(sources)}")
        if token_usage:
            st.write("Token usage:")
            st.json(token_usage)

        trace = metadata.get("trace")
        if trace:
            st.subheader("Trace")
            render_trace(trace)
            trace_json = json.dumps(trace, indent=2)
            st.download_button(
                "Download trace JSON",
                data=trace_json,
                file_name="rag_trace.json",
                mime="application/json",
            )
        else:
            st.info("No trace available for this run.")

        context = result.get("context")
        if context:
            with st.expander("Conversation context"):
                st.text_area(
                    "Context",
                    value="\n\n".join(context),
                    height=240,
                )

        with st.expander("Raw result JSON"):
            st.json(result)


if __name__ == "__main__":
    main()
