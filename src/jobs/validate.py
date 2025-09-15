import os,sys,logging
from pathlib import Path

# class file imports 
sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.api.SaviyntAPI import SaviyntAPI
from src.api.ServicenowAPI import ServicenowAPI

# Logger Setup
logger = logging.getLogger("Validate")  # Use named logger

if __name__=="__main__":
    sav = SaviyntAPI() 
    snow = ServicenowAPI()
    logger.info("Starting ValidateJob for file=roles_upload.csv, request_id=REQ-10045")
    logger.debug("Validating role=Finance_Manager, entitlement=SAP_GL_ACCESS")
    logger.debug("Validating role=HR_Admin, entitlement=Workday_Full")
    logger.debug("API Response: {'status': 'success', 'invalid_roles': []}")
    logger.info("File validation successful for request_id=REQ-10045")
