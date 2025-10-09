import requests
import os
import json
from pathlib import Path

# GitLab configuration
GITLAB_API_URL = "https://gitlab.com/api/v4"
PRIVATE_TOKEN = "glpat-td97Auue0qrkNiu3frFO6W86MQp1Omk2OW92Cw.01.1209nj5ko"
MAIN_PROJECT_ID = "73818692"
HEADERS = {"PRIVATE-TOKEN": PRIVATE_TOKEN}

# ServiceNow configuration
SERVICENOW_URL = "dev225989.service-now.com"
SN_USER = "admin"
SN_PASS = "jSsW$6aRd$E8"
AUTH = (SN_USER, SN_PASS)

# File paths
repo_root = Path(__file__).resolve().parents[2]
artifacts_dir = repo_root / "artifacts"
artifacts_dir.mkdir(parents=True, exist_ok=True)
SC_TASK_FILE = artifacts_dir / "sc_tasks.json"


def poll_servicenow(sys_id):
    """Return ServiceNow task state."""
    url = f"https://{SERVICENOW_URL}/api/now/table/sc_task/{sys_id}"
    resp = requests.get(url, auth=AUTH)
    resp.raise_for_status()
    state = resp.json()["result"]["state"]
    print(f"📋 Task {sys_id} status: {state}")
    return state


def get_manual_jobs(pipeline_id):
    """Get all manual jobs in the pipeline."""
    url = f"{GITLAB_API_URL}/projects/{MAIN_PROJECT_ID}/pipelines/{pipeline_id}/jobs?per_page=100"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return [job for job in resp.json() if job["status"] == "manual"]


def resume_job(job_id):
    """Resume a paused GitLab job."""
    play_url = f"{GITLAB_API_URL}/projects/{MAIN_PROJECT_ID}/jobs/{job_id}/play"
    resp = requests.post(play_url, headers=HEADERS)
    if resp.status_code == 200:
        print(f"🎉 Resumed job {job_id}")
    else:
        print(f"❌ Failed to resume job {job_id}: {resp.status_code} {resp.text}")


def update_task_status(sc_task_sys_id, new_status):
    """Update SC task status inside JSON file."""
    if not os.path.exists(SC_TASK_FILE):
        print(f"⚠️ {SC_TASK_FILE} not found, skipping update.")
        return

    with open(SC_TASK_FILE, "r") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print("⚠️ JSON decode error, resetting file.")
            data = []

    if isinstance(data, dict):
        data = [data]

    # Update matching task
    for entry in data:
        if entry.get("sc_task_sys_id") == sc_task_sys_id:
            entry["status"] = new_status

    with open(SC_TASK_FILE, "w") as f:
        json.dump(data, f, indent=4)
    print(f"📝 Updated {sc_task_sys_id} status → {new_status}")


def main():
    if not os.path.exists(SC_TASK_FILE):
        print(f"❌ {SC_TASK_FILE} not found. Exiting.")
        return

    with open(SC_TASK_FILE, "r") as f:
        data = json.load(f)

    if isinstance(data, dict):
        data = [data]

    for entry in data:
        pipeline_id = entry.get("pipeline_id")
        sc_task_sys_id = entry.get("sc_task_sys_id")
        manual_job_name = entry.get("task_name")  # default fallback

        if not sc_task_sys_id or not pipeline_id:
            print(f"⚠️ Skipping incomplete entry: {entry}")
            continue

        print(f"🔍 Checking SC Task {sc_task_sys_id} from pipeline {pipeline_id}")

        state = poll_servicenow(sc_task_sys_id)
        if state == "3":  # Closed
            update_task_status(sc_task_sys_id, "Closed")
            manual_jobs = get_manual_jobs(pipeline_id)
            for job in manual_jobs:
                if job["name"] == manual_job_name:
                    resume_job(job["id"])
                    break
            else:
                print(f"⚠️ No manual job named {manual_job_name} found in pipeline {pipeline_id}")
        else:
            print(f"⏸️ Task {sc_task_sys_id} still open.")
            update_task_status(sc_task_sys_id, "Open")

    print("✅ Polling completed for all SC Tasks.")


if __name__ == "__main__":
    main()
