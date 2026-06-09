"""state helpers for the WebSP-Eval replay agent (split from run_with_replay.py)."""
import time
import logging
from pathlib import Path

from utils import check_cloudflare
from state_reset.extension_reset import replay_events, load_json_file
from state_reset import (
    hf_make_repo_public,
    remove_gated_access,
    remove_dataset_licenses,
    remove_dataset,
    git_make_repo_public,
    remove_repo_license,
    reset_history,
    reset_cookies,
    hf_random_access_token_number,
)


def execute_state_reset(state_reset_ops, driver_task=None, task=None):
    """
    Execute state reset operations based on type specified in state_reset_ops.
    
    Args:
        state_reset_ops: Dictionary with 'type' and 'function_calls' fields, or None
        driver_task: Selenium WebDriver instance (required for extension type)
        task: Task dictionary (for context/logging)
    
    Returns:
        True if reset was executed successfully, False otherwise
    """
    if not state_reset_ops:
        return False
    
    reset_type = state_reset_ops.get('type')
    if not reset_type or reset_type == 'NONE':
        return False
    
    function_calls = state_reset_ops.get('function_calls', [])
    if not isinstance(function_calls, list):
        logging.warning(f"Invalid function_calls format for task {task.get('id', 'unknown') if task else 'unknown'}")
        return False
    
    task_id = task.get('id', 'unknown') if task else 'unknown'
    
    # Map function name strings to actual functions for API type
    api_function_map = {
        'hf_make_repo_public': hf_make_repo_public,
        'remove_gated_access': remove_gated_access,
        'remove_dataset_licenses': remove_dataset_licenses,
        'remove_dataset': remove_dataset,
        'git_make_repo_public': git_make_repo_public,
        'remove_repo_license': remove_repo_license,
        'reset_cookies': reset_cookies,
        'hf_access_token': hf_random_access_token_number,
    }
    
    try:
        if reset_type == 'extension':
            if not driver_task:
                logging.error(f"Driver required for extension reset (task {task_id})")
                return False
            
            # Check if we have function_calls (new multi-file approach)
            if function_calls and len(function_calls) > 0:
                logging.info(f"Processing {len(function_calls)} replay function call(s) for task {task_id}")
                
                # Loop through each function_call (each may have its own file and state)
                for func_idx, func_call in enumerate(function_calls):
                    func_name = func_call.get('function')
                    if func_name != 'replay_events':
                        logging.warning(f"Unknown extension function: {func_name} (task {task_id})")
                        continue
                    
                    kwargs = func_call.get('kwargs', {})
                    click_file = kwargs.get('replay_click_file')
                    
                    if not click_file:
                        logging.warning(f"No replay_click_file in function_call {func_idx + 1} (task {task_id})")
                        continue
                    
                    logging.info(f"Processing function call {func_idx + 1}/{len(function_calls)}: {click_file}")
                    
                    # Resolve path
                    replay_path = Path(click_file)
                    if not replay_path.is_absolute():
                        replay_path = Path(__file__).parent.parent / replay_path
                    
                    if not replay_path.exists():
                        logging.warning(f"Replay click file not found: {replay_path}")
                        return False
                    
                    logging.info(f"Loading replay events from: {replay_path}")
                    replay_data = load_json_file(str(replay_path))
                    events = replay_data.get('events', [])
                    
                    if not events:
                        logging.warning(f"No events found in replay file: {replay_path}")
                        return False
                    
                    # Navigate to start URL if present
                    start_url = replay_data.get('startUrl')
                    if start_url:
                        # Validate window before navigation
                        try:
                            # Check if current window is still valid
                            try:
                                driver_task.current_window_handle
                            except Exception as window_error:
                                error_msg = str(window_error)
                                if "no such window" in error_msg or "target window already closed" in error_msg:
                                    logging.warning("Current window is closed. Checking for available windows...")
                                    # Try to switch to any available window
                                    available_handles = driver_task.window_handles
                                    if available_handles:
                                        driver_task.switch_to.window(available_handles[0])
                                        logging.info(f"Switched to available window: {available_handles[0]}")
                                    else:
                                        logging.error("No available windows found. Cannot proceed with state reset.")
                                        return False
                                else:
                                    raise window_error
                            
                            logging.info(f"Navigating to replay start URL: {start_url}")
                            driver_task.get(start_url)
                            if task and task.get('captcha_setup', False):
                                check_cloudflare(driver_task)
                            time.sleep(2)
                            logging.info(f"Navigated successfully to replay start URL: {start_url}")
                        except Exception as nav_error:
                            logging.error(f"Error navigating to replay start URL: {nav_error}")
                            # Try to recover by checking for available windows
                            try:
                                available_handles = driver_task.window_handles
                                if available_handles:
                                    driver_task.switch_to.window(available_handles[0])
                                    logging.info(f"Recovered by switching to window: {available_handles[0]}")
                                    # Retry navigation
                                    driver_task.get(start_url)
                                    if task and task.get('captcha_setup', False):
                                        check_cloudflare(driver_task)
                                    time.sleep(2)
                                    logging.info(f"Successfully navigated to replay start URL after recovery: {start_url}")
                                else:
                                    logging.error("No available windows for recovery. Cannot proceed with state reset.")
                                    return False
                            except Exception as recovery_error:
                                logging.error(f"Failed to recover from navigation error: {recovery_error}")
                                return False
                    
                    # Execute replay for this function call
                    logging.info(f"Executing replay events from function call {func_idx + 1}/{len(function_calls)}")
                    replay_events(
                        driver_task,
                        events,
                        set_checked_state=kwargs.get('set_checked_state', True),
                        skip_disabled_clicks=kwargs.get('skip_disabled_clicks', False),
                        refresh_before_start=kwargs.get('refresh_before_start', True)
                    )
                    logging.info(f"Replay completed for function call {func_idx + 1}/{len(function_calls)}")
                    
                    # Add a small delay between function calls if there are multiple
                    if func_idx < len(function_calls) - 1:
                        logging.info(f"Waiting 2 seconds before processing next function call...")
                        time.sleep(2)
                
                logging.info(f"All extension replay function calls completed for task {task_id}")
                return True
            else:
                logging.warning(f"No function_calls specified for extension reset (task {task_id})")
                return False
        
        elif reset_type == 'api':
            # Execute API functions (no driver needed)
            for func_call in function_calls:
                func_name = func_call.get('function')
                kwargs = func_call.get('kwargs', {})
                
                if func_name not in api_function_map:
                    logging.warning(f"Unknown API function: {func_name} (task {task_id})")
                    continue
                
                try:
                    logging.info(f"Executing API function: {func_name} for task {task_id}")
                    api_function_map[func_name](**kwargs)
                    logging.info(f"API function {func_name} completed for task {task_id}")
                except Exception as e:
                    logging.error(f"Error executing API function {func_name} for task {task_id}: {e}")
                    logging.exception(e)
            
            return True

        elif reset_type == 'hf_access_token':
            # Expect a function_call like:
            # {"function": "hf_random_access_token_number",
            #  "kwargs": {"instruction": "Create a new read-only access token named 'read_token_8761'."}}
            if not function_calls:
                logging.warning(f"hf_access_token reset: no function_calls specified (task {task_id})")
                return False

            func_call = function_calls[0]
            func_name = func_call.get('function')
            kwargs = func_call.get('kwargs', {})

            if func_name != 'hf_random_access_token_number':
                logging.warning(f"hf_access_token reset: unexpected function {func_name} (task {task_id})")
                return False

            # Extract instruction from kwargs
            instruction = kwargs.get('instruction')
            if not instruction:
                logging.warning(f"hf_access_token reset: no 'instruction' in kwargs for task {task_id}")
                return False

            logging.info(f"hf_access_token reset: original instruction for task {task_id}: {instruction}")
            new_ques = hf_random_access_token_number(instruction)
            
            # Also update task['ques'] so the agent sees the new token suffix
            if task is not None and isinstance(task.get('ques'), str):
                task['ques'] = new_ques
            logging.info(f"hf_access_token reset: updated instruction for task {task_id}: {new_ques}")
            return True
        
        elif reset_type == 'history':
            # Execute history reset (uses its own driver)
            for func_call in function_calls:
                func_name = func_call.get('function')
                kwargs = func_call.get('kwargs', {})
                
                if func_name == 'reset_history':
                    try:
                        logging.info(f"Executing history reset (task {task_id})")
                        reset_history(headless=kwargs.get('headless', True))
                        logging.info(f"History reset completed for task {task_id}")
                    except Exception as e:
                        logging.error(f"Error during history reset for task {task_id}: {e}")
                        logging.exception(e)
                else:
                    logging.warning(f"Unknown history function: {func_name} (task {task_id})")
            
            return True
        
        elif reset_type == 'cookies':
            if not driver_task:
                logging.error(f"Driver required for cookies reset (task {task_id})")
                return False
            
            # Execute cookies reset for each function call
            for func_call in function_calls:
                func_name = func_call.get('function')
                kwargs = func_call.get('kwargs', {})
                
                if func_name == 'reset_cookies':
                    website_url = kwargs.get('website_url')
                    if not website_url:
                        logging.warning(f"website_url required for cookies reset (task {task_id})")
                        continue
                    
                    try:
                        logging.info(f"Resetting cookies for {website_url} (task {task_id})")
                        reset_cookies(website_url=website_url, driver=driver_task)
                        logging.info(f"Cookies reset completed for task {task_id}")
                    except Exception as e:
                        logging.error(f"Error during cookies reset for task {task_id}: {e}")
                        logging.exception(e)
                else:
                    logging.warning(f"Unknown cookies function: {func_name} (task {task_id})")
            
            return True
        
        else:
            logging.warning(f"Unknown state reset type: {reset_type} (task {task_id})")
            return False
    
    except Exception as e:
        logging.error(f"Error during state reset for task {task_id}: {e}")
        logging.exception(e)
        return False
