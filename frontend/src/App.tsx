import React, { useState, useRef, useEffect } from "react";
import axios from "axios";

type AgentStep = { tool: string; input: string; output: string };
type ChatMessage = { role: "user" | "agent"; text: string; steps: AgentStep[] };

function App() {
  const [jobDescription, setJobDescription] = useState("");
  const [resumes, setResumes] = useState<FileList | null>(null);
  const [topCandidates, setTopCandidates] = useState<any[]>([]);
  const [questions, setQuestions] = useState<string[]>([]);
  const [candidateEmail, setCandidateEmail] = useState("");
  const [recruiterEmail, setRecruiterEmail] = useState("");
  const [interviewTime, setInterviewTime] = useState("");
  const [progress, setProgress] = useState(0);
  const [progressText, setProgressText] = useState("");
  const [loading, setLoading] = useState(false);
  const [generatingQuestionsFor, setGeneratingQuestionsFor] = useState<string | null>(null);

  // Agent chat state
  const [sessionId] = useState(() => crypto.randomUUID());
  const [agentInput, setAgentInput] = useState("");
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [agentStreaming, setAgentStreaming] = useState(false);
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set());
  const chatEndRef = useRef<HTMLDivElement>(null);

  const backendURL = "http://localhost:8000";

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory]);

  const handleUpload = async () => {
    if (!resumes || !jobDescription) return;
    setLoading(true);
    setProgress(10);
    setProgressText("Uploading and processing resumes...");

    const formData = new FormData();
    Array.from(resumes).forEach((file) => formData.append("resumes", file));
    formData.append("job_description", jobDescription);

    const interval = setInterval(() => {
      setProgress((prev) => {
        if (prev < 90) return prev + 10;
        clearInterval(interval);
        return prev;
      });
    }, 300);

    try {
      const res = await axios.post(`${backendURL}/match_resumes`, formData);
      setTopCandidates(res.data);
      setProgress(100);
      setProgressText("Matching complete.");
    } catch (err) {
      console.error("Resume matching failed:", err);
      setProgressText("Something went wrong.");
      setProgress(100);
    } finally {
      clearInterval(interval);
      setLoading(false);
      setTimeout(() => {
        setProgress(0);
        setProgressText("");
      }, 2000);
    }
  };

  const handleGenerateQuestions = async (filename: string) => {
    setGeneratingQuestionsFor(filename);
    try {
      const res = await axios.post(`${backendURL}/generate_questions`, {
        job_description: jobDescription,
        resume_text: filename,
      });
      setQuestions(res.data.questions);
    } catch (err) {
      console.error("Question generation failed:", err);
    } finally {
      setGeneratingQuestionsFor(null);
    }
  };

  const handleSchedule = async () => {
    await axios.post(`${backendURL}/schedule_interview`, {
      candidate_email: candidateEmail,
      recruiter_email: recruiterEmail,
      time_slot: interviewTime,
    });
  };

  const handleSendWelcomeEmail = async () => {
    await axios.post(`${backendURL}/send_welcome_email`, {
      candidate_email: candidateEmail,
    });
  };

  const handleAgentChat = async () => {
    const instruction = agentInput.trim();
    if (!instruction || agentStreaming) return;

    setAgentInput("");
    setChatHistory((prev) => [
      ...prev,
      { role: "user", text: instruction, steps: [] },
      { role: "agent", text: "", steps: [] },
    ]);
    setAgentStreaming(true);

    try {
      const response = await fetch(`${backendURL}/agent/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction, session_id: sessionId }),
      });

      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));

            if (event.type === "tool_start") {
              setChatHistory((prev) => {
                const updated = [...prev];
                const last = { ...updated[updated.length - 1] };
                last.steps = [...last.steps, { tool: event.tool, input: event.input, output: "" }];
                updated[updated.length - 1] = last;
                return updated;
              });
            } else if (event.type === "tool_end") {
              setChatHistory((prev) => {
                const updated = [...prev];
                const last = { ...updated[updated.length - 1] };
                const steps = [...last.steps];
                const idx = steps.length - 1;
                if (idx >= 0) steps[idx] = { ...steps[idx], output: event.output };
                last.steps = steps;
                updated[updated.length - 1] = last;
                return updated;
              });
            } else if (event.type === "token") {
              setChatHistory((prev) => {
                const updated = [...prev];
                const last = { ...updated[updated.length - 1] };
                last.text = last.text + event.content;
                updated[updated.length - 1] = last;
                return updated;
              });
            } else if (event.type === "done") {
              setChatHistory((prev) => {
                const updated = [...prev];
                const last = { ...updated[updated.length - 1] };
                if (!last.text) last.text = event.output;
                updated[updated.length - 1] = last;
                return updated;
              });
            } else if (event.type === "error") {
              setChatHistory((prev) => {
                const updated = [...prev];
                const last = { ...updated[updated.length - 1] };
                last.text = `Error: ${event.message}`;
                updated[updated.length - 1] = last;
                return updated;
              });
            }
          } catch {
            // ignore malformed SSE lines
          }
        }
      }
    } catch (err) {
      console.error("Agent chat failed:", err);
      setChatHistory((prev) => {
        const updated = [...prev];
        const last = { ...updated[updated.length - 1] };
        last.text = "Something went wrong connecting to the agent.";
        updated[updated.length - 1] = last;
        return updated;
      });
    } finally {
      setAgentStreaming(false);
    }
  };

  const toggleSteps = (index: number) => {
    setExpandedSteps((prev) => {
      const next = new Set(prev);
      next.has(index) ? next.delete(index) : next.add(index);
      return next;
    });
  };

  return (
    <div style={{ padding: 30, fontFamily: "Arial, sans-serif", maxWidth: 860, margin: "auto" }}>
      <img
        src="/AberdeenLogo.png"
        alt="Company Logo"
        style={{ maxHeight: 60, height: "auto", width: "auto", objectFit: "contain" }}
      />
      <h1 style={{ fontSize: 28, margin: 20 }}>RecruitAI – Aberdeen's GenAI Recruitment Tool</h1>

      {/* ── Manual pipeline ── */}
      <textarea
        placeholder="Paste job description"
        rows={5}
        value={jobDescription}
        onChange={(e) => setJobDescription(e.target.value)}
        style={{ width: "100%", marginBottom: 10, padding: 10, borderRadius: 6, border: "1px solid #ccc" }}
      />

      <input type="file" multiple onChange={(e) => setResumes(e.target.files)} style={{ marginBottom: 10 }} />
      <button onClick={handleUpload} style={{ marginBottom: 20 }}>Match Resumes</button>

      {(!resumes || resumes.length === 0) && !jobDescription && (
        <p style={{ color: "red", fontWeight: "bold" }}>Please upload resumes and enter a job description.</p>
      )}

      {loading && (
        <div style={{ marginTop: 20 }}>
          <p style={{ color: "green", fontWeight: "bold", marginBottom: 8 }}>Matching resumes...</p>
          <div style={{ width: "100%", backgroundColor: "#f0f0f0", height: 12, borderRadius: 6 }}>
            <div
              style={{
                width: `${progress}%`,
                backgroundColor: "#3498db",
                height: "100%",
                borderRadius: 6,
                transition: "width 0.5s ease-in-out",
              }}
            />
          </div>
          <p style={{ fontStyle: "italic", marginTop: 8, color: "#333" }}>{progressText || "Processing..."}</p>
        </div>
      )}

      {topCandidates.length > 0 && (
        <div style={{ marginTop: 30 }}>
          {topCandidates.map((c) => (
            <div
              key={c.filename}
              style={{
                border: "1px solid #ccc",
                borderRadius: 10,
                padding: 15,
                marginBottom: 15,
                backgroundColor: "#fafafa",
                boxShadow: "0 2px 5px rgba(0,0,0,0.05)",
              }}
            >
              <strong>{c.filename}</strong> – Score: <span style={{ color: "#3498db" }}>{c.score}</span>
              <p style={{ fontStyle: "italic", marginTop: 8 }}>{c.summary}</p>
              <button onClick={() => handleGenerateQuestions(c.filename)}>Generate Questions</button>
              {generatingQuestionsFor === c.filename && <p style={{ color: "green" }}>Generating questions...</p>}
            </div>
          ))}
        </div>
      )}

      {questions.length > 0 && (
        <div style={{ marginTop: 30, padding: 20, backgroundColor: "#f9f9f9", border: "1px solid #ccc", borderRadius: 8 }}>
          <h3 style={{ color: "#2c3e50" }}>Recommended Interview Questions</h3>
          {questions
            .filter((q) => q.trim() !== "")
            .map((q, i) => (
              <div key={i} style={{ marginBottom: 16 }}>
                <strong>Q{i + 1}.</strong>
                <p style={{ margin: "4px 0 0 0" }}>{q.replace(/^\d+\.\s*/, "")}</p>
              </div>
            ))}
        </div>
      )}

      <div style={{ marginTop: 30, padding: 20, backgroundColor: "#f9f9f9", border: "1px solid #ccc", borderRadius: 8 }}>
        <h3 style={{ marginBottom: 10 }}>Schedule Interview</h3>
        <input
          placeholder="Candidate Email"
          value={candidateEmail}
          onChange={(e) => setCandidateEmail(e.target.value)}
          style={{ marginBottom: 10, width: "100%", padding: 8 }}
        />
        <input
          placeholder="Recruiter Email"
          value={recruiterEmail}
          onChange={(e) => setRecruiterEmail(e.target.value)}
          style={{ marginBottom: 10, width: "100%", padding: 8 }}
        />
        <input
          placeholder="Interview Time (e.g., 2025-06-18T15:00:00)"
          value={interviewTime}
          onChange={(e) => setInterviewTime(e.target.value)}
          style={{ marginBottom: 10, width: "100%", padding: 8 }}
        />
        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={handleSchedule}>Schedule</button>
          <button onClick={handleSendWelcomeEmail}>Send Welcome Email</button>
        </div>
      </div>

      {/* ── Agent chat panel ── */}
      <div
        style={{
          marginTop: 40,
          border: "2px solid #3498db",
          borderRadius: 12,
          overflow: "hidden",
          boxShadow: "0 4px 12px rgba(52,152,219,0.15)",
        }}
      >
        {/* Header */}
        <div style={{ backgroundColor: "#3498db", padding: "14px 20px", display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 20 }}>🤖</span>
          <div>
            <div style={{ color: "#fff", fontWeight: "bold", fontSize: 16 }}>AI Recruiting Agent</div>
            <div style={{ color: "rgba(255,255,255,0.8)", fontSize: 12 }}>
              Powered by GPT-4o · remembers this session's context
            </div>
          </div>
        </div>

        {/* Hint when no resumes uploaded */}
        {topCandidates.length === 0 && (
          <div style={{ padding: "10px 20px", backgroundColor: "#fff8e1", borderBottom: "1px solid #ffe082", fontSize: 13, color: "#795548" }}>
            Tip: Upload resumes and run "Match Resumes" first so the agent can access candidate data.
          </div>
        )}

        {/* Message history */}
        <div
          style={{
            height: 400,
            overflowY: "auto",
            padding: 20,
            backgroundColor: "#fafafa",
            display: "flex",
            flexDirection: "column",
            gap: 16,
          }}
        >
          {chatHistory.length === 0 && (
            <div style={{ color: "#aaa", fontStyle: "italic", textAlign: "center", marginTop: 80 }}>
              Try: "Find the top 3 candidates and generate questions for the best match"
            </div>
          )}

          {chatHistory.map((msg, idx) => (
            <div key={idx} style={{ display: "flex", flexDirection: "column", alignItems: msg.role === "user" ? "flex-end" : "flex-start" }}>
              {/* Bubble */}
              <div
                style={{
                  maxWidth: "80%",
                  padding: "10px 14px",
                  borderRadius: msg.role === "user" ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
                  backgroundColor: msg.role === "user" ? "#3498db" : "#fff",
                  color: msg.role === "user" ? "#fff" : "#222",
                  border: msg.role === "agent" ? "1px solid #ddd" : "none",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
                  whiteSpace: "pre-wrap",
                  lineHeight: 1.5,
                }}
              >
                {msg.role === "agent" && msg.text === "" && agentStreaming ? (
                  <span style={{ color: "#999", fontStyle: "italic" }}>Thinking...</span>
                ) : (
                  msg.text
                )}
              </div>

              {/* Tool steps (agent messages only) */}
              {msg.role === "agent" && msg.steps.length > 0 && (
                <div style={{ maxWidth: "80%", marginTop: 6 }}>
                  <button
                    onClick={() => toggleSteps(idx)}
                    style={{
                      background: "none",
                      border: "none",
                      color: "#3498db",
                      cursor: "pointer",
                      fontSize: 12,
                      padding: 0,
                    }}
                  >
                    {expandedSteps.has(idx) ? "▲ Hide" : "▼ Show"} {msg.steps.length} tool call{msg.steps.length !== 1 ? "s" : ""}
                  </button>

                  {expandedSteps.has(idx) && (
                    <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 6 }}>
                      {msg.steps.map((step, si) => (
                        <div
                          key={si}
                          style={{
                            backgroundColor: "#f0f4f8",
                            border: "1px solid #d0dbe7",
                            borderRadius: 8,
                            padding: "8px 12px",
                            fontSize: 12,
                            fontFamily: "monospace",
                          }}
                        >
                          <div style={{ color: "#2980b9", fontWeight: "bold", marginBottom: 2 }}>
                            Tool: {step.tool}
                          </div>
                          <div style={{ color: "#555", marginBottom: step.output ? 4 : 0 }}>
                            Input: {step.input}
                          </div>
                          {step.output && (
                            <div style={{ color: "#27ae60" }}>
                              Output: {step.output}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
          <div ref={chatEndRef} />
        </div>

        {/* Input area */}
        <div
          style={{
            display: "flex",
            gap: 8,
            padding: 14,
            borderTop: "1px solid #e0e0e0",
            backgroundColor: "#fff",
          }}
        >
          <input
            placeholder="Ask the agent… e.g. 'Who are the top candidates?'"
            value={agentInput}
            onChange={(e) => setAgentInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleAgentChat()}
            disabled={agentStreaming}
            style={{
              flex: 1,
              padding: "10px 14px",
              borderRadius: 8,
              border: "1px solid #ccc",
              fontSize: 14,
              outline: "none",
            }}
          />
          <button
            onClick={handleAgentChat}
            disabled={agentStreaming || !agentInput.trim()}
            style={{
              padding: "10px 20px",
              backgroundColor: agentStreaming || !agentInput.trim() ? "#b0c4d8" : "#3498db",
              color: "#fff",
              border: "none",
              borderRadius: 8,
              cursor: agentStreaming || !agentInput.trim() ? "default" : "pointer",
              fontWeight: "bold",
              fontSize: 14,
            }}
          >
            {agentStreaming ? "..." : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default App;
