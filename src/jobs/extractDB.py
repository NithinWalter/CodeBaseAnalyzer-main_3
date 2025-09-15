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

    sav = SaviyntAPI() 
    userJson = sav.getUsers()
    entJson = sav.getEntitlements()

    json_path = artifacts_dir / "userData.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(userJson, f, ensure_ascii=False, indent=2)

    ent_path = artifacts_dir / "entitlementData.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(entJson, f, ensure_ascii=False, indent=2)