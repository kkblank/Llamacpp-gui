import os
import re
from datetime import datetime


class ScriptEntry:
    def __init__(self, name="", content="", model_path=""):
        self.name = name
        self.content = content
        self.saved_at = datetime.now().isoformat()
        self.model_path = model_path

    @staticmethod
    def sanitize_filename(name):
        name = re.sub(r'[<>:"/\\|?*]', '_', name)
        name = re.sub(r'\s+', '_', name).strip()
        return name or "unnamed"

    def save_to_file(self, scripts_dir):
        os.makedirs(scripts_dir, exist_ok=True)
        safe_name = self.sanitize_filename(self.name)
        bat_path = os.path.join(scripts_dir, f"{safe_name}.bat")
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(self.content.replace("\r\n", "\n").replace("\r", "\n"))
        return bat_path

    def to_dict(self):
        return {
            "name": self.name,
            "content": self.content,
            "saved_at": self.saved_at,
            "model_path": self.model_path,
        }

    @classmethod
    def from_dict(cls, d):
        entry = cls(
            name=d.get("name", ""),
            content=d.get("content", ""),
            model_path=d.get("model_path", ""),
        )
        entry.saved_at = d.get("saved_at", "")
        return entry
