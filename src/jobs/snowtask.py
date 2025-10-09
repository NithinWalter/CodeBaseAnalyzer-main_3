import os,sys,logging,json
from pathlib import Path
from datetime import datetime

# class file imports 
sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.api.SaviyntAPI import SaviyntAPI
from src.api.ServicenowAPI import ServicenowAPI

# Logger Setup
logger = logging.getLogger("configuration")  # Use named logger

def update_json(json_file, task_name, task_sys_id):
    """Append SC Task info (with sys_id) to JSON file"""
    pipeline_id=os.getenv("CI_PIPELINE_ID")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data = []
    if json_file.exists():
        with open(json_file, "r") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = []

    data.append({
        "task_name": task_name,
        "pipeline_id": pipeline_id,
        "sc_task_sys_id": task_sys_id,
        "Time_stamp": timestamp
    })

    with open(json_file, "w") as f:
        json.dump(data, f, indent=4)
    logger.info(f"Updated JSON with SC Task sys_id: {task_sys_id}")


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
   
    task3_sys_id = snow.create_sctask(ritm_sys_id, "AOBManual-Config residual", "Manual task description")
    if task3_sys_id:
        logger.info(f"SC Task {task3_sys_id} created successfully")      
        update_json(json_file, "createSCTasks", task3_sys_id)
