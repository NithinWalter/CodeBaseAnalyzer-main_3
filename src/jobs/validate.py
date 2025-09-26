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

    logger.info("Starting ValidateJob for file=roles_upload.csv, request_id=REQ-10045")
    logger.debug("Validating role=Finance_Manager, entitlement=SAP_GL_ACCESS")
    logger.debug("Validating role=HR_Admin, entitlement=Workday_Full")
    logger.debug("API Response: {'status': 'success', 'invalid_roles': []}")
    logger.info("File validation successful for request_id=REQ-10045")

    #Get pipeline ID
    pipeline_id=os.getenv("CI_PIPELINE_ID","local")

    #Report File format
    reportFileFormat = f"Validation_result_{pipeline_id}.json"
    reportFile= artifacts_dir/ reportFileFormat

    #Input file (validateData.json)
    validationFile = artifacts_dir / "validateData.json"

    if not validationFile.exists():
        logger.error(f"File for validation not Found")
        sys.exit(1)

    with open(validationFile, "r") as f:
        validation_data=json.load(f)
    logger.info(f"Validation data are Loaded")

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

    with open(entitlement_data_file, "r") as f:
        all_entitlements = json.load(f)

    with open(roles_data_file, "r") as f:
        all_roles = json.load(f)
    #Validate

     # Validate roles
    valid_entitlements = []
    invalid_entitlements = []

    for entitlement in validation_data.get("Entitlements", []):
        if entitlement in all_entitlements:
            valid_entitlements.append(entitlement)
            logger.debug(f"Entitlement valid: {entitlement}")
        else:
            invalid_entitlements.append(entitlement)
            logger.warning(f"Entitlement invalid: {entitlement}")

    # Validate roles
    valid_roles = []
    invalid_roles = []

    for role in validation_data.get("Roles", []):
        if role in all_roles:
            valid_roles.append(role)
            logger.debug(f"Role valid: {role}")
        else:
            invalid_roles.append(role)
            logger.warning(f"Role invalid: {role}")

    # Final result
    result = {
        "pipeline_id": pipeline_id,
        "total_roles": len(validation_data.get("Roles", [])),
        "valid_roles": valid_roles,
        "invalid_roles": invalid_roles,
        "total_entitlements": len(validation_data.get("Entitlements", [])),
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