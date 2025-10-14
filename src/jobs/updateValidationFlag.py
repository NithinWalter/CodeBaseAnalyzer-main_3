import os
from src.jobs.UpdateGitVariable import update_gitlab_variable

pipeline_id = os.getenv("CI_PIPELINE_ID")
# Dynamic variable name per pipeline
validation_var = f"VALIDATION_COMPLETE_{pipeline_id}"

# Update the flag to True
success = update_gitlab_variable(validation_var, True)

if success:
    print(f"✅ Updated {validation_var} to True")
else:
    print(f"❌ Failed to update {validation_var}")
