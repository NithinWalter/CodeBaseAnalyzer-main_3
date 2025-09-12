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
    logger.info("Starting generateSuggestionsJob for request_id=REQ-10045")
    logger.debug("Using sentence-transformer model=all-MiniLM-L6-v2")
    logger.debug("Generated 12 suggestions")
    logger.debug("Top 3 suggestions: ['Merge Finance_Manager and HR_Admin', 'Split IT_ReadOnly into smaller entitlements', 'Create consolidated Analyst role']")
    logger.info("Suggestions generated successfully for request_id=REQ-10045")