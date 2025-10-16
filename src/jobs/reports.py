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
    """Original validation logic preserved"""
    logger.debug("Starting validate_api()")
    payload = {
        "endpointname": "Axiom - MDM"
    }
    logger.info(f"Sending payload to SaviyntAPI: {payload}")
    
    res = sav.getEndPoint(payload)
    logger.debug(f"Response received from SaviyntAPI: {res}")

    test_case = TestCase("Check if Endpoint Exists")
    if not res["message"] == "Success":
        logger.error(f"Validation failed. Expected 'Success', got '{res['message']}'")
        test_case.add_failure_info(f"Expected Success, got {res['message']}")
    else:
        logger.info("Endpoint validation succeeded")

    return test_case


def endpoint_validate():
    """
    Pytest test case that consumes the dummy function.
    """
    logger.info("EndPoint Validaion")
    res = validate_api()
    logger.info("Endpoint validation success")
    assert res["message"] == "Success"


if __name__=="__main__":
    repo_root = Path(__file__).resolve().parents[2]
    artifacts_dir = repo_root / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    sav = SaviyntAPI() 
    username = "admin"
    password = "jSsW$6aRd$E8"
    ritm_sys_id = os.getenv("RITM_SYS_ID")
    job_name = os.getenv("CI_JOB_NAME")
    os.getenv
    snow = ServicenowAPI(username, password)
   
    json_file = artifacts_dir / "sc_tasks.json"
    report_file = artifacts_dir / "report.xml"
    test_case = validate_api(sav)
    test_suite = TestSuite("ValidationSuite", [test_case])

    task2_sys_id = snow.create_sctask(ritm_sys_id, f"{job_name}", "Reconcile SC Task description")
    if task2_sys_id:
        logger.info(f"SC Task {task2_sys_id} created successfully")
        with open(report_file, "w") as f:
            TestSuite.to_file(f, [test_suite], prettyprint=True)
        snow.close_sctask(task2_sys_id, "Closing after creation")
        logger.info("SC Task closed")
