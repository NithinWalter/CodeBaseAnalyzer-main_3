import urllib3, base64, requests, json, yaml, os
from pathlib import Path 


class SaviyntAPI:

    def __init__(self, baseURL, clientID, clientSecret):
        self.BASE_URL = baseURL.rstrip("/") # Saviynt Base URL
        self.CLIENT_ID = clientID
        self.CLIENT_SECRET = clientSecret
        self.token = ""
        with open(Path(__file__).parent / "../../config/saviynt_endpoints.yml", "r") as f:
            self.endpoints = yaml.safe_load(f)


    def getToken(self):
        endPointURL = f"{self.BASE_URL}{self.endpoints["auth"]["login"]}"
        payload = json.dumps({
            "username": self.CLIENT_ID,
            "password": self.CLIENT_SECRET
            })
        headers = {
            'Content-Type': 'application/json'
        }

        try:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.request("POST", endPointURL, headers=headers, data=payload, verify=False)
            response.raise_for_status()
            jsonData = json.loads(response.text)
            self.token = jsonData["access_token"]

            print("Access Token : " + str(self.token)[1:7])
            return True
        except Exception as e:
            print("Exception has Occured : " + str(e))

    def createSecuritySystem(self, payload):
        endPointURL = self.SAV_BASE_URL + self.SAV_SS_EP
        token = "Bearer " + self.SAV_Token
        headers = {
            'Authorization': token
        }
        try:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.request("POST", endPointURL, headers=headers, data=payload)
            jsonData = json.loads(response.text)
            if(jsonData["msg"].lower() == "success"):
                print("Security System is Successfully Created..".format(jsonData["msg"]))
            else:
                print("Failed to create Security System with ERROR : {}".format(jsonData["msg"]))
        except Exception as e:
            print("Exception has Occured in createSecuritySystem: " + str(e))

    def updateSecuritySystem(self, payload):
        endPointURL = self.SAV_BASE_URL + self.SAV_SSU_EP
        token = "Bearer " + self.SAV_Token
        headers = {
            'Authorization': token
        }
        try:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.request("PUT", endPointURL, headers=headers, data=payload)
            jsonData = json.loads(response.text)
            if(jsonData["msg"].lower() == "success"):
                print("Security System is Successfully Updated...{}".format(jsonData["msg"]))
            else:
                print("Failed to Update Security System with ERROR : {}".format(jsonData["msg"]))
        except Exception as e:
            print("Exception has Occured in updateSecuritySystem: " + str(e))

    def createEndPoint(self, payload):
        endPointURL = self.SAV_BASE_URL + self.SAV_CEP_EP
        token = "Bearer " + self.SAV_Token
        headers = {
            'Authorization': token
        }
        try:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.request("POST", endPointURL, headers=headers, data=payload)
            jsonData = json.loads(response.text)
            if(jsonData["msg"].lower() == "success"):
                print("EndPoint is Successfully Updated...{}".format(jsonData["msg"]))
            else:
                print("Failed to create EndPoint with ERROR : {}".format(jsonData["msg"]))
        except Exception as e:
            print("Exception has Occured in createEndPoint: " + str(e))

    def updateEndPoint(self, payload):
        endPointURL = self.SAV_BASE_URL + self.SAV_UEP
        token = "Bearer " + self.SAV_Token
        headers = {
            'Authorization': token
        }
        try:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.request("PUT", endPointURL, headers=headers, data=payload)
            jsonData = json.loads(response.text)
            if(jsonData["msg"].lower() == "success"):
                print("EndPoint is Successfully Updated...{}".format(jsonData["msg"]))
            else:
                print("Failed to create EndPoint with ERROR : {}".format(jsonData["msg"]))
        except Exception as e:
            print("Exception has Occured in createEndPoint: " + str(e))

    def uploadAccountsFile(self, jsonData):
        endPointURL = self.SAV_BASE_URL + self.SAV_UAF_EP
        token = "Bearer " + self.SAV_Token
        headers = {
            'Authorization': token
        }
        payload = {
            "pathLocation":"SAV"
        }
        fileName = "AOB_SAV_accounts.sav"
        self.writeFile(fileName, jsonData["AccountsSAV"])
        payload = {'pathLocation': 'SAV'}
        files=[
            ('file',(fileName,open(fileName,'rb'),'application/octet-stream'))
        ]
        try:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.request("POST", endPointURL, headers=headers, data=payload, files=files)
            jsonData = json.loads(response.text)
            print(jsonData)
        except Exception as e:
            print("Exception has Occured in uploadAccountsFile: " + str(e))
    
    def uploadEntitlementsFile(self, jsonData):
        endPointURL = self.SAV_BASE_URL + self.SAV_UAF_EP
        token = "Bearer " + self.SAV_Token
        headers = {
            'Authorization': token
        }
        payload = {
            "pathLocation":"SAV"
        }
        fileName = "aob_entitlement_values.sav"
        self.writeFile(fileName, jsonData["EntitlementsSAV"])
        payload = {'pathLocation': 'SAV'}
        files=[
            ('file',(fileName,open(fileName,'rb'),'application/octet-stream'))
        ]
        try:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.request("POST", endPointURL, headers=headers, data=payload, files=files)
            jsonData = json.loads(response.text)
            print(jsonData)
        except Exception as e:
            print("Exception has Occured in uploadEntitlementsFile: " + str(e))

    def writeFile(self, fileName, data):
        with open(fileName, 'w') as f:
            print(data)
            f.write(data)
            print("A {} File is Created.!".format(fileName))
            f.close()

    def updateEndpointFilter(self, payload):
        endPointURL = self.SAV_BASE_URL +  self.SAV_UEP_EP
        token = "Bearer " + self.SAV_Token
        headers = {
            'Authorization': token
        }

        try:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.request("POST", endPointURL, headers=headers, data=payload)
            jsonData = json.loads(response.text)
            print(jsonData)
            if(jsonData["errorCode"] == "0"):
                print("EndPoint is Successfully Updated...{}".format(jsonData["msg"]))
                return True
            else:
                return False
        except Exception as e:
            print("Exception has Occured in updateEndpointFilter: " + str(e))
            return False
        
    def createConnection(self, payload):
        endPointURL = self.SAV_BASE_URL +  self.SAV_UEP_EP
        token = "Bearer " + self.SAV_Token
        headers = {
            'Authorization': token
        }
        try:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.request("POST", endPointURL, headers=headers, data=payload)
            jsonData = json.loads(response.text)
            print(jsonData)
            if(jsonData["errorCode"] == "0"):
                print("Connection is Successfully Created...! Connection Status : {}".format(jsonData["msg"]))
                return jsonData["connectionKey"]
            else:
                return jsonData["connectionKey"]
        except Exception as e:
            print("Exception has Occured in createConnection: " + str(e))
            return jsonData["connectionKey"]


    def triggerApplicationDataImport(self, triggerNames):
        endPointURL = self.SAV_BASE_URL +  self.SAV_RJT_EP
        token = "Bearer " + self.SAV_Token
        headers = {
            'Authorization': token
        }
        payload = json.dumps({
            "triggername": "Alpha_SequentialChainJob",
            "jobgroup": "Utility",
            "jobname": "TriggerChainJob",
            "createJobIfDoesNotExist": "false",
            "valueMap": {
                "savtriggerorderform": triggerNames,
                "onFailureForm": "Continue"
            }
        })
        try:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.request("POST", endPointURL, headers=headers, data=payload)
            jsonData = json.loads(response.text)
            print(jsonData)
        except Exception as e:
            print("Exception has Occured in triggerApplicationDataImport: " + str(e))

    def createJobTrigger(self, payload):
        endPointURL = self.SAV_BASE_URL +  self.SAV_CT
        token = "Bearer " + self.SAV_Token
        headers = {
            'Authorization': token
        }

        try:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.request("POST", endPointURL, headers=headers, data=payload)
            jsonData = json.loads(response.text)
            print(jsonData)
            return True
        except Exception as e:
            print("Exception has Occured in createConnection: " + str(e))
            return False
        
    def triggerJDBCJOB(self, jobName, connectionName):
        endPointURL = self.SAV_BASE_URL +  self.SAV_RJT_EP
        token = "Bearer " + self.SAV_Token
        headers = {
            'Authorization': token
        }
        payload = json.dumps({
            "triggername": "Database_Account_Import",
            "jobgroup": "DATABASE",
            "jobname": jobName,
            "createJobIfDoesNotExist": "false",
            "connectionName":connectionName
        })
        try:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = requests.request("POST", endPointURL, headers=headers, data=payload)
            jsonData = json.loads(response.text)
            print(jsonData)
        except Exception as e:
            print("Exception has Occured in triggerApplicationDataImport: " + str(e))


if __name__=="__main__":
    api = SaviyntAPI("https://tcs-partner.saviyntcloud.com", "Admin_IAMCOE","Password@2025")
    api.getToken()