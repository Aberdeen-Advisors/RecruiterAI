@app.post("/schedule_interview")
def schedule_interview(candidate_email: str, recruiter_email: str, time_slot: str):
    # Placeholder – replace with Google Calendar API logic
    return {"status": "Scheduled", "candidate": candidate_email, "time": time_slot}
