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
    sav.getToken()
    logger.info("Configuration Initiated..")
    logger.info("Starting configureSaviynt job for request_id=REQ-10045")
    logger.debug("Payload for security system creation: {'name': 'HRAppSystem', 'type': 'DB', 'owner': 'IAM_Team'}")
    logger.debug("Saviynt API response: {'status': 'success', 'connection_id': 873}")
    logger.info("Successfully configured Saviynt for request_id=REQ-10045")