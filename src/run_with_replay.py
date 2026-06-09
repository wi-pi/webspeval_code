"""
This script runs privacy and security tasks on websites using web agents based on tasks specified in a jsonl file using a modified version of WebVoyager.
WebVoyager-based implementation for executing privacy and security tasks on websites using web agents. 

The setup of WebVoyager is as follows:
1. It uses selenium to control the browser.
2. It opens a URL in the task-details JSON dict. 
3. Then finds the interactive elements on the page.
4. Passes the screenshot and the user messages to the model. 
5. The model returns an action (click, type, scroll, wait, goback, google, answer).
6. The action is executed on the browser.
7. The process repeats until the task is completed or it reaches the maximum number of iterations.

We make the following modifications to the WebVoyager code:
1. Do not count the iterations for the "Scroll" and "Wait" actions.
2. Improve/Enable scrolling functionality.
3. Give option to use different models/APIs.
4. Force light mode in the browser for the models to understand the elements.
5. Enable passing a chrome profile directory to the script for a user to use login and other functions necessary for 
security and privacy tasks.
"""
import argparse
import time
import json
import re
import os
import shutil
import logging
import random
from tqdm import tqdm

from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from urllib3.exceptions import ReadTimeoutError
from anthropic import AnthropicVertex
from google import genai

from prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_TEXT_ONLY
from openai import OpenAI
from utils import get_web_element_rect, encode_image, extract_information, print_message,\
    get_webarena_accessibility_tree, get_pdf_retrieval_ans_from_assistant, clip_message_and_obs,\
    clip_message_and_obs_text_only, check_cloudflare
from api_utils import (
    format_msg_claude, format_msg_gpt5, format_msg_gemini,
    format_msg_text_only_gpt5, format_msg_text_only_claude, format_msg_text_only_gemini,
    call_claude_api, call_gpt5_api, call_gemini_api
)

from dotenv import load_dotenv

from state_reset import execute_login, logout_inactive

load_dotenv()

# --- agent modules (split out of this file; see src/agent/) ---
from agent.driver import cleanup_temp_profile, initialize_driver_for_taskid
from agent.storage import (save_checkpoint, load_checkpoint, list_s3_result_dirs,
                           download_s3_prefix, upload_directory_to_s3, upload_file_to_s3)
from agent.state import execute_state_reset
from agent.actions import (safe_remove_element, exec_action_click, exec_action_hover,
                           exec_action_type, exec_action_scroll, exec_action_scroll_to_end,
                           exec_action_scroll_within_popup, get_tabs_info, switch_to_tab_by_url)

CLAUDE_MODELS=["claude-sonnet-4-5@20250929","claude-haiku-4-5@20251001"]
GPT_MODELS=["gpt-5.1", "gpt-5-mini"]
GEMINI_MODELS=["gemini-2.5-flash", "gemini-2.5-pro","gemma-3-27b-it","gemini-3-pro-preview","gemini-3.1-pro-preview"]
OPENROUTER_MODELS=["google/gemma-3-27b-it"]

