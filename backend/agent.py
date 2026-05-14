import os
import json
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from langchain.agents import create_openai_functions_agent, AgentExecutor
from langchain.tools import tool
from langchain.memory import ConversationBufferMemory
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

import resume_matcher as rm
from resume_matcher import app

# Per-session conversation memory keyed by session UUID
session_memories: dict[str, ConversationBufferMemory] = {}


# ── Tools ──────────────────────────────────────────────────────────────────────

@tool
def list_resumes() -> str:
    """List all candidate resumes currently available in the system."""
    available: set[str] = set()
    for doc in rm.docs_cache:
        available.add(doc.metadata["source"])
    resumes_dir = "data/resumes"
    if os.path.isdir(resumes_dir):
        for f in os.listdir(resumes_dir):
            if f.lower().endswith(".pdf"):
                available.add(f)
    if not available:
        return "No resumes are loaded yet. Ask the recruiter to upload resumes via the form first."
    return "Available resumes:\n" + "\n".join(f"- {name}" for name in sorted(available))


@tool
def match_candidates(job_description: str) -> str:
    """Match all uploaded resumes against a job description and return the top 3 candidates with fit summaries."""
    if rm.vector_db is None:
        return "No resumes have been uploaded yet. The recruiter needs to upload resumes using the upload form first."

    from langchain.chains import RetrievalQA

    retriever = rm.vector_db.as_retriever(search_type="similarity", search_kwargs={"k": 3})
    qa = RetrievalQA.from_chain_type(
        llm=ChatOpenAI(model_name="gpt-4o"),
        retriever=retriever,
        return_source_documents=True,
    )
    response = qa.invoke(job_description)
    matched_filenames = list({doc.metadata["source"] for doc in response["source_documents"]})

    sections = []
    for fname in matched_filenames:
        doc = next((d for d in rm.docs_cache if d.metadata["source"] == fname), None)
        if doc:
            summary = rm.generate_fit_summary(job_description, doc.page_content, fname)
            sections.append(f"**{fname}**\n{summary}")

    if not sections:
        return "No matching candidates found."
    return "Top matching candidates:\n\n" + "\n\n".join(sections)


@tool
def generate_questions(filename: str, job_description: str) -> str:
    """Generate 5 tailored interview questions for a specific candidate. Pass their exact resume filename and the job description."""
    # Check in-memory cache first (fixes disk-read limitation for uploaded resumes)
    doc = next((d for d in rm.docs_cache if d.metadata["source"] == filename), None)
    if doc:
        resume_text = doc.page_content
    else:
        resume_path = f"data/resumes/{filename}"
        if not os.path.exists(resume_path):
            return f"Resume '{filename}' not found. Use list_resumes to see what's available."
        resume_text = rm.extract_text_from_pdf(resume_path)

    prompt = f"""Based on the job description and the resume below, generate 5 tailored interview questions.

Job Description:
{job_description}

Resume:
{resume_text[:2000]}
"""
    response = rm.client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful interview assistant."},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content.strip()


@tool
def schedule_interview(candidate_email: str, recruiter_email: str, time_slot: str) -> str:
    """Schedule an interview between a candidate and recruiter. time_slot should be ISO format, e.g. 2025-06-18T15:00:00."""
    return (
        f"Interview scheduled: {candidate_email} ↔ {recruiter_email} at {time_slot}. "
        "(Google Calendar integration pending — calendar invite would be sent here.)"
    )


@tool
def send_welcome_email(candidate_email: str) -> str:
    """Send a welcome email to a selected candidate informing them they have been chosen for an interview."""
    return (
        f"Welcome email sent to {candidate_email}. "
        "(Gmail integration pending — email would be delivered here.)"
    )


_tools = [list_resumes, match_candidates, generate_questions, schedule_interview, send_welcome_email]

_SYSTEM_PROMPT = (
    "You are RecruiterAI, Aberdeen's AI-powered recruiting assistant. "
    "You help recruiters screen candidates, generate interview questions, "
    "schedule interviews, and send candidate communications. "
    "Use the available tools to fulfill requests — never guess candidate names or details; "
    "always call the appropriate tool. When referencing a candidate from a previous step, "
    "use their exact resume filename as shown in tool results."
)


# ── Agent factory ──────────────────────────────────────────────────────────────

def build_agent(session_id: str) -> AgentExecutor:
    llm = ChatOpenAI(model_name="gpt-4o", streaming=True)

    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM_PROMPT),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad"),
    ])

    agent = create_openai_functions_agent(llm, _tools, prompt)

    memory = session_memories.setdefault(
        session_id,
        ConversationBufferMemory(return_messages=True, memory_key="chat_history"),
    )

    return AgentExecutor(agent=agent, tools=_tools, memory=memory, verbose=True)


# ── /agent/chat endpoint ───────────────────────────────────────────────────────

class AgentChatRequest(BaseModel):
    instruction: str
    session_id: str


@app.post("/agent/chat")
async def agent_chat(request: AgentChatRequest):
    agent_executor = build_agent(request.session_id)

    async def event_stream():
        try:
            async for event in agent_executor.astream_events(
                {"input": request.instruction},
                version="v1",
            ):
                kind = event["event"]

                if kind == "on_tool_start":
                    raw_input = event.get("data", {}).get("input", "")
                    tool_input = (
                        json.dumps(raw_input) if isinstance(raw_input, dict) else str(raw_input)
                    )
                    payload = {"type": "tool_start", "tool": event["name"], "input": tool_input}
                    yield f"data: {json.dumps(payload)}\n\n"

                elif kind == "on_tool_end":
                    raw_output = event.get("data", {}).get("output", "")
                    tool_output = str(raw_output)[:600]
                    payload = {"type": "tool_end", "tool": event["name"], "output": tool_output}
                    yield f"data: {json.dumps(payload)}\n\n"

                elif kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        payload = {"type": "token", "content": chunk.content}
                        yield f"data: {json.dumps(payload)}\n\n"

                elif kind == "on_chain_end" and event.get("name") == "AgentExecutor":
                    output_data = event.get("data", {}).get("output", {})
                    final = (
                        output_data.get("output", "") if isinstance(output_data, dict) else str(output_data)
                    )
                    payload = {"type": "done", "output": final}
                    yield f"data: {json.dumps(payload)}\n\n"

        except Exception as e:
            payload = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
