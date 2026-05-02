from datetime import datetime, timezone
from functools import wraps

from bson import ObjectId
from flask import Flask, request, jsonify, session, redirect, send_file
from flask_cors import CORS
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
import os
from dotenv import load_dotenv

load_dotenv()

from ml_engine import extract_text_from_file_storage, score_resumes

app = Flask(__name__)


import secrets as _secrets
_secret_key = os.getenv("SECRET_KEY")
if not _secret_key:
    _secret_key = _secrets.token_hex(32)
    print("[WARNING] SECRET_KEY not found in .env — using a random temporary key.")
    print("[WARNING] Add SECRET_KEY=<a-long-random-string> to your .env file.")
app.secret_key = _secret_key

CORS(app, supports_credentials=True, origins=[
    "http://127.0.0.1:3002", 
    "http://localhost:3002",
    "http://127.0.0.1:5000",
    "http://localhost:5000"
])

app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB

@app.errorhandler(413)
def file_too_large(e):
    return jsonify({
        "error": "Upload too large. Maximum allowed size is 10 MB per request."
    }), 413

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return jsonify({'error': 'Authentication required.'}), 401
        return f(*args, **kwargs)
    return decorated

mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(mongo_uri)
db     = client["talentscreen"]      

jobs_col       = db["jobs"]          
candidates_col = db["candidates"]    
users_col      = db["users"]         



LOGIN_HTML   = os.path.join(os.path.dirname(__file__), "..", "Frontend", "login.html")
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "Frontend")


@app.route("/styles/<path:filename>")
def serve_styles(filename):
    return send_file(os.path.abspath(os.path.join(FRONTEND_DIR, "styles", filename)))

@app.route("/")
def index():
    if not session.get("user_id"):
        return redirect("/login")
    return send_file(os.path.abspath(os.path.join(FRONTEND_DIR, "index.html")))

@app.route("/<path:filename>")
def serve_html(filename):
    if filename.endswith(".html"):
        return send_file(os.path.abspath(os.path.join(FRONTEND_DIR, filename)))
    return "Not found", 404


@app.route("/login", methods=["GET"])
def login_page():
    if session.get("user_id"):
        return redirect("/")
    return send_file(os.path.abspath(LOGIN_HTML))




@app.route("/login", methods=["POST"])
def login_submit():
    data     = request.get_json(silent=True) or {}
    email    = (data.get("email")    or request.form.get("email",    "")).strip().lower()
    password = (data.get("password") or request.form.get("password", ""))
    remember = data.get("remember",  True)

    if not email or not password:
        return jsonify({ "error": "Email and password are required." }), 400

    user = users_col.find_one({ "email": email })

    if not user or not check_password_hash(user["password_hash"], password):
        print(f"[login] Failed attempt for: {email}")
        return jsonify({ "error": "Invalid email or password. Please try again." }), 401

    
    session.permanent = bool(remember)
    session["user_id"] = str(user["_id"])
    session["name"]    = user.get("name", email)
    session["email"]   = email

    users_col.update_one(
        { "_id": user["_id"] },
        { "$set": { "last_login": datetime.now(timezone.utc) } }
    )

    print(f"[login] Successful login: {email}")
    return jsonify({ "success": True, "name": session["name"] })


@app.route("/logout")
def logout():
    name = session.get("email", "unknown")
    session.clear()
    print(f"[logout] User logged out: {name}")
    return jsonify({"success": True})


@app.route("/api/me", methods=["GET"])
def get_me():
    if not session.get("user_id"):
        return jsonify({ "error": "Not authenticated." }), 401
    return jsonify({
        "user_id": session["user_id"],
        "name":    session["name"],
        "email":   session["email"],
    })


@app.route("/api/register", methods=["POST"])
def register():
    data  = request.get_json(silent=True) or {}
    name  = data.get("name",             "").strip()
    email = data.get("email",            "").strip().lower()
    pwd   = data.get("password",         "")
    cpwd  = data.get("confirm_password", "")

    
    if not name:
        return jsonify({ "error": "Full name is required." }), 400
    if not email or "@" not in email:
        return jsonify({ "error": "A valid email address is required." }), 400
    if len(pwd) < 6:
        return jsonify({ "error": "Password must be at least 6 characters." }), 400
    if pwd != cpwd:
        return jsonify({ "error": "Passwords do not match." }), 400

    
    if users_col.find_one({ "email": email }):
        return jsonify({ "error": "An account with this email already exists." }), 409

    
    user_doc = {
        "name":          name,
        "email":         email,
        "password_hash": generate_password_hash(pwd),
        "role":          "hr",
        "created_at":    datetime.now(timezone.utc),
        "last_login":    None,
    }
    result = users_col.insert_one(user_doc)
    print(f"[register] New user created: {email}  _id={result.inserted_id}")

    return jsonify({ "success": True, "message": "Account created! You can now sign in." })


