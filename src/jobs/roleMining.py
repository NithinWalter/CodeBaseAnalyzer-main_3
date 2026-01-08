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
                              role_granularity=0.5, popularity=10, max_k=10):

    # Load entitlement matrix JSON
    test_string ="""
        {
  "users": [
      "admin",
      "vibhutisinha",
      "Harsh123",
      "Mukul123",
      "Geetha123",
      "Luke123",
      "JDoe09",
      "AvantiShukla54",
      "Samrat879",
      "Rohit928",
      "Ankit317",
      "SameerS806",
      "Ruchika154",
      "Geet31",
      "Nikhil699",
      "Mohit937",
      "Aditya089",
      "Grok801",
      "Pro670",
      "Lace284",
      "Sam578",
      "Trope57",
      "Worn535",
      "Sneh639",
      "Mark572",
      "Zoya84",
      "Ritik439",
      "New076",
      "Tryg633",
      "Saurav474",
      "Crew841",
      "Virk534",
      "Ak864",
      "Mohit07",
      "Mike896",
      "Jonn421",
      "Deep445",
      "Saloni21",
      "Sarah957",
      "Kavya92",
      "Eram725",
      "Sunil575",
      "Sandeep09",
      "Gill542",
      "Clark962"
  ],
  "matrix": {
      "IT": [
          1, 0, 1, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 0, 1, 0, 
          1, 0, 1, 1, 0, 1, 1, 0, 1, 1, 1, 0, 1, 0, 0, 1, 1, 1, 0, 0, 
          1, 0, 1, 0, 1, 0, 1, 1, 1
      ],
      "Cybersecurity and Risk Management": [
          0, 1, 0, 1, 1, 1, 0, 1, 1, 1, 1, 0, 1, 1, 1, 1, 0, 1, 1, 1, 
          1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1, 1, 0, 1, 
          0, 1, 0, 1, 0, 0, 1, 0, 0
      ],
      "Marketing Specialist": [
          1, 1, 0, 0, 1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 0, 1, 0, 1, 1, 1, 
          1, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0, 0, 1, 1, 1, 1, 0, 1, 0, 1, 
          1, 0, 1, 0, 1, 1, 1, 0, 1
      ]
  }
}

    """
    #with open(json_path, "r") as f:
    #    data = json.loads(f)
    data = json.loads(test_string)
    print(data)

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
        # Format like "EntitlementA (85%)"
            entitlement_with_density = [
                f"{ent_name} ({round(density * 100)}%)"
                for ent_name, density in role_entitlements.items()
            ]

            # ✅ Generate role description dynamically
            top_entitlements = list(role_entitlements.index[:3])  # pick top 3 for summary
            if len(role_entitlements) > 3:
                role_description = (
                    f"This role includes key entitlements like {', '.join(top_entitlements)}, "
                    f"and covers {len(role_entitlements)} total entitlements. "
                    f"It is assigned to {total_users} users with similar access patterns."
                )
            else:
                role_description = (
                    f"This role grants access to {', '.join(top_entitlements)} "
                    f"and is shared by {total_users} users."
                )

            # ✅ Create role object
            role_obj = {
                "role_name": role_name,
                "role_description": role_description,
                "entitlements with density": entitlement_with_density,
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
    if "ValidationResults" not in validation_data:
        validation_data["ValidationResults"] = {}

    validation_data["ValidationResults"].update({
        "RoleMiningRecommendationResult": mined_roles})

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
    print(entitlement_matrix_path)
    validation_result_path = artifacts_dir / "ValidationResult.json"
    print(validation_result_path)

    generate_roles_from_json(
        entitlement_matrix_path,
        validation_result_path,
        pipeline_id,
        role_granularity=0.5,
        popularity=10,
        max_k=10
    )
