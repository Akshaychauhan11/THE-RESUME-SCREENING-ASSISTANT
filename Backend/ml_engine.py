import pdfplumber
import os
import re
import pandas as pd
import nltk
import pytesseract
from pdf2image import convert_from_path
from PIL import Image
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
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
    text = re.sub(r"[^a-z\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    tokens = word_tokenize(text)
    stop_words = set(stopwords.words('english'))
    lemmatizer = WordNetLemmatizer()
    tokens = [t for t in tokens if t not in stop_words and t.isalpha()]
    tokens = [lemmatizer.lemmatize(t, pos='v') for t in tokens]
    return " ".join(tokens)


def extract_text_from_pdf(pdf_path):
    text = ""

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + " "
    except:
        pass

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
    
    import tempfile
    filename = file_storage.filename
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        file_storage.save(tmp.name)
        tmp_path = tmp.name
    text = extract_text_from_pdf(tmp_path)
    os.unlink(tmp_path)
    return filename, text


def score_resumes(job_description, resumes_dict):
    
    if not resumes_dict:
        return []
    cleaned_job = preprocess(job_description)
    names       = list(resumes_dict.keys())
    cleaned_cvs = [preprocess(text) for text in resumes_dict.values()]
    raw_texts   = list(resumes_dict.values())
    all_docs     = [cleaned_job] + cleaned_cvs
    vectorizer   = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform(all_docs)
    scores = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:])[0]
    results = []
    for i, name in enumerate(names):
        score = round(float(scores[i]) * 100, 1)
        if score >= 70:
            level, verdict = "high", "Strong match"
        elif score >= 40:
            level, verdict = "medium", "Potential match"
        else:
            level, verdict = "low", "Weak match"
        results.append({
            "resume": name, "score": score, "level": level,
            "verdict": verdict, "raw_text": raw_texts[i][:2000],
        })
    results.sort(key=lambda x: x["score"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1
    return results
