# 🎯 TalentScreen: AI-Powered Resume Screening Engine

> An intelligent Applicant Tracking System (ATS) leveraging Natural Language Processing (NLP) to evaluate, score, and rank candidates based on semantic contextual matching.

---

## 📖 Problem Statement

Traditional Applicant Tracking Systems (ATS) rely on exact keyword matching, leading to two major inefficiencies in recruitment:
1. **Keyword Stuffing:** Unqualified candidates easily bypass filters by invisibly copying the job description into their resumes.
2. **Context Blindness:** Highly qualified candidates are incorrectly rejected due to the use of synonyms or alternative phrasing (e.g., "React.js" instead of "ReactJS").

**TalentScreen** addresses these limitations by evaluating the *semantic meaning* of a candidate's experience rather than relying on exact string matching.

---

## ⚙️ Methodology & Features

- **Semantic Vector Matching:** Utilizes the `all-MiniLM-L6-v2` transformer model to create dense vector embeddings of both the Job Description and Resumes, calculating cosine similarity for an accurate out-of-100 match score.
- **Dynamic Token Chunking:** Automatically segments large, multi-page PDF resumes into overlapping contextual chunks. This bypasses the standard 256-token limit of lightweight models, ensuring highly accurate evaluations.
- **Data Integrity & Anti-Cheat:** Implements self-similarity detection heuristics to automatically flag and reject "JD-as-Resume" uploads.
- **Secure HR Dashboard:** Features a session-based administrative portal with robust file-size limitations and encrypted credential storage.

---

## 🛠️ Technology Stack

| Layer | Technologies Used |
| :--- | :--- |
| **Machine Learning** | `sentence-transformers`, `scikit-learn`, `pdfplumber`, `nltk` |
| **Backend API** | Python, Flask, Werkzeug |
| **Database** | MongoDB (PyMongo) |
| **Frontend UI** | HTML5, CSS3, JavaScript (Fetch API) |

---

## 🚀 Execution Instructions for Evaluation

### 1. Environment Setup
Ensure Python 3.9+ is installed. Install the required dependencies:
```bash
pip install -r requirements.txt
```

### 2. Database Configuration
Create a `.env` file in the root directory to link your MongoDB database:
```ini
MONGO_URI="your_mongodb_connection_string"
SECRET_KEY="your_secure_secret_key"
```

### 3. Initialize Administrator
Generate the default administrative account (`admin@talentscreen.com` / `Admin@1234`):
```bash
cd Backend
python create_user.py
```

### 4. Launch the Engine
Start the local server:
```bash
python app.py
```
Access the dashboard via **http://127.0.0.1:5000/** in any modern web browser.
