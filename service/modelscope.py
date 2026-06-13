import json
import os
import urllib.request
import urllib.error

API_BASE = "https://modelscope.ai/openapi/v1"
LEGACY_BASE = "https://modelscope.cn/api/v1/models"

CHUNK_SIZE = 1024 * 1024


def search_models(keyword: str, page: int = 1, page_size: int = 20) -> dict:
    url = f"{API_BASE}/models?search={urllib.request.quote(keyword)}&page_number={page}&page_size={page_size}"
    req = urllib.request.Request(url, headers={"User-Agent": "llamacpp-gui/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success"):
                d = data["data"]
                return {
                    "models": d.get("models", []),
                    "total_count": d.get("total_count", 0),
                    "page": d.get("page_number", page),
                    "page_size": d.get("page_size", page_size),
                }
            return {"models": [], "total_count": 0, "page": 1, "page_size": page_size}
    except Exception as e:
        return {"models": [], "total_count": 0, "page": 1, "page_size": page_size, "error": str(e)}


def list_model_files(model_id: str) -> list[dict]:
    quoted_id = urllib.request.quote(model_id, safe="")
    url = f"{LEGACY_BASE}/{quoted_id}/repo/files?Recursive=True"
    req = urllib.request.Request(url, headers={"User-Agent": "llamacpp-gui/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("Code") == 200:
                files = data.get("Data", {}).get("Files", [])
                return [f for f in files if f.get("Type") == "blob"]
            return []
    except Exception:
        return []


def get_download_url(model_id: str, file_path: str, revision: str = "master") -> str:
    quoted_id = urllib.request.quote(model_id, safe="")
    quoted_path = urllib.request.quote(file_path, safe="")
    quoted_rev = urllib.request.quote(revision, safe="")
    return f"{LEGACY_BASE}/{quoted_id}/repo?Revision={quoted_rev}&FilePath={quoted_path}"


def download_file(url: str, dest_path: str, resume_pos: int = 0, chunk_callback=None):
    headers = {
        "User-Agent": "llamacpp-gui/1.0",
    }
    if resume_pos > 0:
        headers["Range"] = f"bytes={resume_pos}-"

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    mode = "ab" if resume_pos > 0 else "wb"

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        total = resume_pos
        if resume_pos == 0:
            content_length = resp.headers.get("Content-Length")
            if content_length:
                total = int(content_length)
        else:
            content_range = resp.headers.get("Content-Range", "")
            if "/" in content_range:
                total = int(content_range.split("/")[1])

        with open(dest_path, mode) as f:
            while True:
                chunk = resp.read(CHUNK_SIZE)
                if not chunk:
                    break
                f.write(chunk)
                resume_pos += len(chunk)
                if chunk_callback:
                    chunk_callback(resume_pos, total)

    return resume_pos, total
