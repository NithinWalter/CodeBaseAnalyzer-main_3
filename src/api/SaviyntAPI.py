import urllib3, base64, requests, json, yaml, os, sys, logging
from pathlib import Path

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
    

if __name__=="__main__":
    api = SaviyntAPI()
    trigger = {
                "connectionname":"Active Directory Rapid"
    }
    # res = api.getUser()
    # print(res)
