from collections import defaultdict
import zipfile
import os
from PIL import Image
import shutil

from .utils import is_image, make_cbz, sort_nicely

# desired dimensions.
WIDTH = 672
HEIGHT = 1448
QUALITY = 70


def process_manhwa_v3(paths: list[str], work_dir: str) -> str:
    print("Starting format...")

    output_dir = os.path.join(work_dir, "output")

    # remove output directory if it exists.
    shutil.rmtree(output_dir, ignore_errors=True)

    # remove output file if it exists.
    try:
        os.remove(output_dir + ".cbz")
    except FileNotFoundError:
        pass

    extracted_paths = []
    for path in paths:
        # extract zip file.
        with zipfile.ZipFile(path, "r") as zip_file:
            extract_path = os.path.join(
                output_dir, os.path.splitext(os.path.basename(path))[0]
            )
            zip_file.extractall(extract_path)
            extracted_paths.append(extract_path)

        # remove __MACOSX directory if any.
        shutil.rmtree(extract_path + "/__MACOSX", ignore_errors=True)

    filepaths_by_chapter = defaultdict(list)
    for extracted_path in extracted_paths:
        for root, _, files in os.walk(extracted_path):
            for file in files:
                filepaths_by_chapter[extracted_path].append(os.path.join(root, file))

    for chapter_path in filepaths_by_chapter:
        sort_nicely(filepaths_by_chapter[chapter_path])

    image_index = 0
    for chapter_path, filepaths in filepaths_by_chapter.items():
        images: list[Image.Image] = []
        for filepath in filepaths:
            if not is_image(filepath):
                continue

            image = Image.open(filepath)
            ratio = image.height / image.width
            image = image.resize((WIDTH, int(WIDTH * ratio)))
            images.append(image)

        # merge images.
        merged = Image.new("RGB", (WIDTH, sum([image.height for image in images])))
        offset = 0
        for image in images:
            merged.paste(image, (0, offset))
            offset += image.height
            image.close()

        # remove original files.
        shutil.rmtree(chapter_path, ignore_errors=True)

        # split merged image into pages.
        offset = 0
        while offset < merged.height:
            merged.crop((0, offset, WIDTH, offset + HEIGHT)).save(
                os.path.join(output_dir, f"merged.{image_index:04d}.jpg"),
                optimize=True,
                quality=QUALITY,
            )

            image_index += 1
            offset += HEIGHT * 0.8

        # close merged image.
        merged.close()

    make_cbz(output_dir)

    return output_dir + ".cbz"
