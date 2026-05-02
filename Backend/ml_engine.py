import pdfplumber
import os
import re
import nltk
import pytesseract
from pdf2image import convert_from_path
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer
from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

pytesseract.pytesseract.tesseract_cmd = os.getenv("TESSERACT_CMD_PATH", r"C:\Program Files\Tesseract-OCR\tesseract.exe")

nltk.download('punkt',     quiet=True)
nltk.download('punkt_tab', quiet=True)
nltk.download('stopwords', quiet=True)
nltk.download('wordnet',   quiet=True)


def preprocess(text):
    text = text.lower()
    text = re.sub(r"[^\x00-\x7F]", " ", text)
 
    text = re.sub(r"[/\\]", " ", text)
    
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    tokens = word_tokenize(text)
    stop_words = set(stopwords.words('english'))
 
    stop_words -= {'no', 'not', 'without', 'never'}
    lemmatizer = WordNetLemmatizer()
    
    tokens = [t for t in tokens if t not in stop_words and t.isalnum()]
    
    tokens = [lemmatizer.lemmatize(t, pos='v') if t.isalpha() else t for t in tokens]
    return " ".join(tokens)


def keyword_overlap_score(cleaned_job, cleaned_resume):
    """
    PRECISION-based keyword overlap:
    "Of the skills the candidate listed, what fraction are relevant to the JD?"

    WHY PRECISION (not recall):
    - Recall = matched / JD_tokens  →  penalises resume for JD prose words
      like 'lifecycle', 'resilience', 'compliance' that only appear in the JD
      description, not in any well-written resume. Gives unfairly low scores.
    - Precision = matched / resume_tokens  →  asks "are the candidate's skills
      relevant?" which is the correct question for resume screening.

    Example (DevOps resume vs DevOps JD):
      Recall    = 36.1%  (penalised for missing JD prose words)
      Precision = 41.7%  (correctly shows strong skill alignment)
    """
   
    jd_tokens     = {t for t in cleaned_job.split()    if len(t) >= 3}
    resume_tokens = {t for t in cleaned_resume.split() if len(t) >= 3}
    if not resume_tokens:
        return 0.0
    matched = jd_tokens.intersection(resume_tokens)
    return len(matched) / len(resume_tokens)


def is_likely_resume(text):
    """Returns False if the text looks like a JD instead of a resume."""
    text_lower = text.lower()
    jd_phrases = [
        "we are looking for", "job description", "responsibilities include",
        "requirements:", "qualifications:", "about the role", "about the company",
        "what you will do", "what we offer", "we offer",
        "equal opportunity employer", "apply now", "to apply",
        "job summary", "position overview", "job responsibilities",
    ]
    has_email = bool(re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text))
    has_phone = bool(re.search(r'(\+?\d[\d\s\-\(\)]{7,}\d)', text))
    jd_flag_count = sum(1 for phrase in jd_phrases if phrase in text_lower)
    if jd_flag_count >= 2 and not has_email and not has_phone:
        return False
    return True



_embed_model = None

def _get_embed_model():
    """Lazy-load the sentence embedding model (only once per server session)."""
    global _embed_model
    if _embed_model is None:
        print("  [ML] Loading semantic model 'all-MiniLM-L6-v2' (first run only)...")
        _embed_model = SentenceTransformer('all-MiniLM-L6-v2')
        print("  [ML] Semantic model ready.")
    return _embed_model


def _encode_long_text(model, text, chunk_size=200, overlap=30):
    """Encode text in overlapping chunks to avoid the 256-token truncation limit."""
    import numpy as np
    words = text.split()
    if len(words) <= chunk_size:
        return model.encode([text], show_progress_bar=False)[0]
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
    if not chunks:
        return model.encode([text], show_progress_bar=False)[0]
    return model.encode(chunks, show_progress_bar=False).mean(axis=0)



def extract_text_from_pdf(pdf_path):
    text = ""

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + " "
    except Exception as e:
        print(f"  -> pdfplumber failed: {e}")

    
    if not text.strip():
        print(f"  → pdfplumber failed, trying OCR...")
        try:
            pages = convert_from_path(pdf_path, dpi=200)
            for page in pages:
                page_text = pytesseract.image_to_string(page)
                text += page_text + " "
            print(f"  → OCR succeeded!")
        except Exception as e:
            print(f"  → OCR also failed: {e}")

    return text.strip()

def extract_text_from_file_storage(file_storage):
    """Extract text from a Flask uploaded file object."""
    import tempfile
    filename = file_storage.filename
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            file_storage.save(tmp.name)
            tmp_path = tmp.name
        text = extract_text_from_pdf(tmp_path)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return filename, text


def score_resumes(job_description, resumes_dict):
    """Score resumes: 70% semantic similarity + 30% keyword precision."""
    if not resumes_dict:
        return []

    model       = _get_embed_model()
    names       = list(resumes_dict.keys())
    raw_texts   = list(resumes_dict.values())
    cleaned_job = preprocess(job_description)
    cleaned_cvs = [preprocess(text) for text in raw_texts]

    jd_emb = _encode_long_text(model, job_description).reshape(1, -1)

    results = []
    for i, name in enumerate(names):

       
        if not is_likely_resume(raw_texts[i]):
            print(f"  [{name}]  FLAGGED — looks like a Job Description, not a resume")
            results.append({
                "resume":   name,
                "score":    0.0,
                "level":    "invalid",
                "verdict":  "⚠️ Suspicious — document looks like a Job Description, not a resume",
                "raw_text": raw_texts[i][:2000],
            })
            continue

        resume_emb = _encode_long_text(model, raw_texts[i]).reshape(1, -1)

        
        sem_score = float(cosine_similarity(jd_emb, resume_emb)[0][0])

       
        kw_score  = keyword_overlap_score(cleaned_job, cleaned_cvs[i])

        combined  = 0.70 * sem_score + 0.30 * kw_score
        score     = round(combined * 100, 1)

        
        if score >= 92:
            print(f"  [{name}]  FLAGGED — suspiciously high score ({score}%), possible JD copy")
            results.append({
                "resume":   name,
                "score":    0.0,
                "level":    "invalid",
                "verdict":  "⚠️ Suspicious — document is too similar to the Job Description",
                "raw_text": raw_texts[i][:2000],
            })
            continue

        print(f"  [{name}]  semantic={sem_score*100:.1f}%  kw_precision={kw_score*100:.1f}%  combined={score}%")

        
        if score >= 55:
            level, verdict = "high",   "Strong match"
        elif score >= 38:
            level, verdict = "medium", "Potential match"
        else:
            level, verdict = "low",    "Weak match"

        results.append({
            "resume":   name,
            "score":    score,
            "level":    level,
            "verdict":  verdict,
            "raw_text": raw_texts[i][:2000],
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1
    return results
