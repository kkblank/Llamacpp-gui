import os
import json

# 路径常量
SCRIPTS_DIR = "data/scripts"
SCRIPTS_CONFIG = "data/scripts.json"
LAST_PID_FILE = "data/last_pid.pid"
APP_CONFIG_FILE = "data/app_config.json"
DOWNLOAD_DIR = "data/downloads"
DOWNLOAD_QUEUE_FILE = "data/downloads/queue.json"


class Settings:
    _instance = None

    def __init__(self):
        self.config = {
            "llamacpp_path": "",
            "model_path": "",
        }

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
            cls._instance.load()
        return cls._instance

    def load(self):
        if os.path.exists(APP_CONFIG_FILE):
            try:
                with open(APP_CONFIG_FILE, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

    def save(self):
        os.makedirs(os.path.dirname(APP_CONFIG_FILE), exist_ok=True)
        with open(APP_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=4)

    @property
    def llamacpp_path(self):
        return self.config.get("llamacpp_path", "")

    @llamacpp_path.setter
    def llamacpp_path(self, value):
        self.config["llamacpp_path"] = value

    @property
    def model_path(self):
        return self.config.get("model_path", "")

    @model_path.setter
    def model_path(self, value):
        self.config["model_path"] = value

    @property
    def visual_model_path(self):
        return self.config.get("visual_model_path", "")

    @visual_model_path.setter
    def visual_model_path(self, value):
        self.config["visual_model_path"] = value

    @property
    def download_path(self):
        return self.config.get("download_path", "")

    @download_path.setter
    def download_path(self, value):
        self.config["download_path"] = value
