"""
Utilities for resetting GitHub repository state via API.

Functions to change repository visibility and remove license files.
"""

import base64
import os
from typing import Optional, Tuple

import requests
from dotenv import load_dotenv

# Load environment variables from .env file, if present
load_dotenv()

# Retrieve credentials from environment. These are only needed for the GitHub API-based
# state-reset tasks, so the check is deferred to first use (github_headers) instead of module
# import -- importing state_reset must not require a GITHUB_TOKEN.
gh_token = os.getenv("GITHUB_TOKEN")
gh_username = os.getenv("GITHUB_USERNAME")


def _require_github_credentials() -> None:
    if not gh_token:
        raise ValueError("GITHUB_TOKEN environment variable is required")
    if not gh_username:
        raise ValueError("GITHUB_USERNAME environment variable is required")


def github_headers() -> dict:
    _require_github_credentials()
    return {
        "Authorization": f"Bearer {gh_token}",
        "Accept": "application/vnd.github+json",
    }


def get_repo_file(repo_id: str, path: str) -> Optional[Tuple[str, str]]:
    url = f"https://api.github.com/repos/{repo_id}/contents/{path}"
    response = requests.get(url, headers=github_headers())
    if response.status_code == 404:
        return None
    response.raise_for_status()
    data = response.json()
    encoded = data["content"].replace("\n", "")
    content = base64.b64decode(encoded).decode("utf-8")
    return content, data["sha"]


def delete_repo_file(repo_id: str, path: str, sha: str, message: str) -> None:
    url = f"https://api.github.com/repos/{repo_id}/contents/{path}"
    payload = {
        "message": message,
        "sha": sha,
    }
    response = requests.delete(url, headers=github_headers(), json=payload)
    response.raise_for_status()


def make_repo_public(repo_name: str) -> None:
    """
    Make the specified GitHub repository public.

    Args:
        repo_name: Repository name (without owner).
    """
    repo_id = f"{gh_username}/{repo_name}"
    url = f"https://api.github.com/repos/{repo_id}"
    headers = github_headers()
    data = {"private": False}

    try:
        response = requests.patch(url, headers=headers, json=data)
        response.raise_for_status()
        print(f"Success! GitHub repository {repo_id} is now public.")
    except requests.RequestException as exc:
        raise Exception(f"Failed to update repository visibility for {repo_id}: {str(exc)}")


def remove_repo_license(repo_name: str) -> None:
    """
    Remove the LICENSE file from the specified GitHub repository.
    
    Args:
        repo_name: Repository name (without owner).
    """
    repo_id = f"{gh_username}/{repo_name}"

    try:
        license_file = get_repo_file(repo_id, "LICENSE")
        if license_file:
            _, license_sha = license_file
            delete_repo_file(
                repo_id,
                "LICENSE",
                license_sha,
                "Remove LICENSE file",
            )
            print(f"Success! Removed LICENSE file from {repo_id}.")
        else:
            print(f"LICENSE file not found in {repo_id}.")

    except requests.RequestException as exc:
        raise Exception(f"Failed to remove LICENSE file from {repo_id}: {str(exc)}")

