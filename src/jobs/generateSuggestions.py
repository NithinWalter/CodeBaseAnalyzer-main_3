import os
import requests
import pandas as pd
from io import BytesIO
import json
import base64
import urllib3
from sentence_transformers import SentenceTransformer
import torch
from sentence_transformers.util import cos_sim

# class file imports 
sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.api.SaviyntAPI import SaviyntAPI
from src.api.ServicenowAPI import ServicenowAPI

# Logger Setup
logger = logging.getLogger("configuration")  # Use named logger

model = SentenceTransformer("all-MiniLM-L6-v2")

if __name__=="__main__":
    sav = SaviyntAPI() 
    snow = ServicenowAPI()
    entitlements = getEntitlements()
    embeddings = model.encode(entitlements, convert_to_tensor=True)
    results ={}
    for ent in ad_groups:
        query_embedding = model.encode(ent, convert_to_tensor=True)
        cos_scores = cos_sim(query_embedding, embeddings)[0]
        top_score, top_idx = torch.max(cos_scores, 0)
        suggested_entitlement = entitlements[top_idx]
        results[ent] = {"match":suggested_entitlement, "score":(top_score.float().item())*100, "index":(top_idx.int()).item()}
    print("results")
    print(results)