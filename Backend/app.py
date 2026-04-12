from datetime import datetime, timezone

from bson import ObjectId
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()


from ml_engine import extract_text_from_file_storage, score_resumes

app = Flask(__name__)

CORS(app)

mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(mongo_uri)
db     = client["talentscreen"]      

jobs_col       = db["jobs"]          
candidates_col = db["candidates"]   

@app.route("/")
def index():
    return jsonify({ "status": "ResumeScreening backend is running ✓" })

@app.route("/api/create-job", methods=["POST"])
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


    scored = score_resumes(job["job_description"], resumes_dict)

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
    app.run(debug=True, port=5000)
