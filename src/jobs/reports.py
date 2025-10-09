import os,sys,logging,json
from pathlib import Path
from datetime import datetime

# class file imports 
sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.api.SaviyntAPI import SaviyntAPI
from src.api.ServicenowAPI import ServicenowAPI

# Logger Setup
logger = logging.getLogger("configuration")  # Use named logger


if __name__=="__main__":
    repo_root = Path(__file__).resolve().parents[2]
    artifacts_dir = repo_root / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    sav = SaviyntAPI() 
    username = "admin"
    password = "jSsW$6aRd$E8"
    ritm_sys_id = "bed16448c324f210d0d2f64d05013161"

    snow = ServicenowAPI(username, password)
   
    json_file = artifacts_dir / "sc_tasks.json"

    task2_sys_id = snow.create_sctask(ritm_sys_id, "AOBAuto Recon", "Reconcile SC Task description")
    if task2_sys_id:
        logger.info(f"SC Task {task2_sys_id} created successfully")
        snow.close_sctask(task2_sys_id, "Closing after creation")
        logger.info("SC Task closed")
