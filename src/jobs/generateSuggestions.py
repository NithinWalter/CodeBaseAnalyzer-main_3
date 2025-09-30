import os,sys,logging, requests
import pandas as pd
from io import BytesIO
import json, base64,  urllib3
from sentence_transformers import SentenceTransformer
import torch
from sentence_transformers.util import cos_sim
from pathlib import Path

# class file imports 
sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.api.SaviyntAPI import SaviyntAPI
from src.api.ServicenowAPI import ServicenowAPI
from src.jobs.UpdateGitVariable import update_gitlab_variable

# Logger Setup
logger = logging.getLogger("configuration")  

# Use named logger
model = SentenceTransformer("all-MiniLM-L6-v2")

if __name__=="__main__":

    repo_root = Path(__file__).resolve().parents[2]
    artifacts_dir = repo_root / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    pipeline_id=os.getenv("CI_PIPELINE_ID","local")
        
    # 1. Fetch the JSON response (dictionary)
    full_response_path = artifacts_dir / "entitlementsData.json"
    with open(full_response_path, "r") as f:
        full_response = json.load(f)
    
    # --- FIX implemented here: Extracting the list of entitlement strings ---
    
    if not isinstance(full_response, dict) or "Entitlementdetails" not in full_response:
        logger.error("API response is invalid or missing 'Entitlementdetails'. Exiting.")
        sys.exit(1)
        
    entitlements_details_list = full_response.get("Entitlementdetails", [])
    
    # Extract the 'entitlement_value' from each dictionary to create the list of strings
    entitlements = [
        item.get("entitlement_value") 
        for item in entitlements_details_list 
        if isinstance(item, dict) and item.get("entitlement_value")
    ]
    
    if not entitlements:
        logger.warning("The extracted entitlements list is empty. Nothing to process.")
        sys.exit(0)
        

    # Encode all valid entitlement strings into embeddings (This line now works)
    embeddings = model.encode(entitlements, convert_to_tensor=True)
    
    results ={}
    extracted_file = artifacts_dir / "ExtractedData.json"
    if not extracted_file.exists():
        logger.error("ExtractedData.json not found. Cannot load AD groups.")
        sys.exit(1)

    with open(extracted_file, "r") as f:
        extracted_data = json.load(f)

    # ✅ Get AD groups dynamically
    ad_groups = [
        group.get("Group name")
        for group in extracted_data.get("AllADGroupsInformation", [])
        if isinstance(group, dict) and group.get("Group name")
    ]

    if not ad_groups:
        logger.warning("No AD groups found in ExtractedData.json. Nothing to process.")
        sys.exit(0)
    for ent in ad_groups:
        query_embedding = model.encode(ent, convert_to_tensor=True)
        
        # Calculate cosine similarity between the query and all entitlements
        cos_scores = cos_sim(query_embedding, embeddings)[0]
        
        # Find the highest score and its index
        top_score, top_idx = torch.max(cos_scores, 0)
        
        suggested_entitlement = entitlements[top_idx]
        
        # Store results, converting tensors to standard Python floats/ints
        results[ent] = {
            "match": suggested_entitlement, 
            "score": (top_score.float().item()) * 100, 
            "index": (top_idx.int()).item()
        }
        
    print(json.dumps(results, indent=4))

    # Path to ValidationResult.json
    reportFile = artifacts_dir / "ValidationResult.json"

# Load existing ValidationResult.json
    if reportFile.exists():
        with open(reportFile, "r") as f:
            validation_data = json.load(f)
    else:
        validation_data = {"ValidationResults": {}}

# Append SuggestedEntitlement under ValidationResults
    validation_data.setdefault("ValidationResults", {})["SuggestedEntitlement"] = results

# Save back to ValidationResult.json
    with open(reportFile, "w") as f:
        json.dump(validation_data, f, indent=2)

# Update GitLab variable
    final_validation_result = update_gitlab_variable(
        f"ValidationResult_{pipeline_id}", validation_data, False
    )

    logger.info("Suggested entitlements appended to ValidationResult.json and GitLab variable.")
