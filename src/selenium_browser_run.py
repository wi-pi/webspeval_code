from pathlib import Path
import argparse
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

import shutil
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

import undetected_chromedriver as uc
from selenium_stealth import stealth
from utils import check_cloudflare

parser = argparse.ArgumentParser()
parser.add_argument("--test_profile_dir_name", type=str, default="test_profile")
parser.add_argument("--use_extension", action='store_true')
parser.add_argument("--default_download_dir", type=str, default=None, 
help="Default download directory for the browser. Use this if you want to save the files during the clicks to a specific directory.")
parser.add_argument("--google_signin", action='store_true')
parser.add_argument("--captcha_mode", action='store_true')
args = parser.parse_args()

PARENT_DIR = Path(__file__).parent
test_profile_dir_name = args.test_profile_dir_name
print(f"Using test profile directory: {test_profile_dir_name}")

# Set default download directory (cross-platform)
if args.default_download_dir is None:
    default_download_dir = str(Path(os.getcwd()) / "Downloads")
else:
    default_download_dir = os.path.expanduser(args.default_download_dir)
    default_download_dir = str(Path(default_download_dir).resolve())

print(f"Using download directory: {default_download_dir}")


def create_driver_options_uc(use_extension=False, default_download_dir=None, viewport_width=1280, viewport_height=1024):
    """Create Chrome options for undetected_chromedriver."""
    options = Options()
    options.add_argument(f"--window-size={viewport_width},{viewport_height}")
    # options.add_argument('--proxy-server=socks5://127.0.0.1:9050')
    options.add_argument("--force-device-scale-factor=1")
    
    # Add extension loading if needed (uc.Chrome doesn't support webextension.install())
    ext_dir = None
    if use_extension:
        ext_dir = Path(__file__).parent.parent / 'extension'
        options.add_argument(f'--load-extension={ext_dir}')
    
    prefs = {
        "extensions.ui.developer_mode": True,
        'profile.default_content_setting_values.notifications': 5,
        'credentials_enable_service': True,
        'profile.password_manager_enabled': True,
        "plugins.always_open_pdf_externally": True,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
    }
    
    # Only add download directory if provided
    if default_download_dir:
        prefs["download.default_directory"] = default_download_dir
    
    options.add_experimental_option('prefs', prefs)
    
    return options, ext_dir


def create_driver_options_full(profile_dir, use_extension=False, default_download_dir=None, viewport_width=1280, viewport_height=1024):
    """Create Chrome options with all necessary configurations for regular Chrome driver."""
    options = Options()
    options.enable_bidi = True
    options.enable_webextensions = True
    
    options.add_argument(f'--user-data-dir={profile_dir}')
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument(f"--window-size={viewport_width},{viewport_height}")
    options.add_argument("--force-device-scale-factor=1")
    options.add_experimental_option("excludeSwitches", ['enable-automation', 'enable-logging'])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--disable-infobars')
    options.add_argument('--start-maximized')
    
    ext_dir = None
    if not use_extension:
        options.add_argument('--disable-extensions')
    else:
        ext_dir = Path(__file__).parent.parent / 'extension'
        options.add_argument(f'--load-extension={ext_dir}')
    
    options.add_argument('--no-sandbox')
    options.add_argument("--disable-features=DisableLoadExtensionCommandLineSwitch")
    options.add_argument('--disable-application-cache')
    options.add_argument('--disable-setuid-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_experimental_option('prefs', {
        "extensions.ui.developer_mode": True,
        'profile.default_content_setting_values.notifications': 5,
        'credentials_enable_service': True,
        'profile.password_manager_enabled': True,
        "plugins.always_open_pdf_externally": True,
        "download.default_directory": default_download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    })
    
    return options, ext_dir


def create_driver_with_captcha_handling(args,profile_dir, use_extension=False, default_download_dir=None, viewport_width=1280, viewport_height=1024):
    """
    Create a Chrome driver with undetected_chromedriver and stealth to handle captcha/Cloudflare.
    Falls back to regular Chrome if uc fails.
    
    Returns:
        tuple: (driver, use_uc_driver) - driver instance and boolean indicating if uc was used
    """
    # Try uc.Chrome first for captcha/Cloudflare handling
    if args.captcha_mode:
        try:
            options_uc, ext_dir_uc = create_driver_options_uc(
                use_extension=use_extension,
                default_download_dir=default_download_dir,
                viewport_width=viewport_width,
                viewport_height=viewport_height
            )
            
            try:
                driver = uc.Chrome(user_data_dir=str(profile_dir), options=options_uc,version_main=144)
                stealth(driver,
                        languages=["en-US", "en"],
                        vendor="Google Inc.",
                        platform="Win32",
                        webgl_vendor="Intel Inc.",
                        renderer="Intel Iris OpenGL Engine")
                print("✓ Using undetected_chromedriver with stealth for captcha/Cloudflare handling")
                return driver, True
            except Exception as e:
                print(f'⚠ Error with uc.Chrome, falling back to regular Chrome: {e}')
                # Fall through to regular Chrome
        except Exception as e:
            print(f'⚠ Error creating uc driver options: {e}')
    
    # Fallback to regular Chrome
    try:
        options_full, ext_dir_full = create_driver_options_full(
            str(profile_dir),
            use_extension=use_extension,
            default_download_dir=default_download_dir,
            viewport_width=viewport_width,
            viewport_height=viewport_height
        )
        service = Service(executable_path=ChromeDriverManager().install())
        driver = webdriver.Chrome(options=options_full, service=service)
        
        # Only use webextension.install() for regular Selenium Chrome (BiDi protocol not supported by uc.Chrome)
        if ext_dir_full:
            try:
                extension_result = driver.webextension.install(path=str(ext_dir_full))
                print(f"✓ Extension installed: {extension_result}")
            except Exception as e:
                print(f"⚠ Warning: Could not install extension via webextension.install(): {e}")
        
        print("✓ Using regular Selenium Chrome driver")
        return driver, False
    except Exception as e:
        print(f'✗ Error creating regular Chrome driver: {e}')
        raise


if args.google_signin:
    #Create a temp profile directory copied from `test_profile_just_google_signed_on` directory
    profile_dir = PARENT_DIR / 'temp_profile_just_google_signed_on' 
    if os.path.exists(profile_dir):
        shutil.rmtree(profile_dir) #If it already exists, delete it and copy from the original
    shutil.copytree(PARENT_DIR / 'test_profile_just_google_signed_on', profile_dir)
else:
    profile_dir = PARENT_DIR / test_profile_dir_name

print(f"Using profile directory: {profile_dir}")

# Create driver with captcha handling
driver_task, use_uc = create_driver_with_captcha_handling(
    args,
    str(profile_dir),
    use_extension=args.use_extension,
    default_download_dir=default_download_dir,
    viewport_width=1280,
    viewport_height=1024
)

# Navigate to website and check for captcha/Cloudflare
driver_task.get("https://www.google.com")

# Check for captcha (reCAPTCHA or Cloudflare)
print("Checking for captcha/Cloudflare...")
check_cloudflare(driver_task)

# Keep browser open for interaction
print("Browser is ready. Press Enter to close...")
x = input()

driver_task.quit()
