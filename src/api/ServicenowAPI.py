# File: src/api/ServicenowAPI.py
import urllib3
import requests
import logging
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.api.BaseAPI import BaseAPI

logger = logging.getLogger(__name__)


class ServicenowAPI(BaseAPI):
    def __init__(self, username: str, password: str):
        super().__init__("servicenow")
        self.username = username
        self.password = password

    def _request(self, method: str, endpoint_key: str, **kwargs):
        url = f"{self.base_url}{self.endpoints[endpoint_key]}"
        headers = kwargs.pop("headers", {})
        headers["Content-Type"] = "application/json"

        auth = (self.username, self.password)

        try:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.request(method, url, headers=headers, auth=auth, **kwargs)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"{method} {url} failed: {e}")
            return None

    def create_sctask(self, ritm_sys_id: str, short_description: str, description: str) -> str:
        payload = {
            "request_item": ritm_sys_id,
            "short_description": short_description,
            "description": description
        }
        res = self._request("POST", "create_sctask", json=payload)
        if res and "result" in res and "sys_id" in res["result"]:
            return res["result"]["sys_id"]
        return None

    def close_sctask(self, task_sys_id: str, close_notes: str = "Closed via automation"):
        payload = {
            "sys_id": task_sys_id,
            "close_notes": close_notes,
            "state": "Closed"
        }
        res = self._request("POST", "close_sctask", json=payload)
        return res
