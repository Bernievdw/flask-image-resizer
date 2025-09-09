from flask import Flask, render_template, request, send_file
from PIL import Image, UnidentifiedImageError
import os, zipfile, io, logging, sqlite3
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

UPLOAD_FOLDER = "static/uploads"
RESIZED_FOLDER = "static/resized"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESIZED_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["RESIZED_FOLDER"] = RESIZED_FOLDER

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}
MAX_FILE_SIZE = 5 * 1024 * 1024 

logging.basicConfig(level=logging.INFO)

DB_PATH = "image_history.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_name TEXT,
            resized_name TEXT,
            width INTEGER,
            height INTEGER,
            format TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def allowed_file(filename):
    ext = filename.rsplit('.', 1)[-1].lower()
    return ext in ALLOWED_EXTENSIONS

def save_history(original_name, resized_name, width, height, fmt):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO history (original_name, resized_name, width, height, format)
        VALUES (?, ?, ?, ?, ?)
    ''', (original_name, resized_name, width, height, fmt))
    conn.commit()
    conn.close()

def process_image(file, width, height, selected_format, quality, lock_aspect, prefix=""):
    previews = []
    try:
        original_path = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
        file.save(original_path)

        if os.path.getsize(original_path) > MAX_FILE_SIZE:
            raise ValueError(f"{file.filename} exceeds maximum size of 5MB.")

        img = Image.open(original_path)
        original_width, original_height = img.size

        new_width, new_height = width, height
        if lock_aspect:
            if width and not height:
                new_height = int((width / original_width) * original_height)
            elif height and not width:
                new_width = int((height / original_height) * original_width)
            elif width and height:
                new_height = int((width / original_width) * original_height)

        resized_img = img.resize((new_width, new_height))
        filename_no_ext = os.path.splitext(file.filename)[0]
        output_filename = f"{prefix}{filename_no_ext}_{new_width}x{new_height}.{selected_format.lower()}"
        resized_path = os.path.join(app.config["RESIZED_FOLDER"], output_filename)
        resized_img.save(resized_path, format=selected_format.upper(), quality=quality)

        logging.info(f"Resized {file.filename} → {output_filename}")
        save_history(file.filename, output_filename, new_width, new_height, selected_format.upper())

        previews.append((
            f"/{original_path.replace(os.sep, '/')}",
            f"/{resized_path.replace(os.sep, '/')}"
        ))
    except UnidentifiedImageError:
        previews.append((None, None))
        logging.error(f"Cannot identify image file {file.filename}")
    except Exception as e:
        previews.append((None, None))
        logging.error(f"Error processing {file.filename}: {e}")
    return previews

@app.route("/", methods=["GET", "POST"])
def index():
    previews = []
    error = None
    width = ""
    height = ""
    selected_format = "jpg"
    zip_file = None
    lock_aspect = False
    prefix = ""

    if request.method == "POST":
        try:
            files = request.files.getlist("images")
            width = request.form.get("width")
            height = request.form.get("height")
            selected_format = request.form.get("format", "jpg")
            quality = int(request.form.get("quality", 80))
            lock_aspect = bool(request.form.get("lock_aspect"))
            prefix = request.form.get("prefix", "")

            if len(files) == 0:
                raise ValueError("No files uploaded.")

            width = int(width) if width else None
            height = int(height) if height else None

            for file in files:
                if not allowed_file(file.filename):
                    raise ValueError(f"{file.filename} has invalid file type.")

            if len(files) > 1:
                zip_buffer = io.BytesIO()
                zip_file = zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED)

            with ThreadPoolExecutor() as executor:
                results = []
                for file in files:
                    results.append(executor.submit(process_image, file, width, height,
                                                   selected_format, quality, lock_aspect, prefix))
                for future in results:
                    previews.extend(future.result())

            if zip_file:
                for _, resized_path in previews:
                    if resized_path:
                        zip_file.write(resized_path.lstrip("/"), arcname=os.path.basename(resized_path))
                zip_file.close()
                zip_buffer.seek(0)
                return send_file(zip_buffer, mimetype="application/zip",
                                 download_name="resized_images.zip", as_attachment=True)

        except Exception as e:
            error = f"Something went wrong: {e}"

    return render_template(
        "index.html",
        previews=previews,
        error=error,
        width=width,
        height=height,
        selected_format=selected_format,
        lock_aspect=lock_aspect,
        prefix=prefix
    )

if __name__ == "__main__":
    app.run(debug=True)
