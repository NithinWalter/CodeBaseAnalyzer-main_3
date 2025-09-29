import os
import logging
import requests

logger = logging.getLogger("GitLabUtils")

def update_gitlab_variable(key, value, append=False):
    """
    Update or create a GitLab CI/CD variable.
    If append=True, the new value will be appended to existing JSON list.
    """
    project_id = os.getenv("CI_PROJECT_ID", "74778875")
    token = os.getenv("GITLAB_PRIVATE_TOKEN", "glptt-8a8f9ecdbab849a544863dc1cd746125421307b9")  # safer than hardcoding

    base_url = f"https://gitlab.com/api/v4/projects/{project_id}/variables"
    headers = {"PRIVATE-TOKEN": token, "Content-Type": "application/json"}

    # Handle append
    if append:
        # Fetch existing variable
        resp = requests.get(f"{base_url}/{key}", headers=headers)
        if resp.status_code == 200:
            try:
                existing = resp.json().get("value", "")
                existing_json = json.loads(existing)
                if not isinstance(existing_json, list):
                    existing_json = [existing_json]
            except Exception:
                existing_json = [existing]
            value = existing_json + [value]

    payload = {
        "value": json.dumps(value),
        "variable_type": "env_var",
        "protected": False,
        "masked": False
    }

    # Update first
    update_url = f"{base_url}/{key}"
    response = requests.put(update_url, headers=headers, json=payload)
    if response.status_code == 200:
        logger.info(f"✅ Updated GitLab variable {key}")
        return True
    elif response.status_code == 404:
        # Create new variable
        payload_with_key = {"key": key, **payload}
        response = requests.post(base_url, headers=headers, json=payload_with_key)
        if response.status_code == 201:
            logger.info(f"✅ Created GitLab variable {key}")
            return True
        else:
            logger.error(f"❌ Failed to create variable {key}: {response.text}")
            return False
    else:
        logger.error(f"❌ Failed to update variable {key}: {response.text}")
        return False
