import os, sys
from pathlib import Path


sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.jobs.UpdateGitVariable import update_gitlab_variable

status = sys.argv[1] if len(sys.argv) > 1 else "not_completed"

pipeline_id = os.getenv("CI_PIPELINE_ID", "local")

pipeline_status = "status": status

update_gitlab_variable(
    f"ValidationResult_{pipeline_id}",
    pipeline_status,
    True
)

print(f"Validation flag updated to '{status}' for pipeline {pipeline_id}")
