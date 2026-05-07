import os
from git import Repo


def clone_repo(repo_url: str) -> str:
    repo_name = repo_url.split("/")[-1].replace(".git", "")
    local_path = os.path.join("repos", repo_name)

    if not os.path.exists("repos"):
        os.makedirs("repos")

    if not os.path.exists(local_path):
        Repo.clone_from(repo_url, local_path)

    return local_path