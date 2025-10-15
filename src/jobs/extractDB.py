import os,sys,logging,json
from pathlib import Path

# class file imports 
sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.api.SaviyntAPI import SaviyntAPI
from src.api.ServicenowAPI import ServicenowAPI

# Logger Setup
logger = logging.getLogger("Validate")  # Use named logger

def filter_fields(data_list, required_keys):
    """Filter list of dicts to include only required keys."""
    filtered = []
    for item in data_list:
        filtered.append({k: item.get(k) for k in required_keys if k in item})
    return filtered

def generateRoleMiningMatrix(sav):
    users, user_entitlements, all_entitlements = sav.getEntDetailsforUsers()
    matrix = {}
    for ent in all_entitlements:
        matrix[ent] = [1 if ent in user_entitlements.get(user, []) else 0 for user in users]
    return {
        "users": users,
        "matrix": matrix
    }


if __name__=="__main__":
    repo_root = Path(__file__).resolve().parents[2]
    artifacts_dir = repo_root / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    sav = SaviyntAPI() 
    userJson = sav.getUsers()
    payload = {
    "entitlementType": "uniqueMember"
    }

    entJson = sav.getEntitlements(payload)
    roleJson=sav.getRoles()
    user_details = userJson.get("userdetails", [])
    logger.info(f"Fetched {len(user_details)} users from Saviynt")

    # --- Select only basic fields ---
    user_fields = [
        "username",
        "displayname",
        "email",
        "departmentname",
        "jobDescription",
        "location",
        "enabled",
        "statuskey"
    ]
    filtered_users = filter_fields(user_details, user_fields)

    # --- Save filtered user data ---
    json_path = artifacts_dir / "userData.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(filtered_users, f, ensure_ascii=False, indent=2)
    logger.info("Filtered user data saved successfully.")

    ent_details = entJson.get("Entitlementdetails", entJson)
    ent_fields = [
        "endpoint",
        "entitlement_value",
        "entitlement_glossary",
        "Custom Property 13",
        "displayname",
        "description",
        "entitlementOwner",
        "status",
        "entitlementType"
    ]
    filtered_entitlements = filter_fields(ent_details, ent_fields)
    logger.info(f"Filtered {len(filtered_entitlements)} entitlement records.")

    # Save filtered entitlement data
    ent_path = artifacts_dir / "entitlementsData.json"
    with ent_path.open("w", encoding="utf-8") as f:
        json.dump(filtered_entitlements, f, ensure_ascii=False, indent=2)
    logger.info("Entitlement data saved successfully.")

    #------------ROLES---------------------
    role_details = roleJson.get("Roledetails", roleJson)
    role_fields = [
        "role_name",
        "displayname",
        "description",
        "owner",
        "risk",
        "requestable",
        "status",
        "endpoint"
    ]
    filtered_roles = filter_fields(role_details, role_fields)
    logger.info(f"Filtered {len(filtered_roles)} role records.")

    role_path = artifacts_dir / "rolesData.json"
    with role_path.open("w", encoding="utf-8") as f:
        json.dump(filtered_roles, f, ensure_ascii=False, indent=2)
    logger.info("Filtered role data saved successfully.")


    entMatrix = generateRoleMiningMatrix(sav)
    entMatrixPath = artifacts_dir / "userEntitlementsMatrix.json"
    with entMatrixPath.open("w", encoding="utf-8") as f:
        json.dump(entMatrix, f, ensure_ascii=False, indent=2)
