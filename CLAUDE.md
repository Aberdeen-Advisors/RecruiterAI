# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

**Backend** (from `backend/`):
```bash
cd backend
uvicorn main:app --reload
# API available at http://localhost:8000
```

**Frontend** (from `frontend/`):
```bash
cd frontend
npm install
npm run dev
# UI available at http://localhost:5173
```

**Environment**: Create `backend/.env` with:
```
OPENAI_API_KEY=sk-your-key-here
```

**Python environment**:
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

There are no automated tests in this project.

## Architecture

The app has two independent processes that must both be running:

**Backend entry point**: `backend/main.py` imports the FastAPI `app` instance from `resume_matcher.py`, then imports `agent.py` as a side effect — `agent.py` registers the `/agent/chat` route on that same `app` object. The actual `uvicorn` target is `main:app`.

**Module responsibilities**:
- `resume_matcher.py` — owns the FastAPI `app` instance, the global `vector_db` (FAISS) and `docs_cache` state, PDF extraction, and the `/match_resumes` and `/generate_questions` REST endpoints
- `agent.py` — imports `resume_matcher` as `rm` to share `vector_db`, `docs_cache`, and `generate_fit_summary` directly; registers the `/agent/chat` streaming SSE endpoint; builds a per-session `AgentExecutor` with `ConversationBufferMemory` keyed by UUID
- `scheduler.py` / `emailer.py` — placeholder endpoints only; Google Calendar and Gmail integration is not implemented

**State sharing pattern**: `vector_db` and `docs_cache` live as module-level globals in `resume_matcher.py`. `agent.py` accesses them via `rm.vector_db` / `rm.docs_cache`. This means the agent can only match candidates after the recruiter has uploaded resumes through the `/match_resumes` form.

**RAG pipeline**: Uploaded PDFs → `fitz` text extraction → `RecursiveCharacterTextSplitter` (chunk size 500, overlap 100) → `OpenAIEmbeddings` → FAISS in-memory vector store → `RetrievalQA` chain with `ChatOpenAI(gpt-4o)`. Top 3 candidates are determined by which source documents appear in the retrieval results, not by a numeric score (the returned `score` field is hardcoded to `1.0`).

**Agent tools** (defined in `agent.py`): `list_resumes`, `match_candidates`, `generate_questions`, `schedule_interview`, `send_welcome_email`. The agent streams responses via SSE; the frontend parses `tool_start`, `tool_end`, `token`, `done`, and `error` event types.

**Frontend**: Single-component React app (`App.tsx`). All state lives in `App` — no router, no external state manager. The agent chat uses native `fetch` with a `ReadableStream` reader for SSE; all other calls use `axios`. Backend URL is hardcoded to `http://localhost:8000`.
