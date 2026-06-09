"""driver helpers for the WebSP-Eval replay agent (split from run_with_replay.py)."""
import os
import time
import shutil
import logging
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import undetected_chromedriver as uc
from selenium_stealth import stealth


def create_driver_options_uc(args, use_extension=False):
    """Create Chrome options with all necessary configurations.

    Args:
        args: Command line arguments
        profile_dir: Path to Chrome profile directory
        use_extension: Whether to load the UsersFirst extension (default: False)
    """
    options = Options()

    options.add_argument("--window-size=1280,1024")

    if args.tor:
        options.add_argument('--proxy-server=socks5://127.0.0.1:9050')

    # ext_dir = None
    # if not use_extension:
    #     options.add_argument('--disable-extensions')
    # else:
    #     ext_dir = Path(__file__).parent / 'UsersFirst-annotation_v3'
    #     options.add_argument(f'--load-extension={ext_dir}')



    options.add_experimental_option('prefs', {
        "extensions.ui.developer_mode": True,
        'profile.default_content_setting_values.notifications': 5,  # Changed from 2 to 5 (v4 value)
        'credentials_enable_service': True,
        'profile.password_manager_enabled': True,
        "download.default_directory": args.download_dir,
        "plugins.always_open_pdf_externally": True,
        "download.prompt_for_download": False,  # From v4
        "download.directory_upgrade": True,  # From v4
        # "safebrowsing.enabled": True  # From v4
    })

    # options.add_argument(f'--user-data-dir={profile_dir}')
    # options.add_argument("--disable-gpu")
    options.add_argument("--force-device-scale-factor=1")  # Force non-HiDPI rendering

    ## Force light mode in the browser (for the models to understand the elements)
    ##If not specified, the browser will use the existing theme (light or dark)
    if args.force_light_mode:
        options.add_argument("--force-dark-mode=0")
        options.add_argument("--disable-features=DarkMode")

    if args.save_accessibility_tree:
        args.force_device_scale = True

    if args.force_device_scale:
        options.add_argument("--force-device-scale-factor=1")
    if args.headless:
        options.add_argument("--headless=new")

    return options


def create_driver_options(args, profile_dir, use_extension=False):
    """Create Chrome options with all necessary configurations.

    Args:
        args: Command line arguments
        profile_dir: Path to Chrome profile directory
        use_extension: Whether to load the UsersFirst extension (default: False)
    """
    options = Options()

    # Enable BiDi and WebExtensions (from v4)
    options.enable_bidi = True
    options.enable_webextensions = True

    # options.add_argument("--window-size=1280,1024")

    # Anti-detection configurations
    options.add_experimental_option("excludeSwitches", ['enable-automation', 'enable-logging'])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument('--disable-blink-features=AutomationControlled')

    # Additional stealth arguments
    options.add_argument('--disable-infobars')
    # options.add_argument('--start-maximized')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-application-cache')
    options.add_argument('--disable-setuid-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-features=DisableLoadExtensionCommandLineSwitch') 

    # Extension handling
    ext_dir = None
    if not use_extension:
        options.add_argument('--disable-extensions')
    else:
        ext_dir = Path(__file__).parent / 'UsersFirst-annotation_v3'
        options.add_argument(f'--load-extension={ext_dir}')

    options.add_experimental_option('prefs', {
        "extensions.ui.developer_mode": True,
        'profile.default_content_setting_values.notifications': 5,  
        'credentials_enable_service': True,
        'profile.password_manager_enabled': True,
        "download.default_directory": args.download_dir,
        "plugins.always_open_pdf_externally": True,
        "download.prompt_for_download": False,  
        "download.directory_upgrade": True,  
        "safebrowsing.enabled": True  
    })

    options.add_argument(f'--user-data-dir={profile_dir}')
    options.add_argument("--disable-gpu")
    options.add_argument("--force-device-scale-factor=1")  # Force non-HiDPI rendering

    ## Force light mode in the browser (for the models to understand the elements)
    ##If not specified, the browser will use the existing theme (light or dark)
    if args.force_light_mode:
        options.add_argument("--force-dark-mode=0")
        options.add_argument("--disable-features=DarkMode")

    if args.save_accessibility_tree:
        args.force_device_scale = True

    if args.force_device_scale:
        options.add_argument("--force-device-scale-factor=1")
    if args.headless:
        options.add_argument("--headless=new")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
    else:
        # Set realistic user agent for non-headless mode too
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )

    return options


def cleanup_temp_profile(profile_dir):
    """Clean up temporary profile directory."""
    try:
        if profile_dir and os.path.exists(profile_dir):
            shutil.rmtree(profile_dir)
            logging.info(f"Cleaned up profile directory: {profile_dir}")
    except Exception as e:
        logging.warning(f"Could not clean up profile directory {profile_dir}: {e}")


def create_fresh_profile(args, captcha_setup=False):
    """Create a fresh temporary profile directory for a task."""
    from pathlib import Path

    PARENT_DIR = Path(__file__).parent
    
    if captcha_setup:
        master_profile_dir = PARENT_DIR / "test_profile_captcha"
    elif not args.test_profile_dir_name:
        master_profile_dir = PARENT_DIR / "test_profile"
    else: #Use an existing profile directory (passed in as an argument)
        master_profile_dir = PARENT_DIR / args.test_profile_dir_name

    # Create a unique temp profile directory
    profile_dir = PARENT_DIR / f"temp_profile_{time.time()}"

    # Copy master profile to new temp directory
    try:
        shutil.copytree(str(master_profile_dir), str(profile_dir))
        logging.info(f"Created fresh profile directory: {profile_dir}")
    except Exception as e:
        logging.error(f"Failed to create profile directory: {e}")
        raise

    print(f"Using profile directory: {profile_dir}")

    return profile_dir


