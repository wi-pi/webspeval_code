import os
import time
from selenium import webdriver
import requests
import socket
from selenium.webdriver.common.by import By
from RecaptchaSolver import RecaptchaSolver


def captcha_solver(driver):
    captcha = 0
    while captcha < 3:
        try:
            recaptchaSolver = RecaptchaSolver(driver)
            recaptchaSolver.solveCaptcha()
        except Exception:
            captcha += 1
            continue
        return True
    print("✗ Could not solve the captcha after multiple attempts.")
    return False


def is_recaptcha_present(driver):
    # 1. Check for the reCAPTCHA Iframe
    # This is the most reliable method for v2 (checkbox)|
    try:
        if len(driver.find_elements(By.CSS_SELECTOR, "iframe[src*='google.com/recaptcha']")) > 0:
            iframes = driver.find_elements(By.CSS_SELECTOR, "iframe[src*='google.com/recaptcha']")
            for iframe in iframes:
                # is_displayed() checks if the element is visible to the user
                # (width > 0, height > 0, opacity > 0, and not hidden)
                if iframe.is_displayed():
                    return True
        if len(driver.find_elements(By.CSS_SELECTOR, "iframe[src*='recaptcha.net']")) > 0:
            iframes = driver.find_elements(By.CSS_SELECTOR, "iframe[src*='recaptcha.net']")
            for iframe in iframes:
                # is_displayed() checks if the element is visible to the user
                # (width > 0, height > 0, opacity > 0, and not hidden)
                if iframe.is_displayed():
                    return True
    except:
        pass

    # # 2. Check for the "g-recaptcha" class
    # # Standard class for the widget container
    # if len(driver.find_elements(By.CLASS_NAME, "g-recaptcha")) > 0:
    #     return True
    #
    # # 3. Check for the Invisible reCAPTCHA Badge (v3 or invisible v2)
    # # This is the "Protected by reCAPTCHA" badge usually in the corner
    # if len(driver.find_elements(By.CLASS_NAME, "grecaptcha-badge")) > 0:
    #     return True
    #
    # # 4. Check for the hidden response textarea
    # # Even if the captcha is invisible, this field often exists to store the token
    # if len(driver.find_elements(By.NAME, "g-recaptcha-response")) > 0:
    #     return True

    return False


def check_cloudflare(driver: webdriver.Chrome):
    time.sleep(2)
    site = driver.current_url

    if is_recaptcha_present(driver):
        if not captcha_solver(driver):
            ntfy_url = os.environ.get("NTFY_TOPIC_URL", "")
            if ntfy_url:
                requests.post(
                    ntfy_url,
                    data="GOOGLE ReCAPTCHA FOUND!!",
                    headers={
                        "Title": f"GOOGLE ReCAPTCHA ALERT at {site}[{socket.gethostname()}]",
                        "Priority": "high",
                        "Tags": "warning,skull"  # Adds emojis
                    }
                )
            input("Google ReCAPTCHA detected! Please solve it manually and press Enter to continue...")

    if driver.execute_script("if (window.turnstile) return true;"):
        ntfy_url = os.environ.get("NTFY_TOPIC_URL", "")
        if ntfy_url:
            requests.post(
                ntfy_url,
                data="CLOUDFLARE CAPTCHA FOUND!!",
                headers={
                    "Title": f"CLOUDFLARE CAPTCHA ALERT at {site}[{socket.gethostname()}]",
                    "Priority": "high",
                    "Tags": "warning,skull"  # Adds emojis
                }
            )
        input("Cloudflare CAPTCHA detected! Please solve it manually and press Enter to continue...")