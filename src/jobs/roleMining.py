import os, sys, logging, requests
import json, base64, urllib3
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from pathlib import Path
import logging

# class file imports
sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.jobs.UpdateGitVariable import update_gitlab_variable

logger = logging.getLogger("role_mining")

def generate_roles_from_json(json_path, validation_json_path, pipeline_id,
                              role_granularity=0.5, popularity=3, max_k=10):
    # Load entitlement matrix JSON
    with open(json_path, "r") as f:
        data = json.load(f)

    users = data["users"]
    matrix_dict = data["matrix"]

    for key, values in matrix_dict.items():
        if len(values) < len(users):
        # pad with zeros
            matrix_dict[key] = values + [0] * (len(users) - len(values))
        elif len(values) > len(users):
        # trim extras
            matrix_dict[key] = values[:len(users)]

    df = pd.DataFrame(matrix_dict, index=users)

   

    # Determine best number of clusters
    X = df.values
    best_k = 0
    best_score = -1
    for k in range(2, min(max_k, len(users))):
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = kmeans.fit_predict(X)
        score = silhouette_score(X, labels)
        if score > best_score:
            best_score = score
            best_k = k

    # Final clustering
    kmeans = KMeans(n_clusters=best_k, random_state=42, n_init=10)
    df["Cluster"] = kmeans.fit_predict(X)

    entitlements = [col for col in df.columns if col != "Cluster"]
    mined_roles = []

    for cluster_id in df["Cluster"].unique():
        role_name = f"Role_{cluster_id}"
        cluster_users = df[df["Cluster"] == cluster_id]
        total_users = len(cluster_users)

        if total_users < popularity:
            continue

        # Calculate entitlement density
        density_series = cluster_users[entitlements].sum() / total_users
        role_entitlements = density_series[density_series >= role_granularity]

        if not role_entitlements.empty:
            role_obj = {
                "role_name": role_name,
                "entitlements": role_entitlements.index.tolist(),
                "density": role_entitlements.round(2).tolist(),
                "users": cluster_users.index.tolist(),
                "popularity": total_users
            }
            mined_roles.append(role_obj)

    # Load or create ValidationResult.json
    if validation_json_path.exists():
        with open(validation_json_path, "r") as f:
            validation_data = json.load(f)
    else:
        validation_data = {"ValidationResults": {}}

    # Add MRVS data as a list of role objects
    validation_data.setdefault("ValidationResults", {})["RoleMiningRecommendationResult"] = mined_roles

    # Save updated ValidationResult.json
    with open(validation_json_path, "w") as f:
        json.dump(validation_data, f, indent=2)

    # Update GitLab variable
    update_gitlab_variable(
        f"ValidationResult_{pipeline_id}",
        validation_data,
        False
    )

    logger.info("Appended MRVS role mining results to ValidationResult.json and updated GitLab variable.")
    
    # Print final JSON 
    print("\n===== Final ValidationResult.json =====\n")
    print(json.dumps(validation_data, indent=2))

if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[2]
    artifacts_dir = repo_root / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    pipeline_id = os.getenv("CI_PIPELINE_ID", "local")

    entitlement_matrix_path = artifacts_dir / "userEntitlementsMatrix.json"
    validation_result_path = artifacts_dir / "ValidationResult.json"

    generate_roles_from_json(
        entitlement_matrix_path,
        validation_result_path,
        pipeline_id,
        role_granularity=0.6,
        popularity=3,
        max_k=10
    )
