"""
Utilities for resetting browser history by visiting a set of links.

Opens a headless browser and visits predefined links to populate browser history.
"""

import time
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from .extension_reset import load_json_file


def reset_history(
    # website_name: str,
    headless: bool = True,
) -> None:
    """
    Open a selenium browser and visit a set of links for different domains to populate browser history.
    
    Args:
        # website_name: Name of the website (key in history_links.json) [REMOVED FOR NOW]
        headless: Whether to run browser in headless mode (default: True)
    
    Raises:
        KeyError: If website_name is not found in history_links.json
        FileNotFoundError: If history_links_file doesn't exist
    """

    PARENT_DIR = Path(__file__).parent.parent
    profile_dir = PARENT_DIR / "test_profile"
    history_links_file = Path(__file__).parent / "history_links.json"
    
    # Load website links
    website_links_dict = load_json_file(history_links_file) #Removed specific website links for now
    
    # Flatten all URL lists from all website keys into a single list
    website_links = []
    for website_name, url_list in website_links_dict.items():
        if isinstance(url_list, list):
            website_links.extend(url_list)
        else:
            print(f"Warning: Expected list for '{website_name}', got {type(url_list)}")
    
    if not website_links:
        raise ValueError("No valid URLs found in history_links.json")
    
    print(f"Loaded {len(website_links)} URLs from {len(website_links_dict)} websites")
    
    # Setup Chrome options
    options = Options()
    options.add_argument("--window-size=1280,1024")
    options.add_argument(f'--user-data-dir={str(profile_dir)}')
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--force-device-scale-factor=1")
    
    if headless:
        options.add_argument('--headless')
    
    options.add_experimental_option("excludeSwitches", ['enable-automation', 'enable-logging'])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--disable-infobars')
    options.add_argument('--disable-extensions')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-application-cache')
    options.add_argument('--disable-setuid-sandbox')
    
    options.add_experimental_option('prefs', {
        "extensions.ui.developer_mode": True,
        'profile.default_content_setting_values.notifications': 5,
        'credentials_enable_service': True,
        'profile.password_manager_enabled': True,
        "safebrowsing.enabled": True,
        "autoscroll": False,
        "smooth_scrolling": False
    })
    
    # Create driver and visit links
    service = Service(executable_path=ChromeDriverManager().install())
    driver = None
    
    try:
        driver = webdriver.Chrome(options=options, service=service)
        
        for link in website_links:
            print(f"Visiting: {link}")
            driver.get(link)
            time.sleep(1)  # Wait for page to load and history to be recorded
        
        print(f"Success! Visited {len(website_links)} links for different domains")
    
    except Exception as e:
        print(f"Error resetting history for different domains: {e}")
        raise
    
    finally:
        if driver:
            driver.quit()


def reset_cookies(website_url: str, driver: webdriver.Chrome) -> None:
    """
    Reset cookies for a specific website.
    
    Args:
        website_url: URL of the website (e.g., "https://www.example.com")
        driver: Selenium WebDriver instance
    
    Note: Navigates to the website first, then deletes all cookies for that domain.
    """
    from urllib.parse import urlparse
    
    # Extract domain from URL for logging
    parsed = urlparse(website_url)
    domain = parsed.netloc or parsed.path.split('/')[0]
    
    # Navigate to the website to access its cookies
    driver.get(website_url)
    
    # Get cookies count before deletion (for logging)
    cookies_before = driver.get_cookies()
    
    # Delete all cookies for the current domain
    driver.delete_all_cookies()
    
    print(f"Deleted {len(cookies_before)} cookie(s) for {domain}")

# from selenium import webdriver

# driver = webdriver.Chrome()
# driver.get("https://example.com")

# # Remove all cookies
# driver.delete_all_cookies()

# # Or remove one cookie by name
# driver.delete_cookie("sessionid")

# # Confirm
# print(driver.get_cookies())
