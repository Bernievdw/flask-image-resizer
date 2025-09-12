import os
import hashlib
from PIL import Image 

THUMB_DIR = "static/thumbnails"
os.makedirs(THUMB_DIR, exist_ok=True)

def get_thumbnail(image_path, size=(200, 200)):
    hash_key = hashlib.md5(image_path.encode()).hexdigest()
    thumb_path = os.path.join(THUMB_DIR, f"{hash_key}.jpg")

    if not os.path.exists(thumb_path):
        with Image.open(image_path) as img:
            img.thumbnail(size)
            img.save(thumb_path, "JPEG")

    return "/" + thumb_path.replace("\\", "/")
