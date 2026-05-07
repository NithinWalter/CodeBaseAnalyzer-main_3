import requests
import json
import re

# 🔐 ADD YOUR API KEY HERE
GROK_API_KEY = "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"

GROK_URL = "https://api.groq.com/openai/v1/chat/completions"


# -----------------------------------
# PROMPT (uses your cleaned IAM JSON)
# -----------------------------------
def build_prompt(cleaned_iam: dict) -> str:
    return f"""
You are an expert in Identity Governance and Administration (IGA).

Below is an IAM analysis extracted from a codebase:

{json.dumps(cleaned_iam, indent=2)}

Your job:
1. Identify authentication type (JWT, OAuth2, LDAP, SAML, etc.)
2. Identify IAM connectors needed (REST API, Database, LDAP, etc.)
3. Recommend IGA tools (Keycloak, Okta, SailPoint, Auth0, Azure AD, etc.)
4. Explain how this application can be onboarded into an IGA system
5. Provide a confidence score (0 to 1)

IMPORTANT:
- Do NOT assume OAuth2 unless explicitly present
- JWT + Passport = Token-based authentication
- NOSQL = Database connector needed

Return ONLY JSON in this format:
{{
  "auth_type": "",
  "connectors": [],
  "iga_tools": [],
  "integration_strategy": "",
  "reasoning": "",
  "confidence": 0.0
}}
"""


# -----------------------------------
# GROK API CALL
# -----------------------------------
def call_grok(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": "You are an IAM and IGA expert."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2
    }

    response = requests.post(GROK_URL, headers=headers, json=payload, timeout=60)

    if response.status_code != 200:
        raise Exception(f"Grok API Error: {response.text}")

    return response.json()["choices"][0]["message"]["content"]


# -----------------------------------
# SAFE JSON PARSER
# -----------------------------------
def extract_json(text: str):
    try:
        return json.loads(text)
    except:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {"raw_output": text}


# -----------------------------------
# MAIN FUNCTION (CALL THIS)
# -----------------------------------
def get_grok_iga_recommendation(cleaned_iam: dict):
    # ⚠️ Prevent huge payload crash
    text = json.dumps(cleaned_iam)
    if len(text) > 5000:
        cleaned_iam = json.loads(text[:5000])

    prompt = build_prompt(cleaned_iam)

    raw_output = call_grok(prompt)

    parsed_output = extract_json(raw_output)

    return parsed_output