from resume_matcher import app  # base FastAPI app
import agent  # registers /agent/chat route on app

# To run locally:
# cd backend && uvicorn main:app --reload