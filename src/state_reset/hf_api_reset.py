"""
Utilities for resetting Hugging Face repository state via API.

Functions to change repository visibility, remove gated access, remove licenses, and delete datasets.
"""

import os
import re
import tempfile
from typing import Literal
from dotenv import load_dotenv
from huggingface_hub import HfApi



def make_repo_public(repo_name: str, repo_type: Literal["dataset", "model"]) -> None:
    """
    Make a Hugging Face repository (dataset or model) public.
    
    Args:
        repo_name: Name of the repository (dataset or model)
        repo_type: Type of repository - "dataset" or "model"
    """
   
    # Load the essential environment variables for accessing the Hugging Face API
    load_dotenv()

    # Get token and username from .env
    hf_token = os.getenv("HF_TOKEN")
    hf_username = os.getenv("HF_USERNAME")

    repo_id = f"{hf_username}/{repo_name}"
    
    try:
        # Initialize API
        api = HfApi(token=hf_token)
        
        # Update repository visibility to public
        # This will work even if it's already public (idempotent)
        api.update_repo_settings(
            repo_id=repo_id, 
            repo_type=repo_type, 
            private=False
        )
        print(f"Success! {repo_type.capitalize()} {repo_id} is now public.")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        raise Exception(f"Failed to make {repo_type.capitalize()} {repo_id} public: {str(e)}")


def remove_gated_access(dataset_name: str) -> None:
    """
    Remove gated access requirements from a Hugging Face dataset repository.
    
    Args:
        dataset_name: Name of the dataset
    """

    # Load the essential environment variables for accessing the Hugging Face API
    load_dotenv()

    # Get token and username from .env
    hf_token = os.getenv("HF_TOKEN")
    hf_username = os.getenv("HF_USERNAME")
    
    repo_id = f"{hf_username}/{dataset_name}"
    
    try:
        api = HfApi(token=hf_token)
        api.update_repo_settings(
            repo_id=repo_id,
            repo_type="dataset",
            gated=False
        )
        print(f"Success! Gated access removed for dataset {repo_id}.")
    except Exception as e:
        print(f"Error: {str(e)}")
        raise Exception(f"Failed to remove gated access from dataset {repo_id}: {str(e)}")


def remove_dataset_licenses(dataset_name: str) -> None:
    """
    Remove all license information from a Hugging Face dataset repository.
    
    Args:
        dataset_name: Name of the dataset
    """
    # Load the essential environment variables for accessing the Hugging Face API
    load_dotenv()

    # Get token and username from .env
    hf_token = os.getenv("HF_TOKEN")
    hf_username = os.getenv("HF_USERNAME")

    repo_id = f"{hf_username}/{dataset_name}"
    
    try:
        # Initialize API
        api = HfApi(token=hf_token)
        
        # Download the README.md file
        readme_content = api.hf_hub_download(
            repo_id=repo_id,
            filename="README.md",
            repo_type="dataset"
        )
        
        # Read the current content
        with open(readme_content, "r", encoding="utf-8") as f:
            content = f.read()
        # Remove license from YAML frontmatter (if present)
        # Match YAML frontmatter between --- markers
        yaml_pattern = r'^---\s*\n(.*?)\n---\s*\n'
        yaml_match = re.match(yaml_pattern, content, re.DOTALL | re.MULTILINE)
        
        if yaml_match:
            yaml_content = yaml_match.group(1)
            # Remove license-related fields (case-insensitive)
            yaml_lines = yaml_content.split('\n')
            filtered_yaml_lines = []
            for line in yaml_lines:
                # Skip lines that are license-related (license, licenses, license_id, etc.)
                # Match YAML key format: key: value or key: "value" or key: [value]
                if not re.match(r'^\s*(license|licenses|license_id|license_name|license_url|license_link)\s*[:]', line, re.IGNORECASE):
                    filtered_yaml_lines.append(line)
            
            if not any(line.strip() for line in filtered_yaml_lines):
                # Entire frontmatter was license info; remove the frontmatter block
                content = content[yaml_match.end():]
            else:
                # Reconstruct content with cleaned YAML
                new_yaml = '\n'.join(filtered_yaml_lines)
                content = re.sub(yaml_pattern, f'---\n{new_yaml}\n---\n', content, flags=re.DOTALL | re.MULTILINE)
        
        # Remove license sections from markdown content
        # Remove ## License or ## Licenses sections
        content = re.sub(r'##+\s*License[s]?\s*[^\n]*\n.*?(?=\n##|\Z)', '', content, flags=re.IGNORECASE | re.DOTALL)
        
        # Remove inline license mentions in YAML-style lists
        content = re.sub(r'^\s*-\s*license[s]?:.*$', '', content, flags=re.IGNORECASE | re.MULTILINE)
        
        # Remove license tags or badges if present
        content = re.sub(r'\[!\[.*?license.*?\]\(.*?\)\]\(.*?\)', '', content, flags=re.IGNORECASE)
        content = re.sub(r'!\[.*?license.*?\]\(.*?\)', '', content, flags=re.IGNORECASE)
        
        # Clean up any double newlines that might have been created
        content = re.sub(r'\n\n\n+', '\n\n', content)
        
        # Create a temporary file with the modified content
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.md') as tmp_file:
            tmp_file.write(content)
            tmp_file_path = tmp_file.name
        
        # Upload the modified README.md back to the repository
        api.upload_file(
            path_or_fileobj=tmp_file_path,
            path_in_repo="README.md",
            repo_id=repo_id,
            repo_type="dataset",
            commit_message="Remove license information from dataset card"
        )
        
        # Clean up temporary file
        os.unlink(tmp_file_path)
        
        print(f"Success! All licenses removed from dataset {repo_id}.")
        
    except Exception as e:
        print(f" Error: {str(e)}")
        raise Exception(f"Failed to remove licenses from dataset {repo_id}: {str(e)}")


def remove_dataset(dataset_name: str) -> None:
    """
    Delete a Hugging Face dataset repository from the account.
    
    WARNING: This action is irreversible. The dataset will be permanently deleted.
    
    Args:
        dataset_name: Name of the dataset to delete
    """
    # Load the essential environment variables for accessing the Hugging Face API
    load_dotenv()

    # Get token and username from .env
    hf_token = os.getenv("HF_TOKEN")
    hf_username = os.getenv("HF_USERNAME")

    repo_id = f"{hf_username}/{dataset_name}"
    
    try:
        # Initialize API
        api = HfApi(token=hf_token)
        
        # Delete the dataset repository
        api.delete_repo(
            repo_id=repo_id,
            repo_type="dataset"
        )
        
        print(f"Success! Dataset {repo_id} has been permanently deleted.")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        raise Exception(f"Failed to delete dataset {repo_id}: {str(e)}")
