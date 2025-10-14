import urllib3, base64, requests, json, yaml, os, sys, logging
from pathlib import Path
from collections import defaultdict

sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.api.BaseAPI import BaseAPI 

logger = logging.getLogger(__name__)  # Use named logger

class SaviyntAPI(BaseAPI):

    def __init__(self):
        super().__init__("saviynt")
        self.token = None


    def getToken(self):
        endPointURL = f"{self.base_url}{self.endpoints['login']}"
        payload = json.dumps({
            "username": self.clientID,
            "password": self.clientSecret
            })
        headers = {'Content-Type': 'application/json'}

        try:
            # self.call_api(method="POST",endpoint_key="login",data=payload,)
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.request("POST", endPointURL, headers=headers, data=payload, verify=False)
            response.raise_for_status()
            jsonData = response.json()
            self.token = jsonData["access_token"]
            if self.token:
                logger.info("Saviynt token retrieved successfully")
                logger.debug(f"Access Token (partial): {self.token[:6]}...")
                return True
            else:
                logger.error("Failed to retrieve access token from Saviynt response")
                return False
        except Exception as e:
            logger.error("Exception has Occured : " + str(e))
    
    
    def _request(self, method: str, endpoint_key: str, **kwargs):
        """Wrapper around requests to include auth token and handle errors."""
        if not self.token:
            logger.debug("No token available. Calling get_token() first.")
            self.getToken()

        url = f"{self.base_url}{self.endpoints[endpoint_key]}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.token}"

        try:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            logger.debug(f"{method} {url} succeeded")
            return response.json()
        except Exception as e:
            logger.error(f"{method} {url} failed: {e}")
            return None
        
    def create_security_system(self, payload: dict):
        return self._request("POST", "create_security_system", json=payload)
    
    def update_security_system(self, payload: dict):
        return self._request("POST", "update_security_system", json=payload)
    
    def createEndPoint(self, payload: dict):
        return self._request("POST", "create_endpoint", json=payload)
    
    def getEndPoint(self, payload: dict):
        return self._request("POST", "get_endpoint", json=payload)
    
    def updateEndPoint(self, payload: dict):    
        return self._request("POST", "update_endpoint", json=payload)

    def trigger_job(self, payload: dict):
        return self._request("POST", "trigger_job", json=payload)
    
    def getConnection(self, payload: dict, **kwargs): 
        return self._request("POST","get_connection_details",json=payload, **kwargs)
    
    def createConnection(self, payload: dict): 
        return self._request("POST","create_connection",json=payload)
    
    def createJobTrigger(self, payload: dict):
        return self._request("POST","get_connection",json=payload)
        
    def uploadAccountsFile(self, payload: dict, **kwargs):
        return self._request("POST","get_connection", **kwargs)
    
    def getUsers(self, payload={}, **kwargs):
        return self._request("POST","get_user", **kwargs)
    
    def getEntitlements(self, payload={}, **kwargs):
        return self._request("POST","get_entitlements", **kwargs)
    
    def getRoles(self, payload={}, **kwargs):
        return self._request("POST", "list_roles", json=payload,**kwargs)
    
    def testConnection(self, payload: dict, **kwargs): 
        return self._request("POST","testConnection",json=payload, **kwargs)
    
    def getEntDetailsforUsers(self, page_size=100, **kwargs):
        user_entitlements = defaultdict(set)
        all_entitlements = set()
        users_ordered = []
        offset = 0
        total_count = None

        while True:
            params = {"max": page_size, "offset": offset}
            data = self._request("GET", "getEntUserDetails", params=params, **kwargs)

            if not data or "accessDetails" not in data:
                break  # failsafe

            if total_count is None:
                total_count = int(data.get("totalCount", 0))

            display_count = int(data.get("displayCount", 0))

            for record in data["accessDetails"]:
                username = record.get("username")
                ent = record.get("entitlement_value")

                if username and ent:
                    if username not in users_ordered:
                        users_ordered.append(username)  # Preserve order
                    user_entitlements[username].add(ent)
                    all_entitlements.add(ent)

            offset += display_count

            if offset >= total_count:
                break
        return users_ordered, user_entitlements, sorted(all_entitlements)
    
