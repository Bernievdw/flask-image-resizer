from flask import Flask, render_template, request, send_file, redirect, url_for, flash
from PIL import Image, ImageOps, ImageFilter, UnidentifiedImageError
import os, zipfile, io, logging, sqlite3
from concurrent.futures import ThreadPoolExecutor
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin

try:
    from rembg import remove as rembg_remove
    REMBG_AVAILABLE = True
except Exception:
    REMBG_AVAILABLE = False

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "change-this-secret")  

UPLOAD_FOLDER = "static/uploads"
RESIZED_FOLDER = "static/resized"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESIZED_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["RESIZED_FOLDER"] = RESIZED_FOLDER

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "heic"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB per file
logging.basicConfig(level=logging.INFO)

DB_PATH = "image_history.db"

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

class User(UserMixin):
    def __init__(self, id_, username, password_hash):
        self.id = id_
        self.username = username
        self.password_hash = password_hash

    @staticmethod
    def get(user_id):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, username, password_hash FROM users WHERE id = ?", (int(user_id),))
        row = c.fetchone()
        conn.close()
        if row:
            return User(row[0], row[1], row[2])
        return None

    @staticmethod
    def get_by_username(username):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username,))
        row = c.fetchone()
        conn.close()
        if row:
            return User(row[0], row[1], row[2])
        return None

    @staticmethod
    def create(username, password):
        pwd_hash = generate_password_hash(password)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, pwd_hash))
        conn.commit()
        user_id = c.lastrowid
        conn.close()
        return User(user_id, username, pwd_hash)

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
    CREATE TABLE IF NOT EXISTS presets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT NOT NULL,
        width INTEGER,
        height INTEGER,
        format TEXT,
        lock_aspect INTEGER,
        quality INTEGER,
        filter TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password_hash TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def allowed_file(filename):
    ext = filename.rsplit('.', 1)[-1].lower()
    return ext in ALLOWED_EXTENSIONS

def save_history(user_id, original_name, resized_name, width, height, fmt):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO history (user_id, original_name, resized_name, width, height, format)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, original_name, resized_name, width, height, fmt))
    conn.commit()
    conn.close()

def get_history(user_id=None, limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if user_id:
        c.execute("SELECT original_name, resized_name, width, height, format, created_at FROM history WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
    else:
        c.execute("SELECT original_name, resized_name, width, height, format, created_at FROM history ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

def apply_filter(img, filter_name):
    """Apply filter to a PIL Image and return the result"""
    if not filter_name or filter_name == "none":
        return img
    if filter_name == "grayscale":
        return ImageOps.grayscale(img).convert("RGBA")
    if filter_name == "sepia":
        gray = ImageOps.grayscale(img)
        sep = Image.merge("RGB", [
            gray.point(lambda p: p * 240 / 255),
            gray.point(lambda p: p * 200 / 255),
            gray.point(lambda p: p * 145 / 255)
        ])
        return sep.convert("RGBA")
    if filter_name == "blur":
        return img.filter(ImageFilter.GaussianBlur(radius=2)).convert("RGBA")
    if filter_name == "sharpen":
        return img.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3)).convert("RGBA")
    return img

def simple_bg_remove(img):
    """
    Simple background removal by making near-white pixels transparent.
    Not perfect but works for many scanned photos / plain backgrounds.
    """
    img = img.convert("RGBA")
    datas = img.getdata()
    new_data = []
    for item in datas:
        r, g, b, a = item
        if r > 240 and g > 240 and b > 240:
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append(item)
    img.putdata(new_data)
    return img

def process_image(file, width, height, selected_format, quality, lock_aspect, prefix="",
                  resize_mode="stretch", background_color=None,
                  watermark_text=None, watermark_image=None,
                  filter_name=None, strip_metadata=False):
    previews = []
    try:
        original_path = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
        file.save(original_path)

        if os.path.getsize(original_path) > MAX_FILE_SIZE:
            raise ValueError(f"{file.filename} exceeds maximum size of 5MB.")

        img = Image.open(original_path)
        original_width, original_height = img.size

        # --- Resize logic (respect aspect ratio, crop, fit box, etc.)
        new_width, new_height = width, height
        if lock_aspect:
            if width and not height:
                new_height = int((width / original_width) * original_height)
            elif height and not width:
                new_width = int((height / original_height) * original_width)
            elif width and height:
                new_height = int((width / original_width) * original_height)

        # Resize
        resized_img = img.resize((new_width, new_height))

        # --- Apply filters ---
        if filter_name:
            from PIL import ImageFilter, ImageOps
            if filter_name == "grayscale":
                resized_img = ImageOps.grayscale(resized_img)
            elif filter_name == "sepia":
                sepia = ImageOps.colorize(ImageOps.grayscale(resized_img), "#704214", "#C0A080")
                resized_img = sepia
            elif filter_name == "blur":
                resized_img = resized_img.filter(ImageFilter.BLUR)
            elif filter_name == "sharpen":
                resized_img = resized_img.filter(ImageFilter.SHARPEN)

        # --- Apply watermark (text only for now) ---
        if watermark_text:
            from PIL import ImageDraw, ImageFont
            draw = ImageDraw.Draw(resized_img)
            font = ImageFont.load_default()
            draw.text((10, 10), watermark_text, fill="white", font=font)

        # --- Save output ---
        filename_no_ext = os.path.splitext(file.filename)[0]
        output_filename = f"{prefix}{filename_no_ext}_{new_width}x{new_height}.{selected_format.lower()}"
        resized_path = os.path.join(app.config["RESIZED_FOLDER"], output_filename)

        if strip_metadata:
            resized_img.save(resized_path, format=selected_format.upper(), quality=quality)
        else:
            exif = img.info.get("exif")
            resized_img.save(resized_path, format=selected_format.upper(), quality=quality, exif=exif)

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

def save_preset(user_id, name, width, height, format, lock_aspect, quality, filter_name):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        INSERT INTO presets (user_id, name, width, height, format, lock_aspect, quality, filter)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, name, width, height, format, int(lock_aspect), quality, filter_name))
    conn.commit()
    conn.close()

