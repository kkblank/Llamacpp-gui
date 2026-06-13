import os
import json
from model.script import ScriptEntry
from config.config import SCRIPTS_DIR, SCRIPTS_CONFIG


class ScriptService:
    def __init__(self):
        self.scripts_dir = SCRIPTS_DIR
        self.config_file = SCRIPTS_CONFIG

    def save_script(self, entry):
        if not entry.name:
            return ""
        bat_path = entry.save_to_file(self.scripts_dir)
        self._sync_config()
        return bat_path

    def delete_script(self, name):
        safe_name = ScriptEntry.sanitize_filename(name)
        bat_path = os.path.join(self.scripts_dir, f"{safe_name}.bat")
        if os.path.exists(bat_path):
            os.remove(bat_path)
            self._sync_config()
            return True
        return False

    def load_scripts(self):
        scripts = []
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    entries = data.get("scripts", [])
                    for d in entries:
                        scripts.append(ScriptEntry.from_dict(d))
            except (json.JSONDecodeError, IOError):
                pass
        return scripts

    def load_script_content(self, name):
        safe_name = ScriptEntry.sanitize_filename(name)
        bat_path = os.path.join(self.scripts_dir, f"{safe_name}.bat")
        if os.path.exists(bat_path):
            with open(bat_path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def get_script_path(self, name):
        safe_name = ScriptEntry.sanitize_filename(name)
        return os.path.join(self.scripts_dir, f"{safe_name}.bat")

    def _sync_config(self):
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        entries = []
        if os.path.isdir(self.scripts_dir):
            for filename in os.listdir(self.scripts_dir):
                if filename.endswith(".bat"):
                    bat_path = os.path.join(self.scripts_dir, filename)
                    name = filename[:-4]
                    try:
                        with open(bat_path, "r", encoding="utf-8") as f:
                            content = f.read()
                    except IOError:
                        content = ""
                    entries.append({
                        "name": name,
                        "content": content,
                        "saved_at": "",
                        "model_path": "",
                    })
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump({"scripts": entries}, f, indent=4)
