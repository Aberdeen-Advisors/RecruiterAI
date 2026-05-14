# Placeholder for emailer.py
@app.post("/send_welcome_email")
def send_welcome_email(candidate_email: str):
    # Placeholder – replace with Gmail API logic
    return {"status": "Email Sent", "to": candidate_email}