def get_presets(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, name, width, height, format, lock_aspect, quality, filter FROM presets WHERE user_id = ?", (user_id,))
    presets = c.fetchall()
    conn.close()
    return presets


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if not username or not password:
            flash("Username and password required", "danger")
            return redirect(url_for("register"))
        if User.get_by_username(username):
            flash("Username already exists", "warning")
            return redirect(url_for("register"))
        user = User.create(username, password)
        login_user(user)
        flash("Account created", "success")
        return redirect(url_for("index"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        user = User.get_by_username(username)
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash("Logged in", "success")
            return redirect(url_for("index"))
        flash("Invalid username or password", "danger")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out", "info")
    return redirect(url_for("index"))

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
    resize_mode = "stretch"
    compress_only = False
    preset = None
    watermark_text = None
    filter_name = "none"
    remove_bg = False

    history = get_history(current_user.id if current_user.is_authenticated else None, limit=8)

    if request.method == "POST":
        try:
            files = request.files.getlist("images")
            width = request.form.get("width")
            height = request.form.get("height")
            selected_format = request.form.get("format", "jpg")
            quality = int(request.form.get("quality", 80))
            lock_aspect = bool(request.form.get("lock_aspect"))
            prefix = request.form.get("prefix", "")
            resize_mode = request.form.get("resize_mode", "stretch")
            compress_only = bool(request.form.get("compress_only"))
            preset = request.form.get("preset")
            watermark_text = request.form.get("watermark_text")
            filter_name = request.form.get("filter", "none")
            remove_bg = bool(request.form.get("remove_bg"))

            watermark_file = request.files.get("watermark")
            watermark_path = None
            if watermark_file and watermark_file.filename != "":
                watermark_path = os.path.join(app.config["UPLOAD_FOLDER"], watermark_file.filename)
                watermark_file.save(watermark_path)

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
                    results.append(executor.submit(
                        process_image,
                        file, width, height,
                        selected_format, quality,
                        lock_aspect, prefix,
                        request.form.get("resize_mode", "stretch"),
                        request.form.get("background_color"),
                        request.form.get("watermark_text"),
                        None,  
                        request.form.get("filter_name"),
                        bool(request.form.get("strip_metadata"))
                    ))
                for future in results:
                    previews.extend(future.result())

            if zip_file:
                for _, resized_path in previews:
                    if resized_path:
                        zip_file.write(resized_path.lstrip("/"), arcname=os.path.basename(resized_path))
                zip_file.close()
                zip_buffer.seek(0)
                tmp_zip_path = os.path.join(app.config["RESIZED_FOLDER"], "resized_images.zip")
                with open(tmp_zip_path, "wb") as f:
                    f.write(zip_buffer.getvalue())
                zip_link = f"/{tmp_zip_path.replace(os.sep, '/')}"
            else:
                zip_link = None

            history = get_history(current_user.id if current_user.is_authenticated else None, limit=8)

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
        prefix=prefix,
        resize_mode=resize_mode,
        compress_only=compress_only,
        preset=preset,
        watermark_text=watermark_text,
        filter_name=filter_name,
        remove_bg=remove_bg,
        history=history,
        zip_link=zip_link if 'zip_link' in locals() else None
    )

if __name__ == "__main__":
    app.run(debug=True)
