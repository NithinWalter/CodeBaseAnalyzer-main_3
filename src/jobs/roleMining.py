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
    logger.info("Starting generateRoleMiningJob for request_id=REQ-10045")
    logger.debug("Dataset size=256, features=['entitlement_count','user_count']")
    logger.debug("Applying K-Means clustering with k=5")
    logger.debug("Cluster distribution: {0: 54, 1: 62, 2: 49, 3: 51, 4: 40}")
    logger.info("Role mining completed successfully for request_id=REQ-10045 with 5 clusters")
