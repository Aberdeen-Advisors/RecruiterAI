import os
import fitz  # PyMuPDF
from sentence_transformers import SentenceTransformer, util
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from openai import OpenAI
from pydantic import BaseModel
from dotenv import load_dotenv
from scipy.spatial.distance import cosine

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def get_embedding(text: str) -> List[float]:
    
    response = client.embeddings.create(
        input=text,
        model="text-embedding-3-large"
    )
    return response.data[0].embedding

def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    return " ".join([page.get_text() for page in doc])


def generate_fit_summary(job_description: str, resume_text: str, filename: str) -> str:
    prompt = f"""
You are a helpful recruiter assistant. You have just matched a resume against a job description. Based on the text below, briefly explain in 1–2 sentences why the applicant from "{filename}" may be a good fit.

Job Description:
{job_description}

Resume:
{resume_text[:2000]}  # limit input to avoid token overflow

Only return the summary — do not mention that you're an assistant or restate the prompt.
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a professional recruiting assistant."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )
    return response.choices[0].message.content.strip()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
'''
@app.post("/match_resumes")
def match_resumes(
    job_description: str = Form(...),         # ← MUST be from form
    resumes: List[UploadFile] = File(...)     # ← files from form too
):
    jd_embedding = model.encode(job_description, convert_to_tensor=True)
    results = []

    for file in resumes:
        content = file.file.read()
        with open(f"temp_{file.filename}", "wb") as f:
            f.write(content)
        text = extract_text_from_pdf(f"temp_{file.filename}")
        embedding = model.encode(text, convert_to_tensor=True)
        score = util.cos_sim(jd_embedding, embedding).item()
        results.append({"filename": file.filename, "score": round(score, 4)})
        os.remove(f"temp_{file.filename}")

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:3]
'''

@app.post("/match_resumes")
def match_resumes(
    job_description: str = Form(...),
    resumes: List[UploadFile] = File(...)
):
    jd_embedding = get_embedding(job_description)
    results = []

    '''
    for file in resumes:
        content = file.file.read()
        temp_path = f"temp_{file.filename}"
        with open(temp_path, "wb") as f:
            f.write(content)

        resume_text = extract_text_from_pdf(temp_path)
        resume_embedding = get_embedding(resume_text)
        similarity = 1 - cosine(jd_embedding, resume_embedding)
        results.append({"filename": file.filename, "score": round(similarity, 4)})

        os.remove(temp_path)
    '''

    for file in resumes:
        content = file.file.read()
        temp_path = f"temp_{file.filename}"
        with open(temp_path, "wb") as f:
            f.write(content)

        resume_text = extract_text_from_pdf(temp_path)
        resume_embedding = get_embedding(resume_text)
        similarity = 1 - cosine(jd_embedding, resume_embedding)

        try:
            fit_summary = generate_fit_summary(job_description, resume_text, file.filename)
        except Exception as e:
            fit_summary = "Summary generation failed."
            print(f"[ERROR] Summary generation for {file.filename}: {e}")

        results.append({
            "filename": file.filename,
            "score": round(similarity, 4),
            "summary": fit_summary
        })

        # print(f"{file.filename} → score: {similarity:.4f}\nSummary: {fit_summary}\n")

        os.remove(temp_path)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:3]


class QuestionRequest(BaseModel):
    job_description: str
    resume_text: str

@app.post("/generate_questions")
def generate_questions(request: QuestionRequest):
    job_description = request.job_description
    resume_filename = request.resume_text

    resume_path = f"data/resumes/{resume_filename}"  
    resume_text = extract_text_from_pdf(resume_path)


    prompt = f"""
    Based on the job description and the resume below, generate 5 tailored interview questions.

    Job Description:
    {job_description}

    Resume Summary:
    {resume_text}
    """

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful interview assistant."},
            {"role": "user", "content": prompt}
        ]
    )
    return {"questions": response.choices[0].message.content.strip().split("\n")}

