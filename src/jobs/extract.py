import os,sys,logging,base64
import pandas as pd
from pathlib import Path

# class file imports 
sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.api.SaviyntAPI import SaviyntAPI
from src.api.ServicenowAPI import ServicenowAPI

# Logger Setup
logger = logging.getLogger("ExtractFile")  # Use named logger

if __name__=="__main__":
    repo_root = Path(__file__).resolve().parents[2]
    artifacts_dir = repo_root / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TEST_VARIABLES"] = "valuesdasfghjkasdlfjag"
    logger.info("Starting ExtractFiles job for request_id=REQ-10045")
    logger.debug("Received form submission from ServiceNow with details: {'requested_by': 'jdoe', 'system': 'HRApp'}")
    logger.debug("Extracted CSV file: roles_upload.csv with size=47 KB")
    logger.info("ExtractFiles job completed successfully for request_id=REQ-10045")
    # base64file = os.environ.get("FILE")
    # # Decode to bytes
    # excel_bytes = base64.b64decode(base64file)

    # # Save to disk
    # out_path = artifacts_dir / "master.xlsx"
    # out_path.write_bytes(excel_bytes)

    # # Read with pandas (requires openpyxl for .xlsx)
    # df = pd.read_excel(out_path, sheet_name=0, engine="openpyxl")  # change sheet_name as needed
    # print(df.head())
