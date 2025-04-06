import os
import hashlib
import pymongo
import pandas as pd
from flask import Flask, request, jsonify, send_file, redirect
from werkzeug.utils import secure_filename
from flask_cors import CORS  # Add this import

# Flask app setup
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# MongoDB connection
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["part_one"]
collection = db["one"]

#dict
url_cache = {}

# Base62 alphabet
BASE62_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

def base62_encode(num, alphabet=BASE62_ALPHABET):
    """Encodes an integer into Base62."""
    if num == 0:
        return alphabet[0]

    base62 = []
    while num:
        num, rem = divmod(num, 62)
        base62.append(alphabet[rem])
    return ''.join(reversed(base62))

def normalize_url(url):
    """Normalize URL by stripping spaces, trailing slashes, and converting to lowercase."""
    if url:
        return url.strip().rstrip('/').lower()
    return ""

def generate_short_url(long_url, domain="http://127.0.0.1:5000/"):
    """Generates a short URL from a long URL."""
    long_url = normalize_url(long_url)
    sha256_hash = hashlib.sha256(long_url.encode()).hexdigest()
    unique_id = int(sha256_hash[:16], 16)  # First 8 bytes = 64 bits
    base62_id = base62_encode(unique_id)
    short_url = f"{domain}{base62_id}"
    return sha256_hash[:8], base62_id, short_url

def store_in_mongo(long_url, sha256_hash, base62_id, short_url):
    """Stores the short URL and unique ID in MongoDB."""
    if not collection.find_one({"sha256_hash": sha256_hash}):
        data = {
            "sha256_hash": sha256_hash,
            "base62_id": base62_id,
            "short_url": short_url
        }
        collection.insert_one(data)

def process_uploaded_file(file_path):
    """Processes the uploaded Excel/CSV file and adds short URLs."""
    print(f"Processing file: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.csv':
        df = pd.read_csv(file_path)
    else:
        df = pd.read_excel(file_path, header=1)

    print("File loaded into pandas:", df.head())
    df.columns = df.columns.str.strip().str.lower()
    print("Normalized columns:", df.columns.tolist())

    if "long_url" not in df.columns:
        print("Error: 'long_url' column not found in the file")
        return None
    else:
        print("Column 'long_url' is present")

    def safe_generate(url):
        try:
            if pd.isna(url) or not isinstance(url, str):
                print(f"Skipping invalid URL: {url}")
                return None
            sha256_hash, base62_id, short_url = generate_short_url(url)
            store_in_mongo(url, sha256_hash, base62_id, short_url)
            url_cache[base62_id] = url
            return short_url
        except Exception as e:
            print(f"Error generating short URL for {url}: {e}")
            return None

    df["short_url"] = df["long_url"].apply(safe_generate)

    # Save processed file
    output_file = os.path.join(UPLOAD_FOLDER, "short_links.xlsx")
    df.to_excel(output_file, index=False)
    print(f"Short links saved to: {output_file}")

    return output_file

# Route: Upload File
@app.route("/upload", methods=["POST"])
def upload_file():
    """Handles file upload and processing."""
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(file_path)
    print(f"File saved to {file_path}")

    processed_file = process_uploaded_file(file_path)
    if processed_file:
        response = jsonify({"fileUrl": "http://127.0.0.1:5000/download"})
        print("Sending response:", response.get_data(as_text=True))  # Debug print
        return response, 200
    else:
        return jsonify({"error": "Failed to process file"}), 500

# Route: Download Processed File
@app.route("/download", methods=["GET"])
def download_file():
    """Serves the processed Excel file for download."""
    output_file = os.path.join(UPLOAD_FOLDER, "short_links.xlsx")
    if os.path.exists(output_file):
        return send_file(output_file, as_attachment=True)
    else:
        return jsonify({"error": "File not found"}), 404

# Route: Short URL Redirect
@app.route("/<short_code>")
def redirect_to_url(short_code):
    """Redirects to the original long URL."""
    long_url = url_cache.get(short_code)
    if long_url:
        return redirect(long_url, code=302)
    else:
        return "Short URL not found or expired from cache", 404

# Run the app
if __name__ == "__main__":
    app.run(debug=True)