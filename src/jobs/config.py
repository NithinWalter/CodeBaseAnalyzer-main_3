import os
import sys
import logging
import json
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.api.SaviyntAPI import SaviyntAPI
from src.api.ServicenowAPI import ServicenowAPI

#logger
logger = logging.getLogger("configuration")

def configADBased(sav, formData):
    # Get the Existing EndpointFilter
    con1 = {
        "connectionname": "IAMCOE LDAP SERVER",
        "connectiontype": "AD"
    }
    logger.debug("Checking for existing EndPoints")
    res1 = sav.getConnection(con1)

    endpoint_filter = json.loads(res1['connectionattributes']['ENDPOINTS_FILTER'])

    #Extract the AD Groups and the EndpointName from the FormData
    app_name = formData["application_name"]
    BASE_DN = "OU=Groups,DC=iamcoe,DC=cloud"
    group_dn = [f"CN={g['group_name']},OU=Groups,DC=iamcoe,DC=cloud" for g in data["ad_groups"]]

    if app_name in endpoint_filter:
        endpoint_filter[app_name][0]["uniqueMember"] = group_dn
    else:
        # ✅ Create a new entry if not present
        endpoint_filter[app_name] = [
            {
                "uniqueMember": group_dn
            }
        ]
    logger.debug("ENDPOINTS_FILTER : " + str(endpoint_filter))
    # Update the EndpointFilter
    con2 = {
        "connectionName": "IAMCOE LDAP SERVER",
        "connectiontype": "AD",
        "saveconnection": "Y",
        "ENDPOINTS_FILTER":json.dumps(endpoint_filter)
    }
    logger.debug("Updaing Connection EnpointFileter")
    sav.testConnection(con2)
    payload = json.dumps({
            "triggername": "Alpha_SequentialChainJob",
            "jobgroup": "Utility",
            "jobname": "TriggerChainJob",
            "createJobIfDoesNotExist": "false",
            "valueMap": {
                "savtriggerorderform": "IAMCOE_LDAP_ACCOUNTIMPORT",
                "onFailureForm": "Continue"
            }
        })
    sav.trigger_job(payload)
    return True


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[2]
    artifacts_dir = repo_root / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    sav = SaviyntAPI() 
    #data = os.environ.get("FORM_DATA")
    data = {
     "application_name": "Axiom",
     "application_owner": "test test",
     "technical_service_owner": "test test",
     "requesting_entity": "axa",
     "ad_groups": [
         {"group_name": "IT", "group_technical_name": "", "group_description": "test description", "group_owner": "some owner"},
         {"group_name": "HR Manager", "group_technical_name": "", "group_description": "test description", "group_owner": "some owner"},
         {"group_name": "Finance Officer", "group_technical_name": "", "group_description": "test description", "group_owner": "some owner"}
     ]
    }
    username = "admin"
    password = "jSsW$6aRd$E8"
    ritm_sys_id = os.getenv("RITM_SYS_ID")
    snow = ServicenowAPI(username, password)
   
    
    
    # --- First SC Task ---
    task1_sys_id = snow.create_sctask(ritm_sys_id, "AOBAuto Configuration", "Configuration SC Task description")
    if task1_sys_id:
        logger.info(f"SC Task created Successfully with sys id: {task1_sys_id}")
        res = configADBased(sav, data)        
        snow.close_sctask(task1_sys_id, "Closing after creation")
        logger.info("SC Task closed")

    
