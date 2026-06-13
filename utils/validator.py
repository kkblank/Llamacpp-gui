import os
import re


def validate_path(path):
    return os.path.exists(path) and os.path.isdir(path)


def validate_file(path):
    return os.path.exists(path) and os.path.isfile(path)


def validate_gguf(path):
    return validate_file(path) and path.lower().endswith(".gguf")


def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '_', name)
