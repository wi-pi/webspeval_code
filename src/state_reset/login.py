import logging
import time
from pathlib import Path
from .extension_reset import replay_events, load_json_file

def execute_login(driver_task, task, web_url=None):
    """
    Execute login replay for a task if login_click_file is specified.
    
    Args:
        driver_task: Selenium WebDriver instance
        task: Task dictionary with optional 'login_click_file' field (absolute path or None)
        web_url: Optional website URL to navigate/refresh after login to persist session
    
    Returns:
        True if login was executed successfully, False otherwise
    """
    login_click_file = task.get('login_click_file')
    
    if not login_click_file:
        return False
    
    # Resolve path (handle both absolute and relative paths)
    login_path = Path(login_click_file)
    if not login_path.is_absolute():
        # If relative, resolve relative to the repository root
        login_path = Path(__file__).parent.parent.parent / login_path
    
    if not login_path.exists():
        logging.warning(f"Login click file not found: {login_path}")
        return False
    
    try:
        logging.info(f"Loading login events from: {login_path}")
        
        # Load login events from JSON file
        login_data = load_json_file(str(login_path))
        events = login_data.get('events', [])
        
        if not events:
            logging.warning(f"No events found in login file: {login_path}")
            return False
        
        # Navigate to start URL if present
        start_url = login_data.get('startUrl')
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
                            logging.error("No available windows found. Cannot proceed with login.")
                            return False
                    else:
                        raise window_error
                
                logging.info(f"Navigating to login start URL: {start_url}")
                driver_task.get(start_url)
                time.sleep(2)
            except Exception as nav_error:
                logging.error(f"Error navigating to login start URL: {nav_error}")
                # Try to recover by checking for available windows
                try:
                    available_handles = driver_task.window_handles
                    if available_handles:
                        driver_task.switch_to.window(available_handles[0])
                        logging.info(f"Recovered by switching to window: {available_handles[0]}")
                        # Retry navigation
                        driver_task.get(start_url)
                        time.sleep(2)
                        logging.info(f"Successfully navigated to login start URL after recovery: {start_url}")
                    else:
                        logging.error("No available windows for recovery. Cannot proceed with login.")
                        return False
                except Exception as recovery_error:
                    logging.error(f"Failed to recover from navigation error: {recovery_error}")
                    return False
        
        # Replay login events
        replay_events(
            driver_task,
            events,
            set_checked_state=True,
            skip_disabled_clicks=False,
            refresh_before_start=True
        )
        
        logging.info(f"Login replay completed for task {task.get('id', 'unknown')}")

        # Navigate to the task website in a new tab and refresh to persist login state
        target_url = web_url or task.get('web')
        if target_url:
            try:
                logging.info(f"Opening task URL in a new tab after login to persist session: {target_url}")
                original_handle = driver_task.current_window_handle
                driver_task.execute_script("window.open(arguments[0], '_blank');", target_url)
                time.sleep(1)
                handles = driver_task.window_handles
                if len(handles) > 1:
                    driver_task.switch_to.window(handles[-1])
                else:
                    driver_task.get(target_url)
                time.sleep(2)
                driver_task.refresh()
                time.sleep(2)
                logging.info("Post-login new-tab navigation and refresh completed")
                # Optional cleanup: close the new tab and return to original
                try:
                    if len(handles) > 1:
                        driver_task.close()
                        driver_task.switch_to.window(original_handle)
                except Exception:
                    pass

            except Exception as e: 
                logging.error(f"Error during post-login navigation and refresh: {e}")
                logging.exception(e)


        return True
        
    except Exception as e:
        logging.error(f"Error during login replay for task {task.get('id', 'unknown')}: {e}")
        logging.exception(e)
        return False