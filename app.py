from flask import Flask, render_template, request, send_from_directory, send_file
from PIL import Image
import os, zipfile, io

app = Flask(__name__)

UPLOAD_FOLDER = "static/uploads"
RESIZED_FOLDER = "static/resized"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESIZED_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["RESIZED_FOLDER"] = RESIZED_FOLDER

@app.route("/", methods=["GET", "POST"])
def index():
    previews = []
    error = None
    width = ""
    height = ""
    selected_format = "jpg"
    zip_file = None

    if request.method == "POST":
        try:
            files = request.files.getlist("images")
            width = int(request.form["width"])
            height = int(request.form["height"])
            selected_format = request.form.get("format", "jpg")
            quality = int(request.form.get("quality", 80))

            if len(files) == 0:
                raise ValueError("No files uploaded.")

            if len(files) > 1:
                zip_buffer = io.BytesIO()
                zip_file = zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED)

            for file in files:
                if file:
                    original_path = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
                    file.save(original_path)

                    img = Image.open(original_path)
                    resized_img = img.resize((width, height))

                    filename_no_ext = os.path.splitext(file.filename)[0]
                    output_filename = f"{filename_no_ext}.{selected_format.lower()}"
                    resized_path = os.path.join(app.config["RESIZED_FOLDER"], output_filename)

                    resized_img.save(resized_path, format=selected_format.upper(), quality=quality)

                    previews.append((
                        f"/{original_path.replace(os.sep, '/')}",
                        f"/{resized_path.replace(os.sep, '/')}"
                    ))
                    if zip_file:
                        zip_file.write(resized_path, arcname=output_filename)

            if zip_file:
                zip_file.close()
                zip_buffer.seek(0)
                return send_file(zip_buffer, mimetype="application/zip", download_name="resized_images.zip", as_attachment=True)

        except Exception as e:
            error = f"Something went wrong: {e}"

    return render_template(
        "index.html",
        previews=previews,
        error=error,
        width=width,
        height=height,
        selected_format=selected_format
    )

if __name__ == "__main__":
    app.run(debug=True)
