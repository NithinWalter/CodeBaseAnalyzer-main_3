import os, sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.jobs.UpdateGitVariable import update_gitlab_variable

pipeline_id = os.getenv("CI_PIPELINE_ID")

pipeline_status={
    "status":"completed"
}
update_gitlab_variable(
        f"ValidationResult_{pipeline_id}",
        pipeline_status,
        True
    )