def get_stealth_js():
    """Return stealth JavaScript to mask automation."""
    return """
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        
        // Override Chrome runtime
        window.chrome = {
            runtime: {}
        };
        
        // Override permissions
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
        
        // Override plugins and mimeTypes
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });
        
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en']
        });
    """


def initialize_driver_for_taskid(args, task_id, profile_dir=None, use_extension=False, captcha_setup=False):
    """Initialize a fresh driver instance for a specific task_id.

    Args:
        args: Command line arguments
        task_id: ID of the task being processed
        profile_dir: Path to Chrome profile directory (creates new if None)
        use_extension: Whether to load the UsersFirst extension (default: False)
    """
    # Create fresh profile
    if profile_dir is None:
        profile_dir = create_fresh_profile(args, captcha_setup=captcha_setup)

    # Create driver options
    options = None
    if captcha_setup:
        try:
            options = create_driver_options_uc(args, use_extension=use_extension)
        except Exception as e:
            logging.error(f'Error creating driver options: {e}')
            options = create_driver_options(args, profile_dir, use_extension=use_extension)
    else:
        options = create_driver_options(args, profile_dir, use_extension=use_extension)

    # Initialize stealth JavaScript
    stealth_js = get_stealth_js()

    try:
        # Create driver with profile
        if captcha_setup:
            try:
                driver = uc.Chrome(user_data_dir=profile_dir,options=options,version_main=144)
                stealth(driver,
                        languages=["en-US", "en"],
                        vendor="Google Inc.",
                        platform="Win32",
                        webgl_vendor="Intel Inc.",
                        renderer="Intel Iris OpenGL Engine",
                        # fix_hairline=True,   # only for headless
                        )
                logging.info("✓ Using undetected_chromedriver with stealth for captcha/Cloudflare handling")
                print("✓ Using undetected_chromedriver with stealth for captcha/Cloudflare handling")
            except Exception as e:
                logging.warning(f"⚠ Error with uc.Chrome, falling back to regular Chrome: {e}")
                print(f"⚠ Error with uc.Chrome, falling back to regular Chrome: {e}")
                service = Service(executable_path=ChromeDriverManager().install())
                driver = webdriver.Chrome(options=options, service=service)
                logging.info("✓ Using regular Selenium Chrome driver")
                print("✓ Using regular Selenium Chrome driver")
        else:
            service = Service(executable_path=ChromeDriverManager().install())
            driver = webdriver.Chrome(options=options, service=service)
            logging.info("✓ Using regular Selenium Chrome driver")
            print("✓ Using regular Selenium Chrome driver")
        
        # Set page load timeout to 60 seconds
        driver.set_page_load_timeout(60)
        # Set script timeout to 120 seconds to handle long-running scroll scripts
        driver.set_script_timeout(120)

        # if use_extension: #no need for this we are loading it in the base test profile
        #     ext_dir = Path(__file__).parent / 'UsersFirst-annotation_v3'
        #     _ = driver.webextension.install(path=str(ext_dir))
        #     print("Extension loaded successfully")
        
        # Apply stealth JavaScript
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': stealth_js})
        
        # Set window size
        driver.set_window_size(args.window_width, args.window_height)
        
        logging.info(f"Successfully initialized driver for task_id: {task_id}")
        
    except Exception as e:
        logging.error(f'Failed to start Chrome with profile: {e}')
        logging.info('Trying to start Chrome without profile...')
        
        # Clean up failed profile
        cleanup_temp_profile(profile_dir)
        
        # Fallback: try without profile
        fallback_options = Options()
        fallback_options.add_argument("--no-sandbox")
        fallback_options.add_argument("--disable-dev-shm-usage")
        fallback_options.add_argument('--disable-blink-features=AutomationControlled')
        fallback_options.add_experimental_option("excludeSwitches", ['enable-automation', 'enable-logging'])
        fallback_options.add_experimental_option('useAutomationExtension', False)
        fallback_options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        fallback_options.add_experimental_option(
            "prefs", {
                "download.default_directory": args.download_dir,
                "plugins.always_open_pdf_externally": True,
                'profile.default_content_setting_values.notifications': 2,
                'credentials_enable_service': False,
                'profile.password_manager_enabled': False
            }
        )
        
        driver = webdriver.Chrome(options=fallback_options)
        
        # Set script timeout to 120 seconds to handle long-running scroll scripts
        driver.set_script_timeout(120)
        
        if use_extension:
            ext_dir = Path(__file__).parent / 'UsersFirst-annotation_v3'
            _ = driver.webextension.install(path=str(ext_dir))
            print("Extension loaded successfully")
        
        # Execute stealth JavaScript for fallback driver
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': stealth_js})
        
        driver.set_window_size(args.window_width, args.window_height)
        
        profile_dir = None  # No profile in fallback mode
        
    return driver, profile_dir
