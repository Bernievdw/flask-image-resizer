from flask import Flask, render_template, request, send_from_directory
from PIL import Image
import os

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
RESIZED_FOLDER = "resized"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESIZED_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["RESIZED_FOLDER"] = RESIZED_FOLDER


@app.route("/", methods=["GET", "POST"])
@app.route("/", methods=["GET", "POST"])
def index():
    download_link = None
    error = None

    if request.method == "POST":
        try:
            file = request.files["image"]
            width = int(request.form["width"])
            height = int(request.form["height"])

            if file:
                filepath = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
                file.save(filepath)

                img = Image.open(filepath)
                resized_img = img.resize((width, height))

                resized_path = os.path.join(app.config["RESIZED_FOLDER"], file.filename)
                resized_img.save(resized_path)

                download_link = f"/download/{file.filename}"
        except Exception as e:
            error = f"Something went wrong: {e}"

    return render_template("index.html", download_link=download_link, error=error)

@app.route("/download/<filename>")
def download(filename):
    return send_from_directory(app.config["RESIZED_FOLDER"], filename, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True)
