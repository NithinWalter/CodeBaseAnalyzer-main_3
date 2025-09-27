import os
import logging
import requests

logger = logging.getLogger("GitLabUtils")

def update_gitlab_variable(key, value):
    """
    Update or create a GitLab CI/CD variable.
    """
    project_id = "74778875"
    token = "glpat-wHe150FpKb06wJICGp1cfW86MQp1Omc0OXNxCw.01.120nsrzri"

    if not project_id or not token:
        logger.error("❌ Missing CI_PROJECT_ID or GITLAB_PRIVATE_TOKEN in environment.")
        return False

    base_url = f"https://gitlab.com/api/v4/projects/{project_id}/variables"
    headers = {
        "PRIVATE-TOKEN": token,
        "Content-Type": "application/json"
    }

    payload = {
        "value": str(value),
        "variable_type": "env_var",
        "protected": False,
        "masked": False
    }

    # Try update first
    update_url = f"{base_url}/{key}"
    response = requests.put(update_url, headers=headers, json=payload)

    if response.status_code == 200:
        logger.info(f"✅ Updated GitLab variable {key}")
        return True
    elif response.status_code == 404:
        # Variable not found → create new
        payload_with_key = {"key": key, **payload}
        response = requests.post(base_url, headers=headers, json=payload_with_key)
        if response.status_code == 201:
            logger.info(f"✅ Created new GitLab variable {key}")
            return True
        else:
            logger.error(f"❌ Failed to create variable {key}: {response.text}")
            return False
    else:
        logger.error(f"❌ Failed to update variable {key}: {response.text}")
        return False
