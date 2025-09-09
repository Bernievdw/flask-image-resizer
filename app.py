from flask import Flask, render_template, request, send_from_directory
from PIL import Image
import os

app = Flask(__name__)

UPLOAD_FOLDER = "static/uploads"
RESIZED_FOLDER = "static/resized"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESIZED_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["RESIZED_FOLDER"] = RESIZED_FOLDER

@app.route("/", methods=["GET", "POST"])
def index():
    download_link = None
    error = None
    selected_format = "jpg"
    width = ""
    height = ""

    if request.method == "POST":
        try:
            file = request.files["image"]
            width = request.form.get("width", "")
            height = request.form.get("height", "")
            selected_format = request.form.get("format", "jpg")  # format dropdown
            width = int(width)
            height = int(height)

            if file:
                filepath = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
                file.save(filepath)
                img = Image.open(filepath)
                resized_img = img.resize((width, height))
                filename_no_ext = os.path.splitext(file.filename)[0]
                output_filename = f"{filename_no_ext}.{selected_format.lower()}"
                resized_path = os.path.join(app.config["RESIZED_FOLDER"], output_filename)
                resized_img.save(resized_path, format=selected_format.upper())
                download_link = f"/download/{output_filename}"

        except Exception as e:
            error = f"Something went wrong: {e}"

    return render_template(
        "index.html",
        download_link=download_link,
        error=error,
        selected_format=selected_format,
        width=width,
        height=height
    )

@app.route("/download/<filename>")
def download(filename):
    return send_from_directory(app.config["RESIZED_FOLDER"], filename, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True)
