import os
import fitz
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from openai import OpenAI
from pydantic import BaseModel
from dotenv import load_dotenv
from langchain.vectorstores import FAISS
from langchain.embeddings import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
from langchain.chains import RetrievalQA
from langchain.chat_models import ChatOpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
embedding_model = OpenAIEmbeddings()
vector_db = None
docs_cache = []

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    return " ".join([page.get_text() for page in doc])

def generate_fit_summary(job_description: str, resume_text: str, filename: str) -> str:
    prompt = f"""
You are a helpful recruiter assistant. Briefly explain in 1–2 sentences why the applicant from "{filename}" is a good fit.

Job Description:
{job_description}

Resume:
{resume_text[:2000]}

Only return the summary.
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

@app.post("/match_resumes")
# Global FAISS vector store and docs cache
def match_resumes(
    job_description: str = Form(...),
    resumes: List[UploadFile] = File(...)
):
    global vector_db, docs_cache

    docs = []
    filenames = []

    for file in resumes:
        temp_path = f"temp_{file.filename}"
        with open(temp_path, "wb") as f:
            f.write(file.file.read())
        resume_text = extract_text_from_pdf(temp_path)
        docs.append(Document(page_content=resume_text, metadata={"source": file.filename}))
        filenames.append(file.filename)
        os.remove(temp_path)

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
    split_docs = splitter.split_documents(docs)

    # Only create the vector store if it doesn't exist or if new resumes are uploaded
    if vector_db is None or docs_cache != docs:
        vector_db = FAISS.from_documents(split_docs, embedding_model)
        docs_cache = docs.copy()

    retriever = vector_db.as_retriever(search_type="similarity", search_kwargs={"k": 3})

    qa = RetrievalQA.from_chain_type(
        llm=ChatOpenAI(model_name="gpt-4o"),
        retriever=retriever,
        return_source_documents=True
    )
    # Use the job description to query the vector store
    response = qa.invoke(job_description)
    matched_filenames = list({
        doc.metadata['source'] for doc in response["source_documents"]
    })

    results = []
    for fname in matched_filenames:
        doc = next(d for d in docs if d.metadata["source"] == fname)
        summary = generate_fit_summary(job_description, doc.page_content, fname)
        results.append({"filename": fname, "score": 1.0, "summary": summary})

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
    {resume_text[:1500]}
    """

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful interview assistant."},
            {"role": "user", "content": prompt}
        ]
    )
    return {"questions": response.choices[0].message.content.strip().split("\n")}