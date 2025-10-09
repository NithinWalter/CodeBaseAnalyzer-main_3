import os
import yaml
import json
import logging
import logging.config
import requests
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# ============================================================
# 1. Load Settings First
# ============================================================
def load_settings(settings_file="config/settings.yml"):
    
    with open(str(Path(__file__).resolve().parents[2] / settings_file), "r") as f:
        settings = yaml.safe_load(f)
    return settings

SETTINGS = load_settings()

# ============================================================
# 2. Initialize Logging from logging.yaml
# ============================================================
def setup_logging(default_path="config/logging.yml", default_level=logging.INFO):
    log_path = Path(__file__).resolve().parents[2] / default_path
    if log_path.exists():
        with open(log_path, "r") as f:
            config = yaml.safe_load(f)
        logging.config.dictConfig(config)
    else:
        logging.basicConfig(level=default_level)


setup_logging(SETTINGS["logging"]["config_file"])
logger = logging.getLogger(__name__)

# ============================================================
# 3. Base API Class
# ============================================================
class BaseAPI:
    def __init__(self, service_name: str):
        self.service_name = service_name.lower()
        self.service_cfg = SETTINGS.get(self.service_name, {})

        if not self.service_cfg:
            raise ValueError(f"Service config for '{service_name}' not found in settings.yml")

        self.base_url = self.service_cfg.get("base_url")
        self.auth_type = self.service_cfg.get("auth_type", "token")
        self.clientID = self.service_cfg.get("client_id", "")
        self.clientSecret = self.service_cfg.get("client_secret", "")
        self.timeout = self.service_cfg.get("timeout", 30)
        self.retries = self.service_cfg.get("retries", 3)

        # Load endpoints file relative to project root
        endpoints_file = self.service_cfg.get("endpoints_file")
        self.endpoints = {}
        if endpoints_file:
            path = (PROJECT_ROOT / endpoints_file).resolve()
            if path.exists():
                with open(path, "r") as f:
                    data = json.load(f)
                    if self.service_name in data:
                        self.endpoints = data[self.service_name]
                        logger.info(f"Loaded endpoints for {self.service_name}: {list(self.endpoints.keys())}")
                    else:
                        logger.error(f"Service '{self.service_name}' not found in {path}")
            else:
                logger.error(f"Endpoints file not found: {path}")
        else:
            logger.error(f"No endpoints_file defined in settings.yml for {self.service_name}")

        logger.info(f"Initialized API client for {self.service_name} → {self.base_url}")
