import os, sys, json
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.jobs.UpdateGitVariable import update_gitlab_variable

status = sys.argv[1] if len(sys.argv) > 1 else "not_completed"
pipeline_id = os.getenv("CI_PIPELINE_ID", "local")

repo_root = Path(__file__).resolve().parents[2]
artifacts_dir = repo_root / "artifacts"
artifacts_dir.mkdir(parents=True, exist_ok=True)

reportFile = artifacts_dir / "ValidationResult.json"

# Load existing ValidationResult.json
if reportFile.exists():
    with open(reportFile, "r") as f:
        validation_data = json.load(f)
else:
    validation_data = {"ValidationResults": {}}

# Ensure ValidationResults exists
validation_data.setdefault("ValidationResults", {})

# Update status
validation_data["ValidationResults"]["status"] = status

# Save back to ValidationResult.json
with open(reportFile, "w") as f:
    json.dump(validation_data, f, indent=2)

print(json.dumps(validation_data, indent=2))

# Update GitLab variable
final_validation_result = update_gitlab_variable(
    f"ValidationResult_{pipeline_id}", validation_data, False
)

print(f"Validation flag updated to '{status}' for pipeline {pipeline_id}")
