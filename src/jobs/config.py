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


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[2]
    artifacts_dir = repo_root / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    sav = SaviyntAPI() 
    username = "admin"
    password = "jSsW$6aRd$E8"
    ritm_sys_id = "bed16448c324f210d0d2f64d05013161"

    snow = ServicenowAPI(username, password)
   
    

    # --- First SC Task ---
    task1_sys_id = snow.create_sctask(ritm_sys_id, "Configuration Auto SC Task", "Configuration SC Task description")
    if task1_sys_id:
        logger.info(f"SC Task created Successfully with sys id: {task1_sys_id}")        
        snow.close_sctask(task1_sys_id, "Closing after creation")
        logger.info("SC Task closed")

    
