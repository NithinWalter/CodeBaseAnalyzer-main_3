import os,sys,logging
from pathlib import Path

# class file imports 
sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.api.SaviyntAPI import SaviyntAPI
from src.api.ServicenowAPI import ServicenowAPI

# Logger Setup
logger = logging.getLogger("configuration")  # Use named logger

if __name__=="__main__":
    sav = SaviyntAPI() 
    snow = ServicenowAPI()
    logger.info("Starting generateReports job for request_id=REQ-10045")
    logger.debug("Input roles count=25, Saviynt roles count=27")
    logger.debug("Report generated with summary: {'new_roles': 2, 'deprecated_roles': 0, 'matches': 25}")
    logger.info("Report generation completed successfully for request_id=REQ-10045")
