import os,sys,logging,json
from pathlib import Path
from datetime import datetime

# class file imports 
sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.api.SaviyntAPI import SaviyntAPI
from src.api.ServicenowAPI import ServicenowAPI
from junit_xml import TestSuite, TestCase

# Logger Setup
logger = logging.getLogger("configuration")  # Use named logger

def validate_api(sav):
    payload = {
        "endpointname": "Axiom"
    }
    res = sav.getEndPoint(payload)

    # Create a test case entry
    test_case = TestCase("API Validation")
    print(res)
    if res["Message"] == "Success":
        test_case.add_failure_info(f"Expected Success, got {res["Message"]}")
    return test_case


if __name__=="__main__":
    repo_root = Path(__file__).resolve().parents[2]
    artifacts_dir = repo_root / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    sav = SaviyntAPI() 
    username = "admin"
    password = "jSsW$6aRd$E8"
    ritm_sys_id = os.getenv("RITM_SYS_ID")

    snow = ServicenowAPI(username, password)
   
    json_file = artifacts_dir / "sc_tasks.json"
    report_file = artifacts_dir / "report.xml"
    test_case = validate_api(sav)
    test_suite = TestSuite("ValidationSuite", [test_case])

    task2_sys_id = snow.create_sctask(ritm_sys_id, "AOBAuto Recon", "Reconcile SC Task description")
    if task2_sys_id:
        logger.info(f"SC Task {task2_sys_id} created successfully")
        with open(report_file, "w") as f:
            TestSuite.to_file(f, [test_suite], prettyprint=True)
        snow.close_sctask(task2_sys_id, "Closing after creation")
        logger.info("SC Task closed")
