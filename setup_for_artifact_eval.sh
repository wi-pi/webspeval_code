#!/usr/bin/env bash
# Setup + functional test for the WebSP-Eval artifact. Run from the repo root.
# Provide first: .env (OPENROUTER_API_KEY + WEBSP_ACCOUNT_*), src/test_profile/, and the Wolfram
# login trace at login_traces/Wolfram_login/session_Wolfram_login.json (download from the portal).
set -eo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

source "$(conda info --base)/etc/profile.d/conda.sh"
conda env list | grep -qE '^webspeval\s' || conda create -n webspeval python=3.10 -y
conda activate webspeval
pip install -r requirements.txt

# Register the login trace, then resolve the <LOGIN_FILE_Wolfram> placeholder in the tasks.
sed -i.bak 's#^Wolfram,.*#Wolfram,login_traces/Wolfram_login/session_login/session_Wolfram_login.json#' dataset/login_files.csv
rm -f dataset/login_files.csv.bak
python tools/fill_login_files.py

# Run the documented functional test (Wolfram_task-7 ON/OFF).
mkdir -p outputs
python src/run_with_replay.py \
  --test_file dataset/artifact_test.jsonl \
  --model_type gemini \
  --api_model google/gemma-3-27b-it \
  --run_with_openrouter \
  --max_iter 20 \
  --max_attached_imgs 3 \
  --temperature 1 \
  --force_light_mode \
  --seed 42 \
  --output_dir outputs/ 2>&1 | tee -a outputs/artifact_test.log
