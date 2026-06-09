"""storage helpers for the WebSP-Eval replay agent (split from run_with_replay.py)."""
import os
import json
import logging
import boto3
from botocore.exceptions import ClientError


def save_checkpoint(result_dir, completed_task_ids):
    """Save checkpoint of completed tasks."""
    checkpoint_file = os.path.join(result_dir, '.checkpoint.json')
    try:
        with open(checkpoint_file, 'w') as f:
            json.dump({'completed_tasks': list(completed_task_ids)}, f, indent=2)
    except Exception as e:
        logging.warning(f"Could not save checkpoint: {e}")


def load_checkpoint(result_dir):
    """Load checkpoint of completed tasks."""
    checkpoint_file = os.path.join(result_dir, '.checkpoint.json')
    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, 'r') as f:
                data = json.load(f)
                return set(data.get('completed_tasks', []))
        except Exception as e:
            logging.warning(f"Could not load checkpoint: {e}")
    return set()


def is_task_completed(result_dir, task_id):
    """Check if a task has been completed by looking for its output files."""
    task_dir = os.path.join(result_dir, f'task{task_id}')
    if not os.path.exists(task_dir):
        return False
    
    # Check for essential output files
    has_log = os.path.exists(os.path.join(task_dir, 'agent.log'))
    has_messages = os.path.exists(os.path.join(task_dir, 'interact_messages.json'))
    
    return has_log or has_messages


def get_s3_client():
    """Return an S3 client using default AWS credentials/config."""
    return boto3.client("s3")


def list_s3_result_dirs(bucket, base_prefix):
    """
    List "result directories" (top-level prefixes) under base_prefix.

    Mirrors the local behavior of listing subdirectories of args.output_dir
    when using resume without specifying --resume_dir.
    """
    base_prefix = base_prefix.rstrip("/") + "/"
    s3 = get_s3_client()
    try:
        paginator = s3.get_paginator("list_objects_v2")
        prefixes = set()
        for page in paginator.paginate(Bucket=bucket, Prefix=base_prefix, Delimiter="/"):
            for cp in page.get("CommonPrefixes", []):
                prefixes.add(cp["Prefix"].rstrip("/"))
        # Sort newest first by name (timestamps in name preserve order)
        return sorted(prefixes, reverse=True)
    except ClientError as e:
        logging.error(f"Error listing S3 result dirs under {bucket}/{base_prefix}: {e}")
        return []


def download_s3_prefix(bucket, prefix, local_root="."):
    """
    Download all objects under s3://bucket/prefix to local_root/prefix.
    """
    s3 = get_s3_client()
    prefix = prefix.rstrip("/") + "/"
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            rel_path = os.path.relpath(key, prefix)
            local_path = os.path.join(local_root, prefix, rel_path)
            local_dir = os.path.dirname(local_path)
            os.makedirs(local_dir, exist_ok=True)
            try:
                s3.download_file(bucket, key, local_path)
            except ClientError as e:
                logging.error(f"Failed to download s3://{bucket}/{key} to {local_path}: {e}")


def upload_directory_to_s3(local_dir, bucket, s3_prefix):
    """
    Recursively upload a local directory to s3://bucket/s3_prefix.
    """
    s3 = get_s3_client()
    local_dir = os.path.abspath(local_dir)
    s3_prefix = s3_prefix.rstrip("/") + "/"
    for root, _, files in os.walk(local_dir):
        for filename in files:
            local_path = os.path.join(root, filename)
            rel_path = os.path.relpath(local_path, local_dir)
            key = os.path.join(s3_prefix, rel_path).replace("\\", "/")
            try:
                s3.upload_file(local_path, bucket, key)
            except ClientError as e:
                logging.error(f"Failed to upload {local_path} to s3://{bucket}/{key}: {e}")


def upload_file_to_s3(local_path, bucket, s3_key):
    """Upload a single file to S3."""
    s3 = get_s3_client()
    try:
        s3.upload_file(local_path, bucket, s3_key)
    except ClientError as e:
        logging.error(f"Failed to upload {local_path} to s3://{bucket}/{s3_key}: {e}")
