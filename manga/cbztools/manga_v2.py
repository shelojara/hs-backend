from multiprocessing import Pool
import zipfile
import os
from PIL import Image, ImageChops
import shutil

from .utils import sort_nicely

# desired dimensions.
ratio = 1072 / 1448
WIDTH = int(1072 * ratio)
HEIGHT = int(1448 * ratio)
QUALITY = 70
WORKERS = 6


OUTPUT_DIR = "output"


def trim(image: Image.Image) -> Image.Image:
    bg = Image.new(image.mode, image.size, "white")
    diff = ImageChops.difference(image, bg)
    diff = ImageChops.add(diff, diff, 2.0, -100)
    bbox = diff.getbbox()

    if bbox:
        return image.crop(bbox)
    return image


def process_file(output_dir: str, filepath: str, index: int):
    _, ext = os.path.splitext(filepath)
    if ext not in [".jpg", ".jpeg", ".png"]:
        # unsupported file type.
        return

    output_path = os.path.join(output_dir, f"{index:05d}.jpg")

    image = trim(Image.open(filepath).convert("RGB"))
    width, height = image.size
    ratio = height / width
    image = image.resize((HEIGHT, int(HEIGHT * ratio)))

    image.save(output_path, optimize=True, quality=QUALITY)
    image.close()


def zip_output(output_dir: str):
    print("Creating archive...")

    shutil.make_archive(output_dir, "zip", output_dir)
    shutil.move(output_dir + ".zip", output_dir + ".cbz")


def process_manga(paths: list[str]) -> str:
    print("Starting format...")

    # clean previous execution stuff.
    try:
        os.remove(OUTPUT_DIR + ".cbz")
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
    except FileNotFoundError:
        pass

    os.mkdir(OUTPUT_DIR)

    for index, path in enumerate(paths):
        _process_manga_path(index, path)

    zip_output(OUTPUT_DIR)

    shutil.rmtree(OUTPUT_DIR)

    return OUTPUT_DIR + ".cbz"


def _process_manga_path(index: int, path: str):
    print(f"Starting format for {path}...")

    unzip_path = f"unzip_{index}"

    # extract zip file.
    with zipfile.ZipFile(path, "r") as zipr:
        zipr.extractall(unzip_path)

    # remove __MACOSX directory if any.
    shutil.rmtree(unzip_path + "/__MACOSX", ignore_errors=True)

    all_filepaths = []
    all_dirs = set()
    for root, _, files in os.walk(unzip_path):
        for file in files:
            all_filepaths.append(os.path.join(root, file))
            all_dirs.add(root)

    sort_nicely(all_filepaths)

    p = Pool(processes=WORKERS)
    for i, filepath in enumerate(all_filepaths):
        p.apply_async(process_file, (OUTPUT_DIR, filepath, i + 1000 * index))

    p.close()
    p.join()

    shutil.rmtree(unzip_path)