def setup_logger(folder_path):
    log_file_path = os.path.join(folder_path, 'agent.log')

    logger = logging.getLogger()
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

    handler = logging.FileHandler(log_file_path)
    formatter = logging.Formatter('%(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)




















AWS_S3_BUCKET = os.environ.get("AWS_S3_BUCKET", "")





































def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test_file', type=str, default='data/test.json')
    parser.add_argument('--max_iter', type=int, default=5)
    parser.add_argument("--output_dir", type=str, default='results')
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--max_attached_imgs", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--download_dir", type=str, default="downloads")
    parser.add_argument("--text_only", action='store_true')
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--worker_id", type=int, default=0)

    # for web browser
    parser.add_argument("--headless", action='store_true', help='The window of selenium')
    parser.add_argument("--save_accessibility_tree", action='store_true')
    parser.add_argument("--force_device_scale", action='store_true')
    parser.add_argument("--window_width", type=int, default=1280)
    parser.add_argument("--window_height", type=int, default=1024)  # for headless mode, there is no address bar
    #parser.add_argument("--fix_box_color", action='store_true')
    parser.add_argument("--chrome_user_data_dir", type=str, default=None)
    parser.add_argument("--chrome_profile_dir_name", type=str, default=None)
    parser.add_argument("--web_names", type=str, default=None, help='Comma separated list of web names to process')
    parser.add_argument("--skip_web_names", type=str, default=None, help='Comma separated list of web names to skip')
    parser.add_argument("--task_id", type=str, default=None, help='Comma separated list of task IDs to process (e.g., "task1,task2")')
    parser.add_argument("--force_light_mode", action='store_true')
    parser.add_argument("--tor", action='store_true')
    
    # Resume functionality
    parser.add_argument("--resume", action='store_true', help='Resume from existing result directory')
    parser.add_argument("--resume_dir", type=str, default=None, help='Specific result directory to resume from')
    parser.add_argument('--include_login', action='store_true', help='Execute login replay before task')
    
    #Test profile directory name
    parser.add_argument("--test_profile_dir_name", type=str, default=None)

    ##Models/APIs related arguments
    parser.add_argument("--model_type", type=str, default='gpt', 
    help='What type of model/API to use? The options are gpt, claude, gemini.'
    'Use the option with the corresponding api_model name.')
    parser.add_argument("--api_key", default="key", type=str, help="YOUR_OPENAI_API_KEY")
    parser.add_argument("--api_model", default="gpt-5-mini", type=str, help="api model name")
    parser.add_argument("--thinking_model", action='store_true', help='Use this when you wanna store the thinking output of the thinking models')
    parser.add_argument("--max_task_time", type=int, default=600, help='Maximum time (in seconds) to run the main task execution. Default: 600 (10 minutes). Does not include login or state reset time.')
    parser.add_argument("--run_gpt_with_azure", action='store_true', help='Use Azure OpenAI endpoints instead of OpenAI endpoints for GPT models')
    parser.add_argument("--run_with_openrouter", action='store_true', help='Use OpenRouter endpoints (OpenAI-compatible) via the OpenAI SDK for model_type=gemini (e.g. gemma). api_model must be in OPENROUTER_MODELS.')

    # AWS / S3 output options
    parser.add_argument(
        "--output_in_aws",
        action="store_true",
        help="If set, mirror all outputs to S3 bucket at the same result_dir prefix and support resume from S3.",
    )

    args = parser.parse_args()
    
    #Load and initialize environment variables
    load_dotenv()
    
    model_type = args.model_type

    if model_type == 'gpt':
        #Check api_model is in GPT_MODELS
        if args.api_model not in GPT_MODELS:
            raise ValueError(f"API model {args.api_model} is not in GPT_MODELS")
        api_call= call_gpt5_api
        format_msg = format_msg_gpt5
        format_msg_text_only = format_msg_text_only_gpt5
        
        if args.run_gpt_with_azure:
            endpoint = os.getenv("ENDPOINT_URL")
            client = OpenAI(
                api_key=os.environ["AZURE_OPENAI_KEY"],
                base_url=endpoint,
            )
        else:
            openai_api_key = os.getenv("OPENAI_API_KEY")
            if not openai_api_key:
                raise ValueError("OPENAI_API_KEY environment variable must be set when using OpenAI endpoints. Pass --run_gpt_with_azure to use Azure endpoints instead.")
            client = OpenAI(
                api_key=openai_api_key,
            )
    elif model_type == 'claude':
        #Check api_model is in CLAUDE_MODELS
        if args.api_model not in CLAUDE_MODELS:
            raise ValueError(f"API model {args.api_model} is not in CLAUDE_MODELS")
        api_call = call_claude_api
        format_msg = format_msg_claude
        format_msg_text_only = format_msg_text_only_claude
        
       
        LOCATION = os.getenv("VERTEX_AI_LOCATION", "us-east5")
        PROJECT_ID = os.getenv("VERTEX_AI_PROJECT_ID")
        
        if not PROJECT_ID:
            raise ValueError("VERTEX_AI_PROJECT_ID environment variable must be set. Please set it in your .env file or environment.")
        
        # AnthropicVertex client
        client = AnthropicVertex(region=LOCATION, project_id=PROJECT_ID)
    elif model_type == 'gemini':
        if args.run_with_openrouter:
            if args.api_model not in OPENROUTER_MODELS:
                raise ValueError(f"API model {args.api_model} is not in OPENROUTER_MODELS")
            openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
            if not openrouter_api_key:
                raise ValueError("OPENROUTER_API_KEY environment variable must be set when using --run_with_openrouter.")
            # OpenRouter is OpenAI-compatible: use the OpenAI SDK + gpt5 chat-completions helpers
            api_call = call_gpt5_api
            format_msg = format_msg_gpt5
            format_msg_text_only = format_msg_text_only_gpt5
            client = OpenAI(
                api_key=openrouter_api_key,
                base_url="https://openrouter.ai/api/v1",
            )
        else:
            api_key = os.getenv("GEMINI_API_KEY")
            #Check api_model is in GEMINI_MODELS
            if args.api_model not in GEMINI_MODELS:
                raise ValueError(f"API model {args.api_model} is not in GEMINI_MODELS")
            api_call = call_gemini_api
            format_msg = format_msg_gemini
            format_msg_text_only = format_msg_text_only_gemini

            # Gemini client with Vertex AI
            client = genai.Client(api_key=api_key)

    else:
        raise ValueError(f"Model type {model_type} is not supported")
    
    
    

    

    # Save Result file - handle resume mode (local + optional S3 mirroring)
    use_s3 = args.output_in_aws
    if args.resume and args.resume_dir:
        # When resuming with a specific directory, treat resume_dir as the result_dir
        result_dir = args.resume_dir
        print(f"Resuming from existing directory: {result_dir}")
        # If using S3, ensure local mirror exists by downloading from S3
        if use_s3 and not os.path.exists(result_dir):
            print(f"Downloading previous results from s3://{AWS_S3_BUCKET}/{result_dir} ...")
            download_s3_prefix(AWS_S3_BUCKET, result_dir, ".")
    elif args.resume:
        # Find the most recent result directory
        if use_s3:
            # List "directories" under the S3 prefix corresponding to args.output_dir
            s3_result_dirs = list_s3_result_dirs(AWS_S3_BUCKET, args.output_dir)
            if s3_result_dirs:
                # s3_result_dirs already contains full prefixes like "results/2025..."
                result_dir = s3_result_dirs[0]
                print(f"Resuming from most recent S3 directory: s3://{AWS_S3_BUCKET}/{result_dir}")
                # Mirror to local filesystem
                download_s3_prefix(AWS_S3_BUCKET, result_dir, ".")
            else:
                print("No existing S3 result directory found. Starting fresh.")
                current_time = time.strftime("%Y%m%d_%H_%M_%S", time.localtime())
                result_dir = os.path.join(args.output_dir, current_time)
                os.makedirs(result_dir, exist_ok=True)
        else:
            result_dirs = [d for d in os.listdir(args.output_dir) if os.path.isdir(os.path.join(args.output_dir, d))]
            if result_dirs:
                result_dirs.sort(reverse=True)
                result_dir = os.path.join(args.output_dir, result_dirs[0])
                print(f"Resuming from most recent directory: {result_dir}")
            else:
                print("No existing result directory found. Starting fresh.")
                current_time = time.strftime("%Y%m%d_%H_%M_%S", time.localtime())
                result_dir = os.path.join(args.output_dir, current_time)
                os.makedirs(result_dir, exist_ok=True)
    else:
        current_time = time.strftime("%Y%m%d_%H_%M_%S", time.localtime())
        result_dir = os.path.join(args.output_dir, current_time)
        os.makedirs(result_dir, exist_ok=True)
        # Optionally create a marker object in S3 so the prefix appears immediately
        if use_s3:
            marker_path = os.path.join(result_dir, ".s3_marker")
            try:
                os.makedirs(os.path.dirname(marker_path), exist_ok=True)
                with open(marker_path, "w") as f:
                    f.write("S3 run marker")
                upload_file_to_s3(
                    marker_path,
                    AWS_S3_BUCKET,
                    os.path.join(result_dir, ".s3_marker").replace("\\", "/"),
                )
            except Exception as e:
                logging.warning(f"Could not create S3 marker file: {e}")

    # Load tasks
    tasks = []
    with open(args.test_file, 'r', encoding='utf-8') as f:
        for line in f:
            tasks.append(json.loads(line))

    # Filter by task_id if specified (before worker distribution)
    if args.task_id:
        task_ids = [tid.strip() for tid in args.task_id.split(',')]
        original_count = len(tasks)
        tasks = [t for t in tasks if t.get('id') in task_ids]
        print(f"Only processing tasks with task_ids: {task_ids}")
        
        if len(tasks) == 0:
            print(f"Warning: No tasks found matching the specified task_id(s): {task_ids}")
            return

    # Distributed settings
    # Calculate distributed size based on total tasks and workers
    total_tasks = len(tasks)
    distributed_size = (total_tasks + args.workers - 1) // args.workers
    start_index = args.worker_id * distributed_size
    end_index = min(start_index + distributed_size, total_tasks)
    tasks = tasks[start_index:end_index]
    if args.web_names:
        web_names = args.web_names.split(',')
        tasks = [t for t in tasks if t['web_name'] in web_names]
        print(f"Only processing tasks for web_names: {web_names}")
    if args.skip_web_names:
        skip_web_names = args.skip_web_names.split(',')
        tasks = [t for t in tasks if t['web_name'] not in skip_web_names]
        print(f"Skipping tasks for web_names: {skip_web_names}")
    print(f"Worker {args.worker_id} processing tasks from index {start_index} to {end_index - 1}")
    print(f"Saving results to {result_dir}")

    # Load checkpoint if resuming
    completed_task_ids = load_checkpoint(result_dir) if args.resume else set()
    
    # Filter out already completed tasks
    if completed_task_ids:
        original_count = len(tasks)
        tasks = [t for t in tasks if t['id'] not in completed_task_ids]
        print(f"Resuming: Skipping {original_count - len(tasks)} already completed tasks")
        print(f"Remaining tasks to process: {len(tasks)}")

    # Shuffle tasks if requested
    
    random.shuffle(tasks)
    print(f"Tasks shuffled randomly")

    # Create progress bar
    progress_bar = tqdm(tasks, desc="Processing tasks", unit="task")
    
    for task in progress_bar:
        # Update progress bar description with current task
        progress_bar.set_description(f"Processing task {task['id']}")
        
        # Skip password task types (not yet implemented)
        task_type = task.get('task_type')
        if task_type in ['password']:
            logging.info(f"Skipping task {task['id']} with type '{task_type}' (not yet implemented)")
            continue
        
        task_dir = os.path.join(result_dir, 'task{}'.format(task["id"]))
        os.makedirs(task_dir, exist_ok=True)
        setup_logger(task_dir)
        logging.info(f'########## TASK{task["id"]} ##########')

        captcha_setup = task.get('captcha_setup', False)

        # Execute state reset operations that don't require driver (API-like, history, hf_access_token)
        state_reset_ops = task.get('state_reset_ops')
        if state_reset_ops:
            reset_type = state_reset_ops.get('type')
            if reset_type in ['api', 'hf_access_token']:
                logging.info(f"Executing {reset_type} state reset before driver creation for task {task['id']}")
                execute_state_reset(state_reset_ops, driver_task=None, task=task)
        
        # we need to perform the reset state for logout_inactive before we login to the driver for the task. 
        if task_type=='logout_inactive':
            logout_inactive(task)
            logging.info("Logout inactive completed!")
        # Create fresh driver for THIS task
        # If login requires extension, enable it
        use_extension_for_login = task.get('login') and task.get('login_with_extension', False)
        logging.info(f"Creating fresh driver for task {task['id']}" + (f" (with extension for login)" if use_extension_for_login else ""))
        driver_task, profile_dir = initialize_driver_for_taskid(args, task['id'], use_extension=use_extension_for_login, captcha_setup=captcha_setup)

        if captcha_setup:
            check_cloudflare(driver_task)
        
        # Execute login if login_click_file is specified in task JSON
        if task.get('login'):
            execute_login(driver_task, task, web_url=task.get('web'))
            print("Login completed!")
            print("Waiting 5 seconds to observe the state...")
            time.sleep(5)
            
            # Validate window after login and wait period
            try:
                # Check if current window is still valid
                try:
                    driver_task.current_window_handle
                    logging.info("Window validation passed after login")
                except Exception as window_error:
                    error_msg = str(window_error)
                    if "no such window" in error_msg or "target window already closed" in error_msg:
                        logging.warning("Current window is closed after login. Checking for available windows...")
                        # Try to switch to any available window
                        available_handles = driver_task.window_handles
                        if available_handles:
                            driver_task.switch_to.window(available_handles[0])
                            logging.info(f"Switched to available window after login: {available_handles[0]}")
                        else:
                            logging.error("No available windows found after login. Cannot proceed with state reset.")
                    else:
                        raise window_error
            except Exception as e:
                logging.warning(f"Window validation after login failed: {e}")
            
            logging.info("Login completed, restarting driver with same profile...")
            # Close and reopen the driver with the same temp profile directory
            # This ensures a clean browser state while preserving login session
            #driver_task.quit()
            #time.sleep(2)  # Brief wait for cleanup
            #driver_task, profile_dir = initialize_driver_for_taskid(args, task['id'], profile_dir)
            #logging.info("Driver restarted after login")

        else:
            #Open the driver with the website url and then wait for 5 seconds (Gives google auto sign in time to finish)
            try:
                driver_task.get(task['web'])
                time.sleep(5)
                driver_task.refresh()
                time.sleep(2)
                print("Page refreshed to restore login session")
            
            except (TimeoutException, ReadTimeoutError, Exception) as e:
                logging.warning(f"Page load timed out for {task['web']} during initial navigation: {type(e).__name__}. Continuing...")
        # Execute state reset operations that require driver (extension, cookies)
        if state_reset_ops:
            print("State reset operations:")
            print(state_reset_ops)
            reset_type = state_reset_ops.get('type')
            if reset_type in ['cookies', 'history']:
                logging.info(f"Skipping state reset for task {task['id']}: task type {reset_type}")
                
            elif reset_type in ['extension']:
                logging.info(f"Executing {reset_type} state reset for task {task['id']}")
                execute_state_reset(state_reset_ops, driver_task=driver_task, task=task)
               
                
                logging.info("Extension state reset completed, restarting driver with same profile...")
                # Close and reopen the driver with the same temp profile directory
                # This ensures a clean browser state while preserving the reset state
                #driver_task.quit()
                #time.sleep(2)  # Brief wait for cleanup
                #driver_task, profile_dir = initialize_driver_for_taskid(args, task['id'], profile_dir)
                #logging.info("Driver restarted after extension state reset")
            # elif reset_type in ['history']:
            #     logging.info(f"Skipping history state reset for task {task['id']}")
        
        
        
        try:
            # Navigate to the task's URL
            try:
                driver_task.get(task['web'])
                #Add a delay to let the page load and any login process to complete
                time.sleep(5)
                driver_task.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
                    "width": args.window_width,
                    "height": args.window_height,
                    "deviceScaleFactor": 1,
                    "mobile": False
                })
                if captcha_setup:
                    check_cloudflare(driver_task)
                logging.info(f"Navigated to: {task['web']}")
                driver_task.refresh()
                if captcha_setup:
                    check_cloudflare(driver_task)
                time.sleep(2)
                print("Page refreshed to restore login session")
            except TimeoutException:
                logging.warning(f"Page load timed out for {task['web']} during task navigation. Continuing...")
            except Exception as e:
                logging.error(f"Failed to navigate to {task['web']}: {e}")
            try:
                driver_task.find_element(By.TAG_NAME, 'body').click()
                if captcha_setup:
                    check_cloudflare(driver_task)
            except:
                pass
            # sometimes enter SPACE, the page will sroll down
            #driver_task.execute_script("""window.onkeydown = function(e) {if(e.keyCode == 32 && e.target.type != 'text' && e.target.type != 'textarea') {e.preventDefault();}};""")
            #time.sleep(2)

            # We only deal with PDF file
            if os.path.exists(args.download_dir):
                for filename in os.listdir(args.download_dir):
                    file_path = os.path.join(args.download_dir, filename)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
            else:
                logging.warning(f"Download directory {args.download_dir} does not exist. Creating it...")
                os.makedirs(args.download_dir, exist_ok=True)

            download_files = []  # sorted(os.listdir(args.download_dir))

            fail_obs = ""  # When error execute the action
            pdf_obs = ""  # When download PDF file
            warn_obs = ""  # Type warning
            pattern = r'Thought:|Action:|Observation:'

            messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
            obs_prompt = "Observation: please analyze the attached screenshot and give the Thought and Action. "
            if args.text_only:
                messages = [{'role': 'system', 'content': SYSTEM_PROMPT_TEXT_ONLY}]
                obs_prompt = "Observation: please analyze the accessibility tree and give the Thought and Action."

            init_msg = f"""Now given a task: {task['ques']}  Please interact with https://www.example.com and get the answer. \n"""
            init_msg = init_msg.replace('https://www.example.com', task['web'])
            init_msg = init_msg + obs_prompt

            it = 0
            accumulate_prompt_token = 0
            accumulate_completion_token = 0
            thoughts_list = []  # Initialize list to store thoughts from each iteration
            all_tabs_info = {}  # Track all tabs across the entire session

            # Record start time for task execution timeout (excludes login and state reset)
            task_start_time = time.time()
            logging.info(f"Task execution started. Max time limit: {args.max_task_time} seconds")

            while it < args.max_iter:
                # Check if task execution time limit has been exceeded
                elapsed_time = time.time() - task_start_time
                if elapsed_time >= args.max_task_time:
                    logging.warning(f"Task execution time limit ({args.max_task_time}s) exceeded. Elapsed time: {elapsed_time:.2f}s. Stopping task and moving to next.")
                    logging.warning(f"Task {task['id']} did not complete within the time limit.")
                    break
                logging.info(f'Iter: {it}')
                it += 1 ## The iteration count is incremented here. But it is subtracted inside if the action is "Scroll" or "Wait"
                if not fail_obs:
                    try:
                        # Check if the browser window is still available
                        try:
                            driver_task.current_window_handle
                        except:
                            logging.error('Browser window has been closed unexpectedly.')
                            break
                    
                        # Get current tab information and update global tab tracker
                        current_tabs_info = get_tabs_info(driver_task)
                        all_tabs_info.update(current_tabs_info)  # Merge with existing tabs
                    
                        # Remove tabs that no longer exist
                        current_handles = set(driver_task.window_handles)
                        all_tabs_info = {handle: info for handle, info in all_tabs_info.items() 
                                       if handle in current_handles}
                    
                        # Update current tab status
                        current_handle = driver_task.current_window_handle
                        for handle in all_tabs_info:
                            all_tabs_info[handle]['is_current'] = (handle == current_handle)
                    
                        if not args.text_only:
                            rects, web_eles, web_eles_text = get_web_element_rect(driver_task, fix_color=False)
                        else:
                            accessibility_tree_path = os.path.join(task_dir, 'accessibility_tree{}'.format(it))
                            ac_tree, obs_info = get_webarena_accessibility_tree(driver_task, accessibility_tree_path)

                    except Exception as e:
                        error_msg = str(e)
                        if "no such window" in error_msg or "target window already closed" in error_msg:
                            logging.error('Browser window was closed unexpectedly.')
                            logging.error('This may be due to Chrome profile conflicts, system resource issues, or website redirects.')
                            logging.error('Try running with --headless flag or without Chrome profile.')
                            break
                        elif "session deleted" in error_msg or "disconnected" in error_msg:
                            logging.error('Chrome browser has disconnected or crashed.')
                            logging.error('This is likely due to profile conflicts or system resource issues.')
                            logging.error('Try running without Chrome profile or with --text_only flag.')
                            break
                        elif not args.text_only:
                            logging.error('Driver error when adding set-of-mark.')

                        else:
                            logging.error('Driver error when obtaining accessibility tree.')
                        logging.error(e)
                        break

                    img_path = os.path.join(task_dir, 'screenshot{}.png'.format(it))
                    driver_task.save_screenshot(img_path)

                    # accessibility tree
                    if (not args.text_only) and args.save_accessibility_tree:
                        accessibility_tree_path = os.path.join(task_dir, 'accessibility_tree{}'.format(it))
                        get_webarena_accessibility_tree(driver_task, accessibility_tree_path)

                    # encode image
                    b64_img = encode_image(img_path)

                    # format msg
                    if not args.text_only:
                        curr_msg = format_msg(it, init_msg, pdf_obs, warn_obs, b64_img, web_eles_text, all_tabs_info)
                    else:
                        curr_msg = format_msg_text_only(it, init_msg, pdf_obs, warn_obs, ac_tree, all_tabs_info)
                    messages.append(curr_msg)
                else:
                    # For failure screenshots, ensure bounding boxes are visible
                    ## We only save the screenshot with bounding boxes for failure cases but still
                    #do not use them for the model maintaining the same functionality as the success screenshots as WebVoyager does.
                    try:
                        if not args.text_only:
                            rects, web_eles, web_eles_text = get_web_element_rect(driver_task, fix_color=False)
                        else:
                            accessibility_tree_path = os.path.join(task_dir, 'accessibility_tree_fail{}'.format(it))
                            ac_tree, obs_info = get_webarena_accessibility_tree(driver_task, accessibility_tree_path)
                    except Exception as e:
                        logging.error('Driver error when adding bounding boxes for failure screenshot.')
                        logging.error(e)
                
                    curr_msg = {
                        'role': 'user',
                        'content': fail_obs
                    }
                    logging.info(f"Fail obs: {fail_obs}")
                    img_path = os.path.join(task_dir, 'screenshot_fail{}.png'.format(it))
                    driver_task.save_screenshot(img_path)
                    messages.append(curr_msg)

                # TODO Better format this
                # Clip messages, too many attached images may cause confusion
                if not args.text_only:
                    messages = clip_message_and_obs(messages, args.max_attached_imgs)
                else:
                    messages = clip_message_and_obs_text_only(messages, args.max_attached_imgs)

                # Call the appropriate API based on model type
                prompt_tokens, completion_tokens, api_call_error, api_response = api_call(args, client, messages)

                if api_call_error:
                    logging.error(f"API call error for {model_type}: {api_call_error}")
                    logging.error(f"API response: {api_response}")
                    break
                else:
                    accumulate_prompt_token += prompt_tokens
                    accumulate_completion_token += completion_tokens
                    logging.info(f'Accumulate Prompt Tokens: {accumulate_prompt_token}; Accumulate Completion Tokens: {accumulate_completion_token}')
                    logging.info('API call complete...')
            
                # Extract response content based on model type
                if model_type == 'gpt':
                    model_response = api_response.choices[0].message.content
                elif model_type == 'claude':
                    # Claude response format: response.content is a list of content blocks
                    model_response = api_response.content[0].text
                elif model_type == 'gemini':
                    if args.run_with_openrouter:
                        # OpenRouter returns an OpenAI-compatible chat-completions response
                        model_response = api_response.choices[0].message.content
                    else:
                        # Gemini response format: response.text
                        model_response = api_response.text
                else:
                    raise ValueError(f"Unsupported model type: {model_type}")
            
                messages.append({'role': 'assistant', 'content': model_response})


                # remove the rects on the website
                # if (not args.text_only) and rects:
                #     logging.info(f"Num of interactive elements: {len(rects)}")
                #     for rect_ele in rects:
                #         driver_task.execute_script("arguments[0].remove()", rect_ele)
                #     rects = []
                    # driver_task.save_screenshot(os.path.join(task_dir, 'screenshot{}_no_box.png'.format(it)))


                # extract action info
                try:
                    assert 'Thought:' in model_response and 'Action:' in model_response
                except (AssertionError,TypeError) as e:
                    logging.error(e)
                    fail_obs = "Format ERROR: Both 'Thought' and 'Action' should be included in your reply."
                    continue

                bot_thought = re.split(pattern, model_response)[1].strip()
                chosen_action = re.split(pattern, model_response)[2].strip()
                # print(chosen_action)
                action_key, info = extract_information(chosen_action)
            
                # Store thought with iteration info
                thoughts_list.append({
                    'iteration': it,
                    'thought': bot_thought,
                    'action': chosen_action
                })

                fail_obs = ""
                pdf_obs = ""
                warn_obs = ""
            
                # Let's ensure that the wait and scroll actions are not counted
                is_wait_or_scroll_action = action_key in ['wait', 'scroll', 'scroll_to_end', 'scroll_within_popup']
            
                # execute action
                try:
                    # Check if browser window is still available before executing action
                    try:
                        window_handle_task = driver_task.current_window_handle
                        driver_task.switch_to.window(window_handle_task)
                    except Exception as window_error:
                        if "no such window" in str(window_error) or "target window already closed" in str(window_error):
                            logging.error('Browser window closed during action execution.')
                            fail_obs = "Browser window was closed unexpectedly. Task cannot continue."
                            break
                        else:
                            raise window_error
                    
                    find_element_js = """
                        let el = document.elementFromPoint(arguments[0], arguments[1]);
                        if (!el) return null;

                        // Helper to check if an element is 'naturally' clickable
                        const isInteractive = (node) => {
                            const tag = node.tagName.toLowerCase();
                            const role = node.getAttribute('role');
                            return ['button', 'a', 'input', 'select', 'textarea'].includes(tag) || 
                                ['button', 'link', 'checkbox', 'menuitem'].includes(role) ||
                                window.getComputedStyle(node).cursor === 'pointer';
                        };

                        // Climb up the DOM tree to find the interactive parent if the top-most isn't interactive
                        let interactiveEl = el;
                        while (interactiveEl && !isInteractive(interactiveEl) && interactiveEl !== document.body) {
                            interactiveEl = interactiveEl.parentElement;
                        }

                        return interactiveEl || el; // Return the interactive one, or fallback to the original
                    """
                    if action_key == 'click':
                        if not args.text_only:
                            click_ele_number = int(info[0])
                            web_ele = web_eles[click_ele_number]
                        else:
                            click_ele_number = info[0]
                            element_box = obs_info[click_ele_number]['union_bound']
                            element_box_center = (element_box[0] + element_box[2] // 2,
                                                  element_box[1] + element_box[3] // 2)
                            web_ele = driver_task.execute_script(find_element_js, element_box_center[0], element_box_center[1])

                        ele_tag_name = web_ele.tag_name.lower()
                        ele_type = web_ele.get_attribute("type")
                    
                        # Check for potentially dangerous elements that might close the window
                        ele_text = web_ele.text.lower() if web_ele.text else ""
                        ele_class = web_ele.get_attribute("class") or ""
                        ele_aria = (web_ele.get_attribute("aria-label") or "").lower()
                        ele_name = (web_ele.get_attribute("name") or "").lower()

                        dangerous_patterns = ['close', 'exit', 'quit', 'logout', 'sign out', 'delete', 'remove']
                        

                        is_dangerous = any(pattern in text for text in [ele_text, ele_aria, ele_name, ele_class.lower()] 
                                        for pattern in dangerous_patterns)

                        if is_dangerous:
                            logging.warning(f'Potentially destructive action: "{ele_text or ele_aria}"')

                        # Store handles before click to detect new tabs
                        handles_before_click = driver_task.window_handles.copy()

                        
                    
                        exec_action_click(info, web_ele, driver_task, screenshot=img_path)
                    
                        # Check if a new tab was opened and switch to it
                        handles_after_click = driver_task.window_handles
                        if len(handles_after_click) > len(handles_before_click):
                            # New tab opened, switch to it and update tab tracking
                            new_handle = [h for h in handles_after_click if h not in handles_before_click][0]
                            driver_task.switch_to.window(new_handle)
                            logging.info(f"New tab opened and switched to: {new_handle}")
                        
                            # Update the global tab tracker with new tab info
                            new_tab_info = get_tabs_info(driver_task)
                            all_tabs_info.update(new_tab_info)


                        try:
                            if (not args.text_only) and rects:
                                logging.info(f"Num of interactive elements: {len(rects)}")
                                for rect_ele in rects:
                                    safe_remove_element(driver_task, rect_ele)
                                rects = []
                        except:
                            pass

                        
                    
                        # Verify window is still available after click
                        try:
                            driver_task.current_window_handle
                        except:
                            logging.error('Browser window was closed after clicking element.')
                            fail_obs = "Browser window was closed after action. Task cannot continue."
                            break

                        # deal with PDF file
                        current_files = sorted(os.listdir(args.download_dir))
                        if current_files != download_files:
                            # wait for download finish
                            time.sleep(10)
                            current_files = sorted(os.listdir(args.download_dir))

                            current_download_file = [pdf_file for pdf_file in current_files if pdf_file not in download_files and pdf_file.endswith('.pdf')]
                            if current_download_file:
                                pdf_file = current_download_file[0]
                                pdf_obs = get_pdf_retrieval_ans_from_assistant(client, os.path.join(args.download_dir, pdf_file), task['ques'])
                                shutil.copy(os.path.join(args.download_dir, pdf_file), task_dir)
                                pdf_obs = "You downloaded a PDF file, I ask the Assistant API to answer the task based on the PDF file and get the following response: " + pdf_obs
                            download_files = current_files

                        if ele_tag_name == 'button' and ele_type == 'submit':
                            time.sleep(3)

                    elif action_key == 'wait':
                        time.sleep(5)
                        if (not args.text_only) and rects:
                            logging.info(f"Num of interactive elements: {len(rects)}")
                            for rect_ele in rects:
                                safe_remove_element(driver_task, rect_ele)
                            rects = []

                    elif action_key == 'hover':
                        if not args.text_only:
                            hover_ele_number = int(info[0])
                            web_ele = web_eles[hover_ele_number]
                        else:
                            hover_ele_number = info[0]
                            element_box = obs_info[hover_ele_number]['union_bound']
                            element_box_center = (element_box[0] + element_box[2] // 2,
                                                  element_box[1] + element_box[3] // 2)
                            web_ele = driver_task.execute_script(find_element_js, element_box_center[0], element_box_center[1])
                        
                        exec_action_hover(info, web_ele, driver_task, screenshot=img_path)

                        try:
                            if (not args.text_only) and rects:
                                logging.info(f"Num of interactive elements: {len(rects)}")
                                for rect_ele in rects:
                                    safe_remove_element(driver_task, rect_ele)
                                rects = []
                        except:
                            pass

                    elif action_key == 'type':
                        if not args.text_only:
                            type_ele_number = int(info['number'])
                            web_ele = web_eles[type_ele_number]
                        else:
                            type_ele_number = info['number']
                            element_box = obs_info[type_ele_number]['union_bound']
                            element_box_center = (element_box[0] + element_box[2] // 2,
                                                  element_box[1] + element_box[3] // 2)
                            web_ele = driver_task.execute_script("return document.elementFromPoint(arguments[0], arguments[1]);", element_box_center[0], element_box_center[1])
                        
                        
                        warn_obs = exec_action_type(info, web_ele, driver_task, captcha_setup=captcha_setup)

                        try:
                            if (not args.text_only) and rects:
                                logging.info(f"Num of interactive elements: {len(rects)}")
                                for rect_ele in rects:
                                    safe_remove_element(driver_task, rect_ele)
                                rects = []

                        except:
                            pass
                        

                        # if 'wolfram' in task['web']:
                        #     time.sleep(5)

                    elif action_key == 'scroll':
                        if (not args.text_only) and rects:
                            logging.info(f"Num of interactive elements: {len(rects)}")
                            for rect_ele in rects:
                                safe_remove_element(driver_task, rect_ele)
                            rects = []
                        if not args.text_only:
                            exec_action_scroll(info, web_eles, driver_task, args, None)
                        else:
                            exec_action_scroll(info, None, driver_task, args, obs_info)

                    elif action_key == 'scroll_to_end':
                        if (not args.text_only) and rects:
                            logging.info(f"Num of interactive elements: {len(rects)}")
                            for rect_ele in rects:
                                safe_remove_element(driver_task, rect_ele)
                            rects = []
                        exec_action_scroll_to_end(driver_task)

                    elif action_key == 'scroll_within_popup':
                        if (not args.text_only) and rects:
                            logging.info(f"Num of interactive elements: {len(rects)}")
                            for rect_ele in rects:
                                safe_remove_element(driver_task, rect_ele)
                            rects = []
                        exec_action_scroll_within_popup(info, driver_task, args)

                    elif action_key == 'switch_tab':
                        target_url = info['content']
                        if switch_to_tab_by_url(driver_task, target_url):
                            logging.info(f"Successfully switched to tab: {target_url}")
                            # Update current tab status in all_tabs_info
                            current_handle = driver_task.current_window_handle
                            for handle in all_tabs_info:
                                all_tabs_info[handle]['is_current'] = (handle == current_handle)
                            time.sleep(2)
                        else:
                            fail_obs = f"Could not find a tab with URL: {target_url}. Available tabs are shown in the observation."

                    elif action_key == 'goback':
                        if (not args.text_only) and rects:
                            logging.info(f"Num of interactive elements: {len(rects)}")
                            for rect_ele in rects:
                                safe_remove_element(driver_task, rect_ele)
                            rects = []
                        driver_task.back()
                        time.sleep(2)

                    elif action_key == 'google':
                        if (not args.text_only) and rects:
                            logging.info(f"Num of interactive elements: {len(rects)}")
                            logging.info(f"Model {args.api_model} googled to solve the task")
                            for rect_ele in rects:
                                safe_remove_element(driver_task, rect_ele)
                            rects = []
                        driver_task.get('https://www.google.com/') #This replaces the current page with the google page
                        time.sleep(2)

                    elif action_key == 'answer':
                        logging.info(info['content'])
                        logging.info('finish!!')
                        break

                    else:
                        raise NotImplementedError
                    fail_obs = ""
                except Exception as e:
                    error_msg = str(e)
                    logging.error('driver error info:')
                    logging.error(e)
                
                    if "no such window" in error_msg or "target window already closed" in error_msg:
                        logging.error('Browser window was closed during action execution.')
                        fail_obs = "Browser window was closed unexpectedly during action. Task cannot continue."
                        break
                    elif "session deleted" in error_msg or "disconnected" in error_msg:
                        logging.error('Browser session was terminated.')
                        fail_obs = "Browser session lost. Task cannot continue."
                        break
                    elif 'element click intercepted' not in error_msg:
                        fail_obs = "The action you have chosen cannot be executed. Please double-check if you have selected the wrong Numerical Label or Action or Action format. Then provide the revised Thought and Action."
                    else:
                        fail_obs = ""
                    time.sleep(2)
            
                #Decrement iteration counter for wait/scroll actions (regardless of success/failure)
                if is_wait_or_scroll_action:
                    it -= 1
                    logging.info(f"Action was wait/scroll - iteration counter decremented to {it}")

            print_message(messages, task_dir)
        
            # Save thoughts to JSON file
            thoughts_file_path = os.path.join(task_dir, 'thoughts.json')
            with open(thoughts_file_path, 'w') as f:
                json.dump(thoughts_list, f, indent=2)
            logging.info(f'Thoughts saved to {thoughts_file_path}')
        
            # Don't quit driver here - reuse for next task with same web_name
            logging.info(f'Task completed. Driver kept alive for potential reuse.')
            logging.info(f'Total cost: {accumulate_prompt_token / 1000 * 0.01 + accumulate_completion_token / 1000 * 0.03}')
        
            # Save checkpoint after completing this task
            completed_task_ids.add(task['id'])
            save_checkpoint(result_dir, completed_task_ids)

        finally:
            # Cleanup driver and profile for this task
            logging.info(f"Cleaning up driver and profile for task {task['id']}")
            # If requested, mirror this task's outputs (and checkpoint) to S3
            try:
                if 'use_s3' in locals() and use_s3:
                    task_dir_s3_prefix = os.path.join(result_dir, f"task{task['id']}").replace("\\", "/")
                    upload_directory_to_s3(task_dir, AWS_S3_BUCKET, task_dir_s3_prefix)
                    # Upload checkpoint file if it exists
                    checkpoint_path = os.path.join(result_dir, '.checkpoint.json')
                    if os.path.exists(checkpoint_path):
                        upload_file_to_s3(
                            checkpoint_path,
                            AWS_S3_BUCKET,
                            os.path.join(result_dir, '.checkpoint.json').replace("\\", "/"),
                        )
            except Exception as e:
                logging.warning(f"Failed to mirror outputs to S3 for task {task['id']}: {e}")
            try:
                driver_task.quit()
            except Exception as e:
                logging.warning(f"Error quitting driver: {e}")
            cleanup_temp_profile(profile_dir)

    logging.info('All tasks processed.')

if __name__ == '__main__':
    main()
    print('End of process')