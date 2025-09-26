import os,sys,logging,json
from pathlib import Path

# class file imports 
sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.api.SaviyntAPI import SaviyntAPI
from src.api.ServicenowAPI import ServicenowAPI

# Logger Setup
logger = logging.getLogger("Validate")  # Use named logger

if __name__=="__main__":
    repo_root = Path(__file__).resolve().parents[2]
    artifacts_dir = repo_root / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    #API initialize
    sav = SaviyntAPI() 
    snow = ServicenowAPI()

    #Get pipeline ID
    pipeline_id=os.getenv("CI_PIPELINE_ID","local")

    #Report File format
    reportFileFormat = f"ValidationResult.json"
    reportFile= artifacts_dir/ reportFileFormat

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
    print(json.dumps(all_roles, indent=2))    #Validate

     # Validate roles
    valid_entitlements = []
    invalid_entitlements = []

    ad_groups_entitlements = [
    group.get("Group name")
    for group in Extracted_data.get("AllADGroupsInformation", [])
    ]


    for entitlement in ad_groups_entitlements:
        if entitlement in all_entitlements:
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

    # Final result
    result = {
        "pipeline_id": pipeline_id,
        "total_roles": len(Extracted_data.get("Roles", [])),
        "valid_roles": valid_roles,
        "invalid_roles": invalid_roles,
        "total_entitlements": len(Extracted_data.get("Entitlements", [])),
        "valid_entitlements": valid_entitlements,
        "invalid_entitlements": invalid_entitlements,
        "status": "success" if not (invalid_roles or invalid_entitlements) else "failed"
    }

    with open(reportFile, "w") as f:
        json.dump(result, f, indent=2)

    if invalid_roles or invalid_entitlements:
        logger.error(f"Validation failed with {len(invalid_roles)} invalid roles and {len(invalid_entitlements)} invalid entitlements. Report: {reportFile}")
        sys.exit(1)
    else:
        logger.info(f"Validation successful. Report: {reportFile}")
        sys.exit(0)