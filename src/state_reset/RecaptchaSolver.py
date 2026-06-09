import os
import urllib.request
import random
import pydub
import speech_recognition
import time
from typing import Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException


class RecaptchaSolver:
    """A class to solve reCAPTCHA challenges using audio recognition."""

    # Constants
    TEMP_DIR = os.getenv("TEMP") if os.name == "nt" else "/tmp"
    TIMEOUT_STANDARD = 7
    TIMEOUT_SHORT = 1
    TIMEOUT_DETECTION = 0.05

    def __init__(self, driver: webdriver.Chrome) -> None:
        """Initialize the solver with a Selenium Chrome WebDriver.

        Args:
            driver: Selenium Chrome WebDriver instance for browser interaction
        """
        self.driver = driver
        self.wait = WebDriverWait(driver, self.TIMEOUT_STANDARD)

    def solveCaptcha(self) -> None:
        """Attempt to solve the reCAPTCHA challenge.

        Raises:
            Exception: If captcha solving fails or bot is detected
        """

        # Handle main reCAPTCHA iframe
        self.wait.until(
            EC.frame_to_be_available_and_switch_to_it((By.CSS_SELECTOR, "iframe[title='reCAPTCHA']"))
        )
        time.sleep(0.1)

        # Click the checkbox
        checkbox = self.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".rc-anchor-content"))
        )
        checkbox.click()

        # Switch back to main content
        self.driver.switch_to.default_content()

        # Check if solved by just clicking
        if self.is_solved():
            return

        # Handle audio challenge iframe
        challenge_iframe = self.wait.until(
            EC.presence_of_element_located((By.XPATH, "//iframe[contains(@title, 'recaptcha')]"))
        )
        self.driver.switch_to.frame(challenge_iframe)

        # Click audio button
        audio_button = self.wait.until(
            EC.element_to_be_clickable((By.ID, "recaptcha-audio-button"))
        )
        audio_button.click()
        time.sleep(0.3)

        if self.is_detected():
            raise Exception("Captcha detected bot behavior")

        # Download and process audio
        audio_source = self.wait.until(
            EC.presence_of_element_located((By.ID, "audio-source"))
        )
        src = audio_source.get_attribute("src")

        try:
            text_response = self._process_audio_challenge(src)
            
            # Enter the response
            audio_response_input = self.driver.find_element(By.ID, "audio-response")
            audio_response_input.send_keys(text_response.lower())
            
            # Click verify button
            verify_button = self.driver.find_element(By.ID, "recaptcha-verify-button")
            verify_button.click()
            time.sleep(0.4)

            # Switch back to main content
            self.driver.switch_to.default_content()

            if not self.is_solved():
                raise Exception("Failed to solve the captcha")

        except Exception as e:
            self.driver.switch_to.default_content()
            raise Exception(f"Audio challenge failed: {str(e)}")

    def _process_audio_challenge(self, audio_url: str) -> str:
        """Process the audio challenge and return the recognized text.

        Args:
            audio_url: URL of the audio file to process

        Returns:
            str: Recognized text from the audio file
        """
        mp3_path = os.path.join(self.TEMP_DIR, f"{random.randrange(1, 1000)}.mp3")
        wav_path = os.path.join(self.TEMP_DIR, f"{random.randrange(1, 1000)}.wav")

        try:
            urllib.request.urlretrieve(audio_url, mp3_path)
            sound = pydub.AudioSegment.from_mp3(mp3_path)
            sound.export(wav_path, format="wav")

            recognizer = speech_recognition.Recognizer()
            with speech_recognition.AudioFile(wav_path) as source:
                audio = recognizer.record(source)

            return recognizer.recognize_google(audio)

        finally:
            for path in (mp3_path, wav_path):
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass

    def is_solved(self) -> bool:
        """Check if the captcha has been solved successfully."""
        try:
            # Switch to the main reCAPTCHA iframe to check the checkbox
            iframe = self.driver.find_element(By.CSS_SELECTOR, "iframe[title='reCAPTCHA']")
            self.driver.switch_to.frame(iframe)
            
            checkmark = self.driver.find_element(By.CSS_SELECTOR, ".recaptcha-checkbox-checkmark")
            is_solved = checkmark.get_attribute("style") is not None and "style" in checkmark.get_attribute("outerHTML")
            
            # Switch back to main content
            self.driver.switch_to.default_content()
            return is_solved
        except NoSuchElementException:
            return True

        except TimeoutException:
            # Make sure we're back in the main content even if there was an error
            try:
                self.driver.switch_to.default_content()
            except:
                pass
            return False

    def is_detected(self) -> bool:
        """Check if the bot has been detected."""
        try:
            # Use a very short wait to check for the "Try again later" message
            short_wait = WebDriverWait(self.driver, self.TIMEOUT_DETECTION)
            element = short_wait.until(
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Try again later')]"))
            )
            return element.is_displayed()
        except (TimeoutException, NoSuchElementException):
            return False

    def get_token(self) -> Optional[str]:
        """Get the reCAPTCHA token if available."""
        try:
            token_element = self.driver.find_element(By.ID, "recaptcha-token")
            return token_element.get_attribute("value")
        except (NoSuchElementException, TimeoutException):
            return None