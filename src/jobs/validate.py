import os,sys,logging,json,requests,urllib3
from pathlib import Path

# class file imports 
sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.api.SaviyntAPI import SaviyntAPI
from src.api.ServicenowAPI import ServicenowAPI

# Logger Setup
logger = logging.getLogger("Validate")  # Use named logger

def updateGitlabVariable(variable,result):
    endPointURL = f"https://gitlab.com/api/v4/projects/73818692/variables/{variable}"
    payload = {'value': result}
    headers = {
    'PRIVATE-TOKEN': 'glpat-td97Auue0qrkNiu3frFO6W86MQp1Omk2OW92Cw.01.1209nj5ko'
    }
    try:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = requests.request("PUT", endPointURL, headers=headers, data=payload)
        if(response.status_code == 200):
            jsonData = json.loads(response.text)     
            return "Updated"
        else:
            print("Request Failed (Status Code) : " + str(response.status_code))
            jsonData = json.loads(response.text)
            print(jsonData)
            if "Variable Not Found" in response.text:
                created_response = createGitlabVariable(variable,result)
                return created_response
            return "Failed"
    except Exception as e:
        print("Exception has Occured : " + str(e))


def createGitlabVariable(variable,result):
    endPointURL = "https://gitlab.com/api/v4/projects/73818692/variables"
    payload = {'key': variable,
    'value': result}
    headers = {
    'PRIVATE-TOKEN': 'glpat-td97Auue0qrkNiu3frFO6W86MQp1Omk2OW92Cw.01.1209nj5ko'
    }
    try:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = requests.request("POST", endPointURL, headers=headers, data=payload)
        if(response.status_code == 201):
            jsonData = json.loads(response.text)
            return "Created"
        else:
            print("Create Request Failed (Status Code) : " + str(response.status_code))
            return "Failed"
    except Exception as e:
        print("Exception has Occured : " + str(e))


if __name__=="__main__":
    repo_root = Path(__file__).resolve().parents[2]
    artifacts_dir = repo_root / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    #API initialize
    sav = SaviyntAPI() 
    snow = ServicenowAPI()

    #Get pipeline ID
    pipeline_id=os.getenv("CI_PIPELINE_ID","local")


    #Input file (validateData.json)
    ExtractedFile = artifacts_dir / "ExtractedData.json"

    if not ExtractedFile.exists():
        logger.error(f"File for validation not Found")
        sys.exit(1)

    with open(ExtractedFile, "r") as f:
        Extracted_data=json.load(f)
    logger.info(f"Extracted data are Loaded")

    #Load entitlement data from extractDB.py
    entitlement_data_file = artifacts_dir / "entitlementsData.json"

    if not entitlement_data_file.exists():
        logger.error("Entitlements DB file not found")
        sys.exit(1)
    
    
    #load roles 
    roles_data_file = artifacts_dir / "rolesData.json"

    if not roles_data_file.exists():
        logger.error("Roles DB file not found")
        sys.exit(1)

    #specific json format
    with open(entitlement_data_file, "r") as f:
        all_entitlements_full = json.load(f)
    
    all_entitlements = [
        {
            "Entitlement value": ent.get("entitlement_value"),
            "Entitlement type": ent.get("entitlementType"),
            "Entitlement ID" : ent.get("entitlementID"),
            "DisplayName" : ent.get("displayname"),
            "Status" :ent.get("status"),
            "Entitlement owner": ent.get("entitlementOwner", [])
        }
        for ent in all_entitlements_full.get("Entitlementdetails", [])
    ]

    with open(roles_data_file, "r") as f:
        all_roles = json.load(f)
    print(json.dumps(all_roles, indent=2))  
    

     # Validate roles
    valid_entitlements = []
    invalid_entitlements = []

    ad_groups_entitlements = [
    group.get("Group name")
    for group in Extracted_data.get("AllADGroupsInformation", [])
    ]

    for entitlement in ad_groups_entitlements:
        if any(entitlement == e["Entitlement value"] for e in all_entitlements):
            valid_entitlements.append(entitlement)
            logger.debug(f"Entitlement valid: {entitlement}")
        else:
            invalid_entitlements.append(entitlement)
            logger.warning(f"Entitlement invalid: {entitlement}")

    # Validate roles
    valid_roles = []
    invalid_roles = []

    all_role_names = [role.get("role_name") for role in all_roles.get("Roledetails", [])]

    for role in Extracted_data.get("Roles", []):
        if role in all_role_names:
            valid_roles.append(role)
            logger.debug(f"Role valid: {role}")
        else:
            invalid_roles.append(role)
            logger.warning(f"Role invalid: {role}")

    # Final result - entitlement
    entitlement_summary = (
        f"Total number of Entitlements : {len(ad_groups_entitlements)}.\n"
        f"Entitlements present in Saviynt : {valid_entitlements}.\n"
        f"Entitlements not present in Saviynt : {invalid_entitlements}.\n"
        )
    if invalid_entitlements:
        entitlement_summary += "Entitlements Validation Failed"
    else:
        entitlement_summary += "Entitlements Validation Passed"
   
    role_summary = (
        f"Total number of Roles : {len(Extracted_data.get('Roles', []))}.\n"
        f"Roles present in Saviynt : {valid_roles}.\n"
        f"Roles not present in Saviynt : {invalid_roles}.\n"
    )

    if invalid_roles:
        role_summary += "Roles Validation Failed"
    else:
        role_summary += "Roles Validation Passed"

    Extracted_data["ValidationResults"] = {
        "EntitlementValidationResult": entitlement_summary,
        "RoleValidationResult": role_summary,
        "ValidationResult": "success" if not (invalid_roles or invalid_entitlements) else "failed"
    }

    reportFile = artifacts_dir / "ValidationResult.json"

    with open(reportFile, "w") as f:
        json.dump(Extracted_data, f, indent=2)

    if invalid_roles or invalid_entitlements:
        logger.error(f"Validation failed with {len(invalid_roles)} invalid roles and {len(invalid_entitlements)} invalid entitlements. Report: {reportFile}")
        
    else:
        logger.info(f"Validation successful. Report: {reportFile}")
    

    final_validation_result= updateGitlabVariable(f"ValidationResult{pipeline_id}", json.dumps(Extracted_data))
    
