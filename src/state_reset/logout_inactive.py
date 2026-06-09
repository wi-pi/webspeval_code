#TODO Create a function to support the logout inactive tasks.

import os
import shutil
import time
import logging
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from .login import execute_login


def logout_inactive(task):
    """
    Create 5 logged-in sessions by replaying login events in separate temporary profiles.
    
    Args:
        task: Task dictionary with 'login_click_file' field
        
    Returns:
        List of profile directory paths (one for each logged-in session)
    """
    PARENT_DIR = Path(__file__).parent.parent
    master_profile_dir = PARENT_DIR / "test_profile"
    
    if not master_profile_dir.exists():
        logging.error(f"Master profile directory not found: {master_profile_dir}")
        raise FileNotFoundError(f"Master profile directory not found: {master_profile_dir}")
    
    session_paths = []
    num_sessions = 5
    
    # Check if login_click_file is specified
    login_click_file = task.get('login_click_file')
    if not login_click_file:
        logging.warning("No login_click_file specified in task. Cannot create logged-in sessions.")
        return []
    
    # Check if extension is needed for login
    use_extension = task.get('login_with_extension', False)
    
    # Use a base timestamp for all sessions in this call to ensure uniqueness
    base_timestamp = int(time.time() * 1000)  # Use milliseconds for better precision
    
    for session_num in range(1, num_sessions + 1):
        logging.info(f"Creating logged-in session {session_num}/{num_sessions}")
        
        # Create a unique temporary profile directory
        profile_dir = PARENT_DIR / f"temp_profile_logout_inactive_{base_timestamp}_{session_num}"
        
        try:
            # Copy master profile to new temp directory
            shutil.copytree(master_profile_dir, profile_dir)
            logging.info(f"Created temporary profile directory: {profile_dir}")
            
            # Create Chrome options
            options = Options()
            
            # Enable BiDi and WebExtensions for extension support
            options.enable_bidi = True
            options.enable_webextensions = True
            
            options.add_argument("--window-size=1280,1024")
            options.add_experimental_option("excludeSwitches", ['enable-automation', 'enable-logging'])
            options.add_experimental_option('useAutomationExtension', False)
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument('--disable-infobars')
            options.add_argument('--start-maximized')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-application-cache')
            options.add_argument('--disable-setuid-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-features=DisableLoadExtensionCommandLineSwitch')
            options.add_argument(f'--user-data-dir={profile_dir}')
            options.add_argument("--disable-gpu")
            options.add_argument("--force-device-scale-factor=1")
            options.add_argument(
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )
            
            # Extension handling
            if not use_extension:
                options.add_argument('--disable-extensions')
            else:
                ext_dir = PARENT_DIR / 'UsersFirst-annotation_v3'
                if ext_dir.exists():
                    options.add_argument(f'--load-extension={ext_dir}')
            
            options.add_experimental_option('prefs', {
                'profile.default_content_setting_values.notifications': 5,
                'credentials_enable_service': True,
                'profile.password_manager_enabled': True,
            })
            
            # Create driver
            service = Service(executable_path=ChromeDriverManager().install())
            driver = webdriver.Chrome(options=options, service=service)
            
            #Commented this as these lines are redundant and we are loading with the options 
            # if use_extension:
            #     ext_dir = PARENT_DIR / 'UsersFirst-annotation_v3'
            #     if ext_dir.exists():
            #         _ = driver.webextension.install(path=str(ext_dir))
            #         logging.info("Extension loaded successfully")
            
            # Apply stealth JavaScript
            stealth_js = """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                window.chrome = {
                    runtime: {}
                };
            """
            driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': stealth_js})
            driver.set_window_size(1280, 1024)
            
            # Execute login using the replay events
            logging.info(f"Executing login for session {session_num}")
            execute_login(driver, task, web_url=task.get('web'))
            
            # Wait a bit to ensure login state is saved
            time.sleep(3)
            
            # Close the browser (profile will persist with login state)
            driver.quit()
            logging.info(f"Browser closed for session {session_num}. Profile saved at: {profile_dir}")
            
            # Add profile path to list
            session_paths.append(str(profile_dir))
            
            # Small delay between sessions
            time.sleep(1)
            
        except Exception as e:
            logging.error(f"Error creating session {session_num}: {e}")
            # Clean up failed profile
            if profile_dir.exists():
                try:
                    shutil.rmtree(profile_dir)
                except:
                    pass
            # Continue with next session
            continue
    
    logging.info(f"Created {len(session_paths)} logged-in sessions")
    return session_paths
    