import os
import subprocess


def validate_llamacpp_file(path):
    if not os.path.isfile(path):
        return False
    return os.path.basename(path).lower() == "llama-server.exe"


def validate_gguf_file(path):
    if not os.path.isfile(path):
        return False
    return path.lower().endswith(".gguf")
