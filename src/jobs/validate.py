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