@app.route("/api/create-job", methods=["POST"])
@login_required
def create_job():

    job_title       = request.form.get("job_title",       "").strip()
    job_description = request.form.get("job_description", "").strip()
    department      = request.form.get("department",      "").strip()
    key_skills      = request.form.get("key_skills",      "").strip()
    employment_type = request.form.get("employment_type", "Full-time").strip()

    if not job_title:
        return jsonify({ "error": "Job title is required." }), 400
    if not job_description:
        return jsonify({ "error": "Job description is required." }), 400

    job_doc = {
        "job_title":        job_title,
        "job_description":  job_description,
        "department":       department,
        "key_skills":       key_skills,
        "employment_type":  employment_type,
        "status":           "active",
        "resume_count":     0,           
        "top_score":        None,        
        "created_at":       datetime.now(timezone.utc),
    }

    result = jobs_col.insert_one(job_doc)

    print(f"[create-job] Saved job: '{job_title}'  _id={result.inserted_id}")

    return jsonify({
        "success": True,
        "job_id":  str(result.inserted_id)
    })

@app.route("/api/upload-resumes", methods=["POST"])
@login_required
def upload_resumes():
    job_id = request.form.get("job_id", "").strip()

    if not job_id:
        return jsonify({ "error": "job_id is missing." }), 400

    try:
        job = jobs_col.find_one({ "_id": ObjectId(job_id) })
    except Exception:
        return jsonify({ "error": "Invalid job_id format." }), 400

    if not job:
        return jsonify({ "error": f"No job found with id: {job_id}" }), 404

    
    uploaded_files = request.files.getlist("resumes")

    if not uploaded_files:
        return jsonify({ "error": "No resume files received." }), 400


    resumes_dict = {}   

    for file in uploaded_files:
        if not file.filename.lower().endswith(".pdf"):
            continue   

        filename, text = extract_text_from_file_storage(file)

        if text:
            resumes_dict[filename] = text
            print(f"  [OK] Extracted text from: {filename}")
        else:
            print(f"  [FAIL] No text extracted from: {filename} (scanned PDF?)")

    if not resumes_dict:
        return jsonify({ "error": "Could not extract text from any uploaded PDF. Are they scanned images?" }), 400

    jd_text = job["job_description"]
    if job.get("key_skills", "").strip():
        jd_text = jd_text + "\n" + job["key_skills"]

    scored = score_resumes(jd_text, resumes_dict)

    candidates_col.delete_many({ "job_id": job_id })

    docs_to_insert = []
    for c in scored:
        docs_to_insert.append({
            "job_id":      job_id,
            "job_title":   job["job_title"],
            "resume":      c["resume"],
            "score":       c["score"],
            "rank":        c["rank"],
            "level":       c["level"],
            "verdict":     c["verdict"],
            "raw_text":    c["raw_text"],
            "screened_at": datetime.now(timezone.utc),
        })

    candidates_col.insert_many(docs_to_insert)

    jobs_col.update_one(
        { "_id": ObjectId(job_id) },
        { "$set": {
            "resume_count": len(scored),
            "top_score":    scored[0]["score"] if scored else None,
        }}
    )

    print(f"[upload-resumes] Screened {len(scored)} resumes for job_id={job_id}")

    return jsonify({
        "success": True,
        "job_id":  job_id,
        "count":   len(scored),
    })

@app.route("/api/jobs/<job_id>/results", methods=["GET"])
@login_required
def get_results(job_id):
    
    try:
        job = jobs_col.find_one({ "_id": ObjectId(job_id) })
    except Exception:
        return jsonify({ "error": "Invalid job_id." }), 400

    if not job:
        return jsonify({ "error": "Job not found." }), 404

   
    cursor     = candidates_col.find({ "job_id": job_id }).sort("rank", 1)
    candidates = []

    for c in cursor:
        candidates.append({
            "_id":       str(c["_id"]),
            "job_id":    c["job_id"],
            "job_title": c.get("job_title", job["job_title"]),
            "resume":    c["resume"],
            "score":     c["score"],
            "rank":      c["rank"],
            "level":     c["level"],
            "verdict":   c["verdict"],
        })

    return jsonify({
        "job": {
            "_id":       str(job["_id"]),
            "job_title": job["job_title"],
            "status":    job.get("status", "active"),
        },
        "candidates": candidates,
    })

@app.route("/api/history", methods=["GET"])
@login_required
def get_history():
    
    cursor = jobs_col.find({}).sort("created_at", -1)
    jobs   = []

    for j in cursor:
        jobs.append({
            "_id":          str(j["_id"]),
            "job_title":    j["job_title"],
            "created_at":   j["created_at"].isoformat(),
            "resume_count": j.get("resume_count", 0),
            "top_score":    j.get("top_score"),
            "status":       j.get("status", "active"),
        })

    return jsonify(jobs)

@app.route("/api/candidates/<candidate_id>", methods=["GET"])
@login_required
def get_candidate(candidate_id):
    try:
        c = candidates_col.find_one({ "_id": ObjectId(candidate_id) })
    except Exception:
        return jsonify({ "error": "Invalid candidate_id." }), 400

    if not c:
        return jsonify({ "error": "Candidate not found." }), 404

    return jsonify({
        "_id":       str(c["_id"]),
        "job_id":    c["job_id"],
        "job_title": c.get("job_title", ""),
        "resume":    c["resume"],
        "score":     c["score"],
        "rank":      c["rank"],
        "level":     c["level"],
        "verdict":   c["verdict"],
        "raw_text":  c.get("raw_text", ""),
    })

if __name__ == "__main__":
    print("=" * 55)
    print("  TalentScreen backend starting…")
    print("  Open: http://127.0.0.1:5000")
    print("=" * 55)
    
    app.run(debug=False, port=5000)
