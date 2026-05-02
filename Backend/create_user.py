import os
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv
from pymongo import MongoClient
from werkzeug.security import generate_password_hash

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))


USER_NAME  = "HR Admin"
USER_EMAIL = "admin@talentscreen.com"
USER_PASS  = "Admin@1234"


mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client    = MongoClient(mongo_uri)
db        = client["talentscreen"]
users_col = db["users"]


existing = users_col.find_one({"email": USER_EMAIL.lower()})
if existing:
    print(f"[!] User already exists: {USER_EMAIL}")
    print("    Delete the document from MongoDB or change the email above.")
    sys.exit(0)


user_doc = {
    "name":          USER_NAME,
    "email":         USER_EMAIL.lower(),
    "password_hash": generate_password_hash(USER_PASS),
    "role":          "admin",
    "created_at":    datetime.now(timezone.utc),
    "last_login":    None,
}

result = users_col.insert_one(user_doc)

print("=" * 50)
print("  HR User Created Successfully!")
print("=" * 50)
print(f"  Name     : {USER_NAME}")
print(f"  Email    : {USER_EMAIL}")
print(f"  Password : {USER_PASS}")
print(f"  _id      : {result.inserted_id}")
print("=" * 50)
print("  Open login page: Frontend/login.html")
print("=" * 50)
