"""
Utilities for replaying extension recordings for resetting website state.

These helpers power both the standalone replay script
(`selenium_state_reset_check_v3.py`) and any other tooling that needs to
programmatically enforce ON/OFF toggle states before executing tasks.
"""

from pathlib import Path
import os
import json
import traceback
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, InvalidSelectorException, StaleElementReferenceException, ElementClickInterceptedException
import time
import random
import re
from typing import List, Optional, Sequence, Tuple

# Note: check_cloudflare is imported locally inside functions to avoid circular import
# (utils.py imports from state_reset.RecaptchaSolver, and run_with_replay.py imports both)

DEFAULT_EXTENSION_DIR ='../UsersFirst-annotation_v3'

def _fill_account_placeholders(text):
    for placeholder, env_var in (
        ("{{WEBSP_ACCOUNT_EMAIL}}", "WEBSP_ACCOUNT_EMAIL"),
        ("{{WEBSP_ACCOUNT_USERNAME}}", "WEBSP_ACCOUNT_USERNAME"),
        ("{{WEBSP_ACCOUNT_NAME}}", "WEBSP_ACCOUNT_NAME"),
    ):
        value = os.environ.get(env_var)
        if value:
            text = text.replace(placeholder, json.dumps(value)[1:-1])
    return text

def load_json_file(json_file):
    with open(json_file, 'r', encoding='utf-8') as f:
        text = f.read()
    return json.loads(_fill_account_placeholders(text))

def save_json_file(json_file, data):
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def switch_to_frame_path(driver, frame_path):
    """Switch to the correct iframe based on framePath"""
    driver.switch_to.default_content()
    for selector in (frame_path or []):
        # Skip empty or invalid selectors
        if not selector or not isinstance(selector, str) or not selector.strip():
            continue
        try:
            iframe = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            driver.switch_to.frame(iframe)
            print(f"  ✓ Switched to iframe: {selector}")

            # Wait for iframe content to fully render (Added this delay to ensure the iframe state is set properly by the website)
            time.sleep(4)
            print(f"  ⏳ Waited 2 seconds for iframe content to render")
        except TimeoutException:
            print(f"Warning: Could not find iframe with selector: {selector}")

def find_element_by_websp_index(driver, websp_index):
    """
    Locate an element by the recorded WEBSP (tab) index.
    This reconstructs the tabbable elements list at runtime and returns the Nth element (1-based in events, but we must use 0-based for replay).

    Args:
        driver: Selenium WebDriver instance (already switched into the correct frame)
        websp_index: 1-based index recorded by the extension

    Returns:
        WebElement if found, None otherwise
    """
    if not websp_index:
        return None
    try:
        # WEBSPIndex in the JSON/events is 1-based; convert to 0-based for JS lookup
        # js_index = int(websp_index)
        js_index = websp_index

        js_code = """
            function getElementByWebspIndex(index) {
              const selector = '[data-websp-index="' + index + '"]';

              function searchTree(root) {
                const element = root.querySelector(selector);
                if (element) return element;

                const hosts = root.querySelectorAll('*');
                for (const host of hosts) {
                  if (host.shadowRoot) {
                    const found = searchTree(host.shadowRoot);
                    if (found) return found;
                  }
                }
                return null;
              }

              return searchTree(document);
            }

            return getElementByWebspIndex(arguments[0]);
            """

        ele = driver.execute_script(js_code, str(js_index))
        return ele

        # element = driver.execute_script("return (function(){" + script + "}).apply(null, arguments);", js_index)
        # return element
    except Exception as e:
        print(f"    ✗ WEBSP index lookup failed: {type(e).__name__}: {str(e)}")
        return None

def find_element_in_shadow_dom(driver, aria_label, role=None, tag_name=None):
    """
    Find an element inside shadow DOM by searching recursively through all shadow roots.
    
    This is necessary for custom web components like Reddit's faceplate-switch-input
    that use shadow DOM encapsulation.
    
    Args:
        driver: Selenium WebDriver instance
        aria_label: The aria-label attribute value to search for
        role: Optional role attribute to match (e.g., 'checkbox', 'switch')
        tag_name: Optional tag name to match (e.g., 'faceplate-switch-input')
    
    Returns:
        WebElement if found, None otherwise
    """
    js_code = """
        function findElementInShadowDOM(ariaLabel, role, tagName) {
            function searchTree(root) {
                // Try to find in current root by aria-label
                let selector = '[aria-label="' + ariaLabel.replace(/"/g, '\\\\"') + '"]';
                
                // If we have a tag name, be more specific
                if (tagName) {
                    selector = tagName + selector;
                }
                
                // If we have a role, add it to selector
                if (role) {
                    selector += '[role="' + role + '"]';
                }
                
                let element = root.querySelector(selector);
                if (element) return element;
                
                // Also try without tag name if tag-specific search failed
                if (tagName) {
                    selector = '[aria-label="' + ariaLabel.replace(/"/g, '\\\\"') + '"]';
                    if (role) {
                        selector += '[role="' + role + '"]';
                    }
                    element = root.querySelector(selector);
                    if (element) return element;
                }
                
                // Search in all shadow roots
                const allElements = root.querySelectorAll('*');
                for (const el of allElements) {
                    if (el.shadowRoot) {
                        const found = searchTree(el.shadowRoot);
                        if (found) return found;
                    }
                }
                
                return null;
            }
            
            return searchTree(document);
        }
        
        return findElementInShadowDOM(arguments[0], arguments[1], arguments[2]);
    """
    
    try:
        element = driver.execute_script(js_code, aria_label, role, tag_name)
        return element
    except Exception as e:
        print(f"    ✗ Shadow DOM search failed: {type(e).__name__}: {str(e)}")
        return None


def find_element_by_selector_in_shadow_dom(driver, selector_path):
    """
    Parse a selector path containing ::shadow and navigate through shadow DOMs.
    
    Handles selectors like:
    main#main-content > div > settings-privacy-section > ::shadow > div > label > faceplate-switch-input
    
    Args:
        driver: Selenium WebDriver instance
        selector_path: CSS selector path that may contain ::shadow markers
    
    Returns:
        WebElement if found, None otherwise
    """
    if '::shadow' not in selector_path:
        return None
    
    js_code = """
        function findElementWithShadow(selectorPath) {
            // Split by ::shadow to get parts before and after shadow boundaries
            const parts = selectorPath.split(/\\s*>\\s*::shadow\\s*>\\s*/);
            
            if (parts.length < 2) return null;
            
            let currentRoot = document;
            
            for (let i = 0; i < parts.length; i++) {
                const selector = parts[i].trim();
                if (!selector) continue;
                
                // Find element in current root
                let element;
                try {
                    element = currentRoot.querySelector(selector);
                } catch (e) {
                    // Invalid selector, try to fix common issues
                    console.log('Invalid selector:', selector, e);
                    return null;
                }
                
                if (!element) {
                    console.log('Element not found for selector:', selector);
                    return null;
                }
                
                // If this is the last part, return the element
                if (i === parts.length - 1) {
                    return element;
                }
                
                // Otherwise, we need to enter the shadow root
                if (element.shadowRoot) {
                    currentRoot = element.shadowRoot;
                } else {
                    console.log('No shadow root on element:', element);
                    return null;
                }
            }
            
            return null;
        }
        
        return findElementWithShadow(arguments[0]);
    """
    
    try:
        element = driver.execute_script(js_code, selector_path)
        return element
    except Exception as e:
        print(f"    ✗ Shadow selector parsing failed: {type(e).__name__}: {str(e)}")
        return None


def find_element_by_event(driver, event, previous_dom_changes=None):
    """
    Find element using semantic information with fallback strategy.
    Priority order:
    0. Shadow DOM search by aria-label (for elements inside shadow roots)
    1. data-testid, data-cy, data-automation (most stable)
    2. id
    3. name (for form inputs)
    4. aria-label
    5. label text matching
    6. nearbyLabelText (text from siblings)
    7. parentTextContext (text from parent containers)
    8. CSS selector (position-based)
    9. XPath
    10. DOM changes (for dynamically added elements)
    11. webspIndex (tab order) - last resort

    Args:
        driver: Selenium WebDriver instance
        event: Event dictionary containing element information
        previous_dom_changes: List of DOM changes from previous events (for finding dynamically added elements)
    """
    # Debug: Print available semantic info
    semantic_info = {
        'dataTestId': event.get('dataTestId'),
        'dataCy': event.get('dataCy'),
        'id': event.get('id'),
        'name': event.get('name'),
        'ariaLabel': event.get('ariaLabel'),
        'labelText': event.get('labelText'),
        'innerText': event.get('innerText'),
        'nearbyLabelText': event.get('nearbyLabelText'),
        'parentTextContext': event.get('parentTextContext'),
    }
    available = {k: v for k, v in semantic_info.items() if v}
    if available:
        print(f"    Semantic info available: {available}")
    
    # Strategy 0: Check if selector contains ::shadow (shadow DOM element)
    # If so, try shadow DOM search FIRST using aria-label
    selector_path = event.get('selectorPath', '')
    aria_label = event.get('ariaLabel')
    role = event.get('role')
    tag_name = event.get('tagName')
    
    if '::shadow' in selector_path and aria_label:
        print(f"    Detected shadow DOM element (::shadow in selector)")
        print(f"    Attempting shadow DOM search by aria-label: '{aria_label[:60]}...'")
        
        # Try finding by aria-label in shadow DOM
        element = find_element_in_shadow_dom(driver, aria_label, role=role, tag_name=tag_name)
        if element:
            try:
                element_id = element.get_attribute('id')
                element_class = element.get_attribute('class')
                element_role = element.get_attribute('role')
                element_aria_label = element.get_attribute('aria-label')
                print(f"    ✓ Found element in shadow DOM:")
                print(f"      tag={element.tag_name}, role='{element_role}', class='{element_class[:50] if element_class else None}...'")
                print(f"      aria-label='{element_aria_label[:60] if element_aria_label else None}...'")
            except:
                print(f"    ✓ Found element in shadow DOM via aria-label")
            return element
        
        # Also try the shadow selector parsing approach
        element = find_element_by_selector_in_shadow_dom(driver, selector_path)
        if element:
            print(f"    ✓ Found element by parsing shadow selector path")
            return element
    
    strategies = []
    
    # Strategy 0a: For switch elements with aria-label containing topic (e.g., Google Ad Center buttons)
    # This is more reliable than webspIndex when DOM updates after interactions
    # Uses role="switch" + aria-label topic to find the correct element
    aria_label = event.get('ariaLabel')
    role = event.get('role')
    if aria_label and role == 'switch' and 'ads about:' in aria_label:
        # Extract topic from aria-label (text after "ads about:")
        # Handles both "Limit ads about: Topic" and "Allow ads about: Topic"
        # Example: "Limit ads about: Pregnancy and parenting" -> "Pregnancy and parenting"
        topic = aria_label.split('ads about:')[-1].strip()
        if topic:
            print(f"    Attempting to find switch by role + aria-label topic: '{topic}'")
            # Escape topic for XPath (handle quotes and special chars)
            topic_escaped = topic.replace("'", "\\'")
            try:
                # Find switch button with role="switch" and aria-label containing the topic
                # The topic is the unique identifier (e.g., "Pregnancy and parenting", "Alcohol", etc.)
                xpath = f'//button[@role="switch" and contains(@aria-label, "{topic_escaped}")]'
                elements = driver.find_elements(By.XPATH, xpath)
                if elements:
                    # Verify we found the right element by checking topic appears in aria-label
                    for elem in elements:
                        elem_aria_label = elem.get_attribute('aria-label') or ''
                        elem_aria_checked = elem.get_attribute('aria-checked')
                        # Check if topic appears in the aria-label (handles both "Limit" and "Allow" prefixes)
                        if topic in elem_aria_label and 'ads about:' in elem_aria_label:
                            print(f"    ✓ Found switch element by role + aria-label topic: '{topic}'")
                            print(f"      Element aria-label: '{elem_aria_label[:60]}...'")
                            print(f"      Element aria-checked: {elem_aria_checked}")
                            return elem
                    # If no exact match found, return first one (shouldn't happen, but fallback)
                    if elements:
                        print(f"    ✓ Found switch element by role + aria-label topic (first match): '{topic}'")
                        return elements[0]
            except Exception as e:
                print(f"    ✗ Could not find switch by role + topic: {e}")

    # Strategy 0: WEBSP index (tab order) if provided by the extension
    # Store WEBSP index for later use as last resort strategy
    # websp_index = event.get('webspIndex') or event.get('webspindex')
    #
    # print(f"    WEBSP index from event: {websp_index}")
    # if websp_index is not None:
    #     try:
    #         # Extension updated to not need such adjustment
    #         websp_index = int(websp_index) # - 1
    #         print(f"    Attempting to find element with webspIndex: {websp_index}")
    #         element = find_element_by_websp_index(driver, websp_index)
    #         if element is not None:
    #             # Get some debug info about the found element
    #             try:
    #                 element_id = element.get_attribute('id')
    #                 element_class = element.get_attribute('class')
    #                 element_role = element.get_attribute('role')
    #                 element_websp_index = element.get_attribute('data-websp-index')
    #                 element_aria_label = element.get_attribute('aria-label')
    #                 print(f"    ✓ Found element using webspIndex {websp_index}:")
    #                 print(f"      id='{element_id}', class='{element_class[:50] if element_class else None}...'")
    #                 print(f"      role='{element_role}', websp-index='{element_websp_index}'")
    #                 print(f"      aria-label='{element_aria_label[:60] if element_aria_label else None}...'")
    #
    #                 # Verify the aria-label matches for Google Ad Center buttons
    #                 expected_aria_label = event.get('ariaLabel')
    #                 if expected_aria_label and element_aria_label:
    #                     # For Google Ad buttons, the text after "ads about:" should match
    #                     # Extract topic name from both (e.g., "Pregnancy and parenting")
    #                     if 'ads about:' in expected_aria_label and 'ads about:' in element_aria_label:
    #                         expected_topic = expected_aria_label.split('ads about:')[-1].strip()
    #                         found_topic = element_aria_label.split('ads about:')[-1].strip()
    #                         if expected_topic != found_topic:
    #                             print(f"    ⚠ Warning: aria-label topic mismatch!")
    #                             print(f"      Expected topic: '{expected_topic}'")
    #                             print(f"      Found topic: '{found_topic}'")
    #                             print(f"    ✗ WebspIndex found wrong element, will try other strategies")
    #                             # Don't return this element, fall through to other strategies
    #                         else:
    #                             print(f"    ✓ aria-label topic verified: '{expected_topic}'")
    #                             return element
    #                     else:
    #                         # Not a Google Ad button, return the element found
    #                         return element
    #                 else:
    #                     # No aria-label to verify, return the element
    #                     return element
    #             except:
    #                 print(f"    ✓ Found element using webspIndex: {websp_index}")
    #                 return element
    #         else:
    #             print(f"    ✗ webspIndex {websp_index} returned None (element not found)")
    #     except Exception as e:
    #         print(f"    ✗ Could not find element by webspIndex {websp_index}: {e}")

    def escape_css_attr(value: str):
        """Escape double quotes in CSS attribute values and wrap with double quotes."""
        if value is None:
            return None
        try:
            return value.replace('"', '\\"')
        except Exception:
            return value

    def sanitize_selector_path(selector: str) -> str:
        """
        Convert invalid ID fragments like tag#:r2f: into tag[id=":r2f:"] so CSS remains valid.
        Also leaves other parts unchanged. Safe no-op if nothing to fix.
        """
        if not selector or not isinstance(selector, str):
            return selector
        try:
            # Replace any #<id> run (until space/combinator/comma) with [id="<id>"]
            # This allows IDs containing characters like ':' without needing CSS escapes.
            def repl(match):
                raw_id = match.group(1)
                esc = escape_css_attr(raw_id)
                return f'[id="{esc}"]'

            # Apply within each simple selector sequence; handle multiple occurrences
            sanitized = re.sub(r'#([^\s>+~,]+)', repl, selector)
            return sanitized
        except Exception:
            return selector

    def find_switch_by_label(driver, label_text: str):
        """Find a switch/checkbox input by a nearby label text, robust to dynamic React Aria IDs.
        Tries several XPath patterns within likely switch containers.
        """
        try:
            # 1) Label with exact text, use its 'for' if present, else find input in same container
            label_exact_xpath = f"//label[normalize-space(.) = '{label_text}']"
            labels = driver.find_elements(By.XPATH, label_exact_xpath)
            for lbl in labels[:5]:
                try:
                    for_id = lbl.get_attribute('for')
                    if for_id:
                        try:
                            return driver.find_element(By.ID, for_id)
                        except Exception:
                            pass
                    # search within switch container ancestor
                    container = None
                    try:
                        container = lbl.find_element(By.XPATH, "ancestor::*[contains(@class, 'gds-switch') or @role='switch' or @data-label-display][1]")
                    except Exception:
                        # fallback to immediate parent
                        try:
                            container = lbl.find_element(By.XPATH, '..')
                        except Exception:
                            container = None
                    if container is not None:
                        candidates = container.find_elements(By.XPATH, ".//input[@role='switch' or @type='checkbox']")
                        if candidates:
                            return candidates[0]
                except Exception:
                    continue
        except Exception:
            pass

        try:
            # 2) Fuzzy match label text within a switch container
            label_contains_xpath = f"//*[self::label or self::span][contains(normalize-space(.), '{label_text}')]/ancestor::*[contains(@class,'gds-switch') or @data-label-display][1]//input[@role='switch' or @type='checkbox']"
            elems = driver.find_elements(By.XPATH, label_contains_xpath)
            if elems:
                return elems[0]
        except Exception:
            pass

        try:
            # 3) Generic: any input switch on page if only one
            elems = driver.find_elements(By.XPATH, "//input[@role='switch' or (contains(@class,'switch') and @type='checkbox')]")
            if len(elems) == 1:
                return elems[0]
        except Exception:
            pass

        return None
    
    # Strategy 1: data-testid/data-cy/data-automation
    if event.get('dataTestId'):
        esc = escape_css_attr(event['dataTestId'])
        strategies.append(('data-testid', By.CSS_SELECTOR, f'[data-testid="{esc}"]'))
        strategies.append(('data-test-id', By.CSS_SELECTOR, f'[data-test-id="{esc}"]'))
    if event.get('dataCy'):
        esc = escape_css_attr(event['dataCy'])
        strategies.append(('data-cy', By.CSS_SELECTOR, f'[data-cy="{esc}"]'))
    if event.get('dataAutomation'):
        esc = escape_css_attr(event['dataAutomation'])
        strategies.append(('data-automation', By.CSS_SELECTOR, f'[data-automation="{esc}"]'))
    
    # Strategy 2: ID (with explicit wait for React/SPA content)
    if event.get('id'):
        element_id = event['id']
        try:
            # Wait up to 5 seconds for element with this ID to appear (React SPA content)
            print(f"    Waiting for element with ID: {element_id}")
            element = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, element_id))
            )
            print(f"    ✓ Found element using id (with wait): {element_id}")
            return element
        except TimeoutException:
            print(f"    ✗ Element with ID '{element_id}' not found after 5 second wait")
            # Fall through to other strategies
        
        strategies.append(('id', By.ID, element_id))
    
    # Strategy 3: Name (for form elements)
    if event.get('name'):
        element_type = event.get('type', '')
        if element_type in ['checkbox', 'radio', 'text', 'email', 'password', 'select', 'textarea']:
            strategies.append(('name', By.NAME, event['name']))
    
    # Strategy 4: aria-label
    if event.get('ariaLabel'):
        esc = escape_css_attr(event['ariaLabel'])
        strategies.append(('aria-label', By.CSS_SELECTOR, f'[aria-label="{esc}"]'))
    
    # Strategy 5: Label text matching (implemented separately below)
    label_text = event.get('labelText')
    
    # Strategy 6: nearbyLabelText - search for text in nearby elements
    nearby_label_text = event.get('nearbyLabelText')
    
    # Strategy 7: parentTextContext - search within parent context
    parent_text_context = event.get('parentTextContext')
    
    # Strategy 8: CSS selector (position-based)
    if event.get('selectorPath'):
        raw_selector = event['selectorPath']
        sanitized_selector = sanitize_selector_path(raw_selector)
        # Try sanitized first if it differs, then raw
        if sanitized_selector != raw_selector:
            strategies.append(('css-selector', By.CSS_SELECTOR, sanitized_selector))
        strategies.append(('css-selector', By.CSS_SELECTOR, raw_selector))
    
    # Strategy 9: XPath (last resort)
    if event.get('xpath'):
        strategies.append(('xpath', By.XPATH, event['xpath']))
    
    # Strategy 8b: role-based quick hint for switches
    # input_type_hint = (event.get('inputType') or '').lower()
    # role_hint = (event.get('role') or '').lower()
    # if input_type_hint == 'switch' or role_hint == 'switch':
    #     strategies.insert(0, ('role-switch', By.CSS_SELECTOR, '[role="switch"], input[role="switch"], input.gds-switch-input'))

    # Try each strategy in order
    for strategy_name, by_type, locator in strategies:
        try:
            element = driver.find_element(by_type, locator)
            # Get debug info about the found element
            try:
                element_id = element.get_attribute('id')
                element_class = element.get_attribute('class')
                element_role = element.get_attribute('role')
                element_websp_index = element.get_attribute('data-websp-index')
                print(f"    ✓ Found element using {strategy_name}: {locator}")
                print(f"      Element details: id='{element_id}', class='{element_class}', role='{element_role}', websp-index='{element_websp_index}'")
            except:
                print(f"    ✓ Found element using {strategy_name}: {locator}")
            return element
        except NoSuchElementException:
            print(f"    ✗ Could not find element by {strategy_name}: {locator}")
            continue
        except InvalidSelectorException as e:
            print(f"    ✗ Invalid selector for {strategy_name}: {locator} ({e.msg})")
            # If CSS selector was invalid, try XPath fallback if available
            if strategy_name in ['css-selector', 'aria-label', 'data-testid', 'data-test-id', 'data-cy', 'data-automation'] and event.get('xpath'):
                try:
                    element = driver.find_element(By.XPATH, event['xpath'])
                    print(f"    ✓ Fallback to XPath succeeded: {event['xpath']}")
                    return element
                except Exception:
                    pass
            continue
    
    # Strategy 5a: Find overlay trigger buttons by aria-haspopup attribute
    # These buttons open dropdowns/overlays - their text shows current selections and changes based on state
    # So we find them by aria-haspopup attribute + class, not by text content
    # Handles both aria-haspopup="dialog" and aria-haspopup="true"
    outer_html_raw = event.get('outerHTML', '')
    has_aria_haspopup = 'aria-haspopup="dialog"' in outer_html_raw or 'aria-haspopup="true"' in outer_html_raw
    if has_aria_haspopup:
        print(f"    Detected overlay trigger button (aria-haspopup)")
        try:
            # Find all buttons with aria-haspopup (either "dialog" or "true")
            elements = driver.find_elements(By.XPATH, "//button[@aria-haspopup='dialog' or @aria-haspopup='true']")
            if elements:
                # If there's only one, return it
                if len(elements) == 1:
                    print(f"    ✓ Found overlay trigger button (only one on page)")
                    return elements[0]
                
                # If multiple, try to match by aria-labelledby or aria-describedby
                aria_labelledby = event.get('ariaLabelledby') or event.get('ariaLabelledBy')
                aria_describedby = event.get('ariaDescribedby') or event.get('ariaDescribedBy')
                
                for elem in elements:
                    elem_labelledby = elem.get_attribute('aria-labelledby')
                    elem_describedby = elem.get_attribute('aria-describedby')
                    
                    # Match by aria-labelledby if available
                    if aria_labelledby and elem_labelledby:
                        # Check if any part of the labelledby matches (IDs are dynamic but structure is similar)
                        if any(part in elem_labelledby for part in aria_labelledby.split()):
                            print(f"    ✓ Found overlay trigger button by aria-labelledby match")
                            return elem
                    
                    # Match by aria-describedby if available
                    if aria_describedby and elem_describedby:
                        if any(part in elem_describedby for part in aria_describedby.split()):
                            print(f"    ✓ Found overlay trigger button by aria-describedby match")
                            return elem
                
                # If no specific match, return the first one with matching class
                event_class = event.get('classList', [])
                for elem in elements:
                    elem_class = elem.get_attribute('class') or ''
                    if 'prc-Button-ButtonBase' in elem_class:
                        print(f"    ✓ Found overlay trigger button by class match")
                        return elem
                
                # Last resort: return first match
                print(f"    ✓ Found overlay trigger button (first of {len(elements)})")
                return elements[0]
        except Exception as e:
            print(f"    ✗ Could not find overlay trigger button: {e}")
    
    # Strategy 10 : WEBSP index (tab order) if provided by the extension

    # Strategy 0: WEBSP index (tab order) if provided by the extension
    # Store WEBSP index for later use as last resort strategy
    websp_index = event.get('webspIndex') or event.get('webspindex')

    print(f"    WEBSP index from event: {websp_index}")
    if websp_index is not None:
        try:
            # Extension updated to not need such adjustment
            websp_index = int(websp_index)  # - 1
            print(f"    Attempting to find element with webspIndex: {websp_index}")
            element = find_element_by_websp_index(driver, websp_index)
            if element is not None:
                # Get some debug info about the found element
                try:
                    element_id = element.get_attribute('id')
                    element_class = element.get_attribute('class')
                    element_role = element.get_attribute('role')
                    element_websp_index = element.get_attribute('data-websp-index')
                    element_aria_label = element.get_attribute('aria-label')
                    print(f"    ✓ Found element using webspIndex {websp_index}:")
                    print(f"      id='{element_id}', class='{element_class[:50] if element_class else None}...'")
                    print(f"      role='{element_role}', websp-index='{element_websp_index}'")
                    print(f"      aria-label='{element_aria_label[:60] if element_aria_label else None}...'")

                    # Verify the aria-label matches for Google Ad Center buttons
                    expected_aria_label = event.get('ariaLabel')
                    if expected_aria_label and element_aria_label:
                        # For Google Ad buttons, the text after "ads about:" should match
                        # Extract topic name from both (e.g., "Pregnancy and parenting")
                        if 'ads about:' in expected_aria_label and 'ads about:' in element_aria_label:
                            expected_topic = expected_aria_label.split('ads about:')[-1].strip()
                            found_topic = element_aria_label.split('ads about:')[-1].strip()
                            if expected_topic != found_topic:
                                print(f"    ⚠ Warning: aria-label topic mismatch!")
                                print(f"      Expected topic: '{expected_topic}'")
                                print(f"      Found topic: '{found_topic}'")
                                print(f"    ✗ WebspIndex found wrong element, will try other strategies")
                                # Don't return this element, fall through to other strategies
                            else:
                                print(f"    ✓ aria-label topic verified: '{expected_topic}'")
                                return element
                        else:
                            # Not a Google Ad button, return the element found
                            return element
                    else:
                        # No aria-label to verify, return the element
                        return element
                except:
                    print(f"    ✓ Found element using webspIndex: {websp_index}")
                    return element
            else:
                print(f"    ✗ webspIndex {websp_index} returned None (element not found)")
        except Exception as e:
            print(f"    ✗ Could not find element by webspIndex {websp_index}: {e}")

    # if websp_index is not None:
    #     try:
    #         element = find_element_by_websp_index(driver, websp_index)
    #         if element is not None:
    #             print(f"    ✓ Found element using webspIndex (last resort): {websp_index}")
    #             return element
    #         else:
    #             print(f"    ✗ Could not find element by webspIndex {websp_index}: returned None")
    #     except Exception as e:
    #         print(f"    ✗ Could not find element by webspIndex {websp_index}: {e}")
    # Strategy 5b: Special handling for switches by label text (React Aria / Grammarly)
    if label_text:
        try:
            # First, try switch-aware search
            element = find_switch_by_label(driver, label_text)
            if element:
                print(f"    ✓ Found switch by label text: '{label_text}'")
                return element
            # Fallback to generic label association
            element = find_element_by_label_text(driver, label_text, event)
            if element:
                print(f"    ✓ Found element using label text: '{label_text}'")
                return element
        except Exception as e:
            print(f"    ✗ Could not find element by label text '{label_text}': {e}")
    
    # Strategy 6a: Find elements by their innerText/textContent
    # This is useful when CSS selectors fail due to dynamic IDs (e.g., dialog buttons, list options)
    inner_text = event.get('innerText') or event.get('textContent')
    element_type = (event.get('elementType') or '').lower()
    tag_name_hint = (event.get('tagName') or '').lower()
    outer_html = (event.get('outerHTML') or '').lower()
    role_hint = (event.get('role') or '').lower()
    
    # Check if this is an option element (li with role="option" - GitHub Primer overlays)
    # Also detect from outerHTML if tagName/role aren't set
    is_option = (tag_name_hint == 'li' and role_hint == 'option') or \
                ('role="option"' in outer_html and '<li' in outer_html)
    
    # Try to find option elements by innerText (handles dynamic IDs in GitHub overlays)
    if inner_text and is_option:
        print(f"    Attempting to find li[role='option'] by innerText: '{inner_text}'")
        try:
            text_escaped = inner_text.replace("'", "\\'")
            xpath = f"//li[@role='option'][normalize-space(.)='{text_escaped}']"
            elements = driver.find_elements(By.XPATH, xpath)
            if elements:
                print(f"    ✓ Found option element by innerText: '{inner_text}'")
                return elements[0]
            
            # Try contains() for partial match
            xpath_contains = f"//li[@role='option'][contains(normalize-space(.), '{text_escaped}')]"
            elements = driver.find_elements(By.XPATH, xpath_contains)
            if elements:
                for elem in elements:
                    elem_text = elem.text.strip()
                    if elem_text == inner_text:
                        print(f"    ✓ Found option element by innerText (exact): '{inner_text}'")
                        return elem
                print(f"    ✓ Found option element by innerText (partial): '{inner_text}'")
                return elements[0]
        except Exception as e:
            print(f"    ✗ Could not find option by innerText '{inner_text}': {e}")
    
    # Also try to find option elements even without tagName/role hints if innerText is available
    # This is a fallback for when the event data doesn't include tagName/role
    if inner_text and not is_option:
        print(f"    Attempting to find li[role='option'] by innerText (fallback): '{inner_text}'")
        try:
            text_escaped = inner_text.replace("'", "\\'")
            xpath = f"//li[@role='option'][normalize-space(.)='{text_escaped}']"
            elements = driver.find_elements(By.XPATH, xpath)
            if elements:
                print(f"    ✓ Found option element by innerText (fallback): '{inner_text}'")
                return elements[0]
        except Exception as e:
            print(f"    ✗ Fallback option search failed: {e}")
    
    # Check if this is a button element (via tagName, elementType, or outerHTML)
    is_button = (element_type == 'button' or tag_name_hint == 'button' or 
                 outer_html.startswith('<button'))
    
    if inner_text and is_button:
        print(f"    Attempting to find button by innerText: '{inner_text}'")
        try:
            # Escape single quotes for XPath
            text_escaped = inner_text.replace("'", "\\'")
            xpath = f"//button[normalize-space(.)='{text_escaped}']"
            elements = driver.find_elements(By.XPATH, xpath)
            if elements:
                print(f"    ✓ Found button by innerText: '{inner_text}'")
                return elements[0]
            
            # Try contains() for partial match
            xpath_contains = f"//button[contains(normalize-space(.), '{text_escaped}')]"
            elements = driver.find_elements(By.XPATH, xpath_contains)
            if elements:
                # Find the one with the closest match
                for elem in elements:
                    elem_text = elem.text.strip()
                    if elem_text == inner_text:
                        print(f"    ✓ Found button by innerText (exact match): '{inner_text}'")
                        return elem
                # Return first if no exact match
                print(f"    ✓ Found button by innerText (partial match): '{inner_text}'")
                return elements[0]
        except Exception as e:
            print(f"    ✗ Could not find button by innerText '{inner_text}': {e}")
    
    # Strategy 6b: Try nearby label text (text from siblings)
    if nearby_label_text:
        try:
            element = find_element_by_nearby_text(driver, nearby_label_text, event)
            if element:
                print(f"    ✓ Found element using nearby label text: '{nearby_label_text}'")
                return element
        except Exception as e:
            print(f"    ✗ Could not find element by nearby text '{nearby_label_text}': {e}")
    
    # Strategy 7b: Try parent text context (search within parent containers)
    if parent_text_context:
        try:
            element = find_element_by_parent_context(driver, parent_text_context, event)
            if element:
                print(f"    ✓ Found element using parent context: '{parent_text_context[:50]}...'")
                return element
        except Exception as e:
            print(f"    ✗ Could not find element by parent context: {e}")
    
    # Strategy 11: Try using DOM changes to find dynamically added elements
    if previous_dom_changes:
        print(f"    Attempting to find element using DOM changes ({len(previous_dom_changes)} changes recorded)...")
        try:
            element = find_element_from_dom_changes(driver, event, previous_dom_changes)
            if element:
                print(f"    ✓ Found element using DOM change information")
                return element
        except Exception as e:
            print(f"    ✗ Could not find element using DOM changes: {e}")
    
    # # Strategy 11 (LAST RESORT): WEBSP index (tab order) if provided by the extension
    # if websp_index is not None:
    #     try:
    #         element = find_element_by_websp_index(driver, websp_index)
    #         if element is not None:
    #             print(f"    ✓ Found element using webspIndex (last resort): {websp_index}")
    #             return element
    #         else:
    #             print(f"    ✗ Could not find element by webspIndex {websp_index}: returned None")
    #     except Exception as e:
    #         print(f"    ✗ Could not find element by webspIndex {websp_index}: {e}")

    raise NoSuchElementException(
        f"Could not find element using any strategy. Event info: "
        f"id={event.get('id')}, name={event.get('name')}, labelText={event.get('labelText')}, "
        f"selector={event.get('selectorPath')}, xpath={event.get('xpath')}"
    )

def find_element_by_label_text(driver, label_text, event):
    """
    Find an input element by its associated label text.
    Tries multiple methods:
    1. Label with 'for' attribute pointing to input ID
    2. Input wrapped inside label
    3. Input adjacent to label
    """
    # Escape quotes in label text for XPath
    label_text_escaped = label_text.replace("'", "\\'")
    
    # Method 1: Find label with exact text, then find input it points to
    try:
        labels = driver.find_elements(By.TAG_NAME, 'label')
        for label in labels:
            if label.text.strip() == label_text:
                # Check if label has 'for' attribute
                for_id = label.get_attribute('for')
                if for_id:
                    try:
                        return driver.find_element(By.ID, for_id)
                    except:
                        pass
                
                # Check if input is inside label
                try:
                    input_type = event.get('type', 'checkbox')
                    inputs = label.find_elements(By.TAG_NAME, 'input')
                    for inp in inputs:
                        if inp.get_attribute('type') == input_type:
                            return inp
                except:
                    pass
    except Exception as e:
        print(f"    Label text search method 1 failed: {e}")
    
    # Method 2: Find input near text containing the label
    try:
        # Try to find elements that contain the label text
        xpath_contains = f"//label[contains(normalize-space(text()), '{label_text_escaped}')]"
        labels = driver.find_elements(By.XPATH, xpath_contains)
        for label in labels:
            # Try to find input inside or adjacent
            for_id = label.get_attribute('for')
            if for_id:
                try:
                    return driver.find_element(By.ID, for_id)
                except:
                    pass
            
            # Check inside label
            try:
                inputs = label.find_elements(By.XPATH, './/input')
                if inputs:
                    return inputs[0]
            except:
                pass
    except Exception as e:
        print(f"    Label text search method 2 failed: {e}")
    
    return None

def find_element_by_nearby_text(driver, nearby_text, event):
    """
    Find an element by searching for the nearby text in siblings or parent elements.
    
    Args:
        driver: Selenium WebDriver instance
        nearby_text: Text that appears near the target element (from sibling or parent)
        event: Event dictionary containing element information
    
    Returns:
        WebElement if found, None otherwise
    """
    if not nearby_text:
        return None
    
    # Escape quotes for XPath
    nearby_text_escaped = nearby_text.replace("'", "\\'")
    
    # Get element type from event
    element_type = event.get('elementType', 'input')
    input_type = event.get('inputType') or event.get('type')
    
    # Strategy 1: Find an element next to or near text containing the nearby text
    try:
        # Look for elements that contain this text as a sibling
        xpath = f"//*[contains(text(), '{nearby_text_escaped[:50]}')]"
        elements_with_text = driver.find_elements(By.XPATH, xpath)
        
        for text_element in elements_with_text:
            # Try to find the target element as a sibling (next or previous)
            parent = text_element.find_element(By.XPATH, '..')
            siblings = parent.find_elements(By.XPATH, f'.//{element_type}')
            for sibling in siblings:
                # Check if this sibling is the right type
                if element_type == 'input':
                    sibling_type = sibling.get_attribute('type')
                    if sibling_type == input_type:
                        return sibling
                elif element_type in ['button', 'a', 'div']:
                    return sibling
            
            # Try immediate next/prev siblings
            # This would need Selenium's special handling for sibling elements
    except Exception as e:
        print(f"    Nearby text search failed: {e}")
    
    # Strategy 2: Find elements within a parent that contains the nearby text
    try:
        # Find parents containing the text
        xpath = f"//*[contains(text(), '{nearby_text_escaped[:50]}')]//ancestor::*/descendant::{element_type}"
        elements = driver.find_elements(By.XPATH, xpath)
        
        for elem in elements:
            if element_type == 'input':
                elem_type = elem.get_attribute('type')
                if elem_type == input_type:
                    return elem
            else:
                return elem
    except Exception as e:
        print(f"    Parent text search failed: {e}")
    
    return None

def find_element_by_parent_context(driver, parent_context, event):
    """
    Find an element by searching within a parent container that has specific text context.
    
    Args:
        driver: Selenium WebDriver instance
        parent_context: Text content of a parent container (like section title, dialog name, etc.)
        event: Event dictionary containing element information
    
    Returns:
        WebElement if found, None otherwise
    """
    if not parent_context:
        return None
    
    # Get element type and attributes from event
    element_type = event.get('elementType', 'input')
    input_type = event.get('inputType') or event.get('type')
    element_id = event.get('id')
    
    # Escape quotes for XPath
    context_escaped = parent_context.replace("'", "\\'")
    # Use first 100 chars for matching
    context_match = context_escaped[:100]
    
    # Strategy 1: Find sections/modals/dialogs containing this text, then find target element within
    try:
        # Look for semantic containers (section, article, dialog, etc.)
        containers = driver.find_elements(By.XPATH, 
            f"//section[contains(., '{context_match}')] | "
            f"//article[contains(., '{context_match}')] | "
            f"//div[@role='dialog' and contains(., '{context_match}')] | "
            f"//div[@role='region' and contains(., '{context_match}')]"
        )
        
        for container in containers[:3]:  # Limit to first 3 matches
            # Look for target element within this container
            if element_id:
                try:
                    elem = container.find_element(By.ID, element_id)
                    return elem
                except:
                    pass
            
            # Look by element type
            try:
                if element_type == 'input':
                    elems = container.find_elements(By.TAG_NAME, 'input')
                    for elem in elems:
                        if input_type and elem.get_attribute('type') == input_type:
                            return elem
                    if elems:
                        return elems[0]  # Return first input found
                else:
                    elems = container.find_elements(By.TAG_NAME, element_type)
                    if elems:
                        return elems[0]
            except:
                continue
                
    except Exception as e:
        print(f"    Parent context search failed: {e}")
    
    # Strategy 2: Use selector/xpath if available, but scoped to parent context area
    try:
        selector = event.get('selectorPath')
        if selector:
            # Try to find elements matching the selector
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if elements:
                return elements[0]
    except:
        pass
    
    return None

def find_element_from_dom_changes(driver, event, dom_changes):
    """
    Try to find an element using DOM change information.
    This is useful when elements are dynamically added or modified after user interactions.
    
    Args:
        driver: Selenium WebDriver instance
        event: Event dictionary
        dom_changes: List of DOM changes from previous events
    
    Returns:
        WebElement if found, None otherwise
    """
    target_selector = event.get('selectorPath')
    target_xpath = event.get('xpath')
    target_id = event.get('id')
    target_classes = event.get('classList', [])
    
    # Look through DOM changes for added nodes that might match our target
    for change in reversed(dom_changes):  # Start with most recent changes
        if change.get('type') != 'childList':
            continue
        
        added_nodes = change.get('addedNodes', [])
        for node in added_nodes:
            node_selector = node.get('selector')
            node_id = node.get('id')
            node_classes = node.get('classes', [])
            
            # Try to match by selector
            if node_selector and target_selector:
                # Check if selectors are similar (same tag and classes)
                if node_selector == target_selector:
                    try:
                        element = driver.find_element(By.CSS_SELECTOR, node_selector)
                        print(f"Matched dynamically added node by selector: {node_selector}")
                        return element
                    except NoSuchElementException:
                        continue
            
            # Try to match by ID
            if node_id and target_id and node_id == target_id:
                try:
                    element = driver.find_element(By.ID, node_id)
                    print(f"      Matched dynamically added node by ID: {node_id}")
                    return element
                except NoSuchElementException:
                    continue
            
            # Try to match by class similarity (if they share significant classes)
            if node_classes and target_classes:
                common_classes = set(node_classes) & set(target_classes)
                if len(common_classes) >= 2:  # At least 2 common classes
                    class_selector = '.' + '.'.join(common_classes)
                    try:
                        elements = driver.find_elements(By.CSS_SELECTOR, class_selector)
                        if elements:
                            print(f"      Matched by common classes: {common_classes}")
                            return elements[0]
                    except NoSuchElementException:
                        continue
    
    return None

def process_dom_changes_before_event(event):
    """
    Process DOM changes that occurred as a result of this event.
    Wait for changes to settle if significant changes occurred.
    
    Args:
        event: Event dictionary that may contain 'domChanges' field
    
    Returns:
        List of DOM changes for this event
    """
    dom_changes = event.get('domChanges', [])
    
    if dom_changes:
        # Count significant changes
        childList_changes = sum(1 for c in dom_changes if c.get('type') == 'childList')
        attribute_changes = sum(1 for c in dom_changes if c.get('type') == 'attributes')
        
        print(f"    DOM changes detected: {len(dom_changes)} total ({childList_changes} structural, {attribute_changes} attributes)")
        
        # If significant structural changes, wait a bit longer for DOM to settle
        if childList_changes > 3:
            print(f"    Waiting for DOM to settle after significant changes...")
            time.sleep(0.5)
        
        # Log some key changes for debugging
        for change in dom_changes[:3]:  # Show first 3 changes
            change_type = change.get('type')
            if change_type == 'childList':
                added = len(change.get('addedNodes', []))
                removed = len(change.get('removedNodes', []))
                print(f"      • Element modified: +{added} nodes, -{removed} nodes at {change.get('targetSelector', 'unknown')}")
            elif change_type == 'attributes':
                print(f"      • Attribute changed: {change.get('attributeName')} on {change.get('targetSelector', 'unknown')}")
    
    return dom_changes

def is_toggle_button_pressed(element):
    """
    Check if a toggle button (like Google Ad Center +/- buttons) is in the pressed/selected state.
    
    Checks:
    - aria-pressed="true" (most common for toggle buttons)
    - aria-selected="true" (some implementations)
    - aria-label text: "See fewer" = ON, "Get more" = OFF (Google Ad Center style)
    
    Returns:
        bool: True if pressed/ON, False if not pressed/OFF
    """
    try:
        # Check aria-pressed attribute
        aria_pressed = element.get_attribute('aria-pressed')
        if aria_pressed is not None:
            print(f"    aria-pressed: {aria_pressed}")
            return aria_pressed == 'true'
    except:
        pass
    
    try:
        # Check aria-selected attribute
        aria_selected = element.get_attribute('aria-selected')
        if aria_selected is not None:
            print(f"    aria-selected: {aria_selected}")
            return aria_selected == 'true'
    except:
        pass
    
    try:
        # Check aria-label for Google Ad Center style toggles
        aria_label = element.get_attribute('aria-label') or ''
        if 'Get more ads about:' in aria_label:
            print(f"    aria-label indicates OFF: {aria_label[:50]}...")
            return False
        elif 'See fewer ads about:' in aria_label:
            print(f"    aria-label indicates ON: {aria_label[:50]}...")
            return True
    except:
        pass
    
    # Default: assume not pressed
    return False

def highlight_element(driver, element, duration=10, border_width=5):
    """
    Debug function to temporarily highlight an element with a red border.
    Useful for visually debugging which elements are being interacted with during replay.

    Args:
        driver: Selenium WebDriver instance
        element: WebElement to highlight
        duration: How long to show the highlight in seconds (default: 10)
        border_width: Width of the red border in pixels (default: 5)

    Usage:
        element = driver.find_element(By.ID, "myElement")
        highlight_element(driver, element, duration=5)
    """
    try:
        # Save original style
        original_style = element.get_attribute('style') or ''

        # Apply red border highlight
        driver.execute_script(
            f"arguments[0].setAttribute('style', arguments[1] + 'border: {border_width}px solid red !important;');",
            element,
            original_style
        )

        # Wait for the specified duration
        time.sleep(duration)

        # Restore original style
        driver.execute_script(
            "arguments[0].setAttribute('style', arguments[1]);",
            element,
            original_style
        )
    except Exception as e:
        print(f"  ⚠ Warning: Could not highlight element: {e}")

def is_element_checked_or_on(element):
    """
    Check if an element (checkbox, radio, or custom toggle) is in the ON/checked state.
    Handles various types of toggles including:
    - Google Ad Center toggle buttons with aria-pressed (aria-pressed="true" = ON) - checked FIRST
    - Google Ad Center switch buttons with role="switch" and aria-checked (aria-checked="true" = ON) - checked FIRST
    - Standard checkboxes/radio buttons (using is_selected() and checked attribute)
    - Amazon switches (checks container class: a-active=ON, a-disabled=OFF, or label text)
    - Custom toggles with aria-checked
    - Custom toggles with aria-pressed
    - Custom toggles with specific class names
    - Checkboxes where state is indicated by parent label classes (e.g., validation-success)

    Returns:
        bool: True if element is ON/checked, False if OFF/unchecked
    """
    # Check for Google Ad Center style buttons FIRST (most specific check)
    # Type 1: Buttons with aria-pressed attribute (toggle buttons)
    # Type 2: Buttons with role="switch" and aria-checked (switch buttons)
    try:
        tag_name = element.tag_name.lower()
        if tag_name == 'button':
            # Check for aria-pressed first (toggle buttons)
            aria_pressed = element.get_attribute('aria-pressed')
            if aria_pressed is not None:
                print(f"    Button with aria-pressed: {aria_pressed}")
                return aria_pressed == 'true'

            # Check for role="switch" with aria-checked (switch buttons)
            role = element.get_attribute('role')
            if role == 'switch':
                aria_checked = element.get_attribute('aria-checked')
                if aria_checked is not None:
                    print(f"    Button with role='switch' and aria-checked: {aria_checked}")
                    return aria_checked == 'true'
    except Exception as e:
        print(f"    Error checking button state: {e}")
        pass

    try:
        # For standard input elements, check the state
        tag_name = element.tag_name.lower()
        if tag_name == 'input':
            input_type = element.get_attribute('type')
            if input_type in ['checkbox', 'radio']:
                # CRITICAL: For inputs with role="switch" (like Twitch toggles),
                # aria-checked is the source of truth, NOT the native checked property.
                # React-controlled switches update aria-checked but may not sync the native property.
                role = element.get_attribute('role')
                if role == 'switch':
                    aria_checked = element.get_attribute('aria-checked')
                    if aria_checked is not None:
                        print(f"    Input[role='switch'] with aria-checked: {aria_checked}")
                        return aria_checked == 'true'
                
                # For standard checkboxes without role="switch", use get_property('checked')
                # This is more reliable than is_selected() for dynamically updated checkboxes
                is_checked = element.get_property('checked')
                if is_checked is not None:
                    print(f"    Input checked property: {is_checked}")
                    return bool(is_checked)
                
                # Fallback to is_selected()
                return element.is_selected()
    except Exception as e:
        print(f"    Error checking input element: {e}")
        pass
    
    # Amazon-style switch pattern: Check container class or label text
    # Structure: <div class="a-switch-row a-active|a-disabled"><input...><label>on|off...</label></div>
    # try:
    #     element_classes = element.get_attribute('class') or ''
    #     if 'a-switch-control' in element_classes or 'a-switch-label' in element_classes:
    #         print(f"    Detected Amazon-style switch element")

    #         # Method 1: Check parent container class (a-active = ON, a-disabled = OFF)
    #         try:
    #             container = element.find_element(By.XPATH, "ancestor::*[contains(@class, 'a-switch-row')][1]")
    #             if container:
    #                 container_classes = container.get_attribute('class') or ''
    #                 if 'a-active' in container_classes:
    #                     print(f"    Amazon switch state: ON (from container class 'a-active')")
    #                     return True
    #                 elif 'a-disabled' in container_classes:
    #                     print(f"    Amazon switch state: OFF (from container class 'a-disabled')")
    #                     return False
    #         except Exception as e:
    #             print(f"    Amazon container class check failed: {e}")

    #         # Method 2: Check label text (on/off)
    #         try:
    #             label = element.find_element(By.XPATH, "ancestor-or-self::label[1]")
    #             if label:
    #                 label_text = label.text.strip().lower()
    #                 if 'on' in label_text and 'off' not in label_text:
    #                     print(f"    Amazon switch state: ON (from label text '{label_text}')")
    #                     return True
    #                 elif 'off' in label_text:
    #                     print(f"    Amazon switch state: OFF (from label text '{label_text}')")
    #                     return False
    #         except Exception as e:
    #             print(f"    Amazon label text check failed: {e}")

    #         # Method 3: Check transform translateX value as last resort
    #         try:
    #             if element.tag_name.lower() == 'a' and 'a-switch-control' in element_classes:
    #                 style = element.get_attribute('style') or ''
    #                 # ON: translateX(15px) or other positive values
    #                 # OFF: translateX(-1px) or translateX(0px)
    #                 if 'translateX(1' in style and 'translateX(-' not in style:
    #                     print(f"    Amazon switch state: ON (from transform)")
    #                     return True
    #                 elif 'translateX(-' in style or 'translateX(0' in style:
    #                     print(f"    Amazon switch state: OFF (from transform)")
    #                     return False
    #         except Exception as e:
    #             print(f"    Amazon transform check failed: {e}")
    # except Exception as e:
    #     print(f"    Amazon switch detection failed: {e}")

    try:
        # Standard checkbox or radio button - try is_selected()
        if element.is_selected():
            return True
    except:
        pass

    try:
        # Check parent label for state indicator classes (common pattern)
        # Some sites use classes like "validation-success" on the label to indicate checked state
        parent_label = element.find_element(By.XPATH, "ancestor::label[1]")
        if parent_label:
            label_classes = parent_label.get_attribute('class') or ''
            # Check for common "checked" indicator classes on parent
            if any(keyword in label_classes.lower() for keyword in [
                'validation-success', 'is-checked', 'checked', 'selected', 'active'
            ]):
                print(f"    Parent label has checked indicator class: {label_classes}")
                return True
            # If label has no checked indicators but has validation classes, it might be unchecked
            # Only return False if we're certain (has label-container but no success class)
            if 'label-container' in label_classes and 'validation-success' not in label_classes:
                print(f"    Parent label without success class: {label_classes}")
                # Don't return False yet, check other methods first
    except:
        pass

    try:
        # Check aria-checked attribute (common in custom toggles)
        aria_checked = element.get_attribute('aria-checked')
        if aria_checked is not None:
            print(f"    aria-checked: {aria_checked}")
            if aria_checked == 'true':
                return True
            elif aria_checked == 'false':
                return False
    except:
        pass
    
    try:
        # Check aria-pressed attribute (used in some toggle buttons)
        aria_pressed = element.get_attribute('aria-pressed')
        if aria_pressed is not None:
            print(f"    aria-pressed: {aria_pressed}")
            if aria_pressed == 'true':
                return True
            elif aria_pressed == 'false':
                return False
    except:
        pass
    
    try:
        # Check aria-selected attribute (used in option elements, selectable list items)
        aria_selected = element.get_attribute('aria-selected')
        if aria_selected is not None:
            print(f"    aria-selected: {aria_selected}")
            if aria_selected == 'true':
                return True
            elif aria_selected == 'false':
                return False
    except:
        pass

    try:
        # Check child elements for aria-checked/aria-pressed/aria-selected (e.g., label wrapping input)
        children = element.find_elements(By.XPATH, ".//*[@aria-checked] | .//*[@aria-pressed] | .//*[@aria-selected] | .//input[@type='checkbox'] | .//input[@type='radio']")
        for child in children:
            # Check aria-checked on child
            aria_checked = child.get_attribute('aria-checked')
            if aria_checked is not None:
                print(f"    Child aria-checked: {aria_checked}")
                if aria_checked == 'true':
                    return True
                elif aria_checked == 'false':
                    return False
            
            # Check aria-pressed on child
            aria_pressed = child.get_attribute('aria-pressed')
            if aria_pressed is not None:
                print(f"    Child aria-pressed: {aria_pressed}")
                if aria_pressed == 'true':
                    return True
                elif aria_pressed == 'false':
                    return False
            
            # Check aria-selected on child
            aria_selected = child.get_attribute('aria-selected')
            if aria_selected is not None:
                print(f"    Child aria-selected: {aria_selected}")
                if aria_selected == 'true':
                    return True
                elif aria_selected == 'false':
                    return False

            # Check if it's a checkbox/radio input
            if child.tag_name.lower() == 'input':
                input_type = child.get_attribute('type')
                if input_type in ['checkbox', 'radio']:
                    is_checked = child.get_property('checked')
                    if is_checked is not None:
                        print(f"    Child input checked: {is_checked}")
                        return bool(is_checked)
    except:
        pass
    
    try:
        # Check data attributes that might indicate state
        data_checked = element.get_attribute('data-checked')
        if data_checked is not None:
            print(f"    data-checked: {data_checked}")
            if data_checked == 'true':
                return True
            elif data_checked == 'false':
                return False
    except:
        pass
    
    try:
        # Check for common "checked" or "active" class names on the element itself
        class_name = element.get_attribute('class') or ''
        if any(keyword in class_name.lower() for keyword in ['checked', 'active', 'selected', 'on', 'enabled']):
            print(f"    Found state keyword in class: {class_name}")
            return True
    except:
        pass
    
    # Default: assume it's unchecked/off
    return False

def force_set_switch_state(driver, element, target_state):
    """
    Force-set state for role="switch"/aria-checked/aria-pressed/aria-selected elements by updating
    the appropriate ARIA attribute and dispatching input/change events so frameworks react.

    Also handles checkboxes where state is indicated by parent label classes.
    Example: Some sites add 'validation-success' class to parent <label> when checkbox is checked.
    Pattern:
      OFF: <label class="form-field label-container">
      ON:  <label class="form-field label-container validation-success">

    For Amazon switches: Finds the actual checkbox input and updates it along with container classes.
    """
    try:
        driver.execute_script(
            """
            const el = arguments[0];
            const desired = Boolean(arguments[1]);
            if (!el) return false;
            
            // Check which attribute to update (priority order)
            if (el.hasAttribute('aria-selected')) {
                el.setAttribute('aria-selected', desired ? 'true' : 'false');
            } else if (el.hasAttribute('aria-checked')) {
                el.setAttribute('aria-checked', desired ? 'true' : 'false');
            } else if (el.hasAttribute('aria-pressed')) {
                el.setAttribute('aria-pressed', desired ? 'true' : 'false');
            let targetEl = el;
            
            // Amazon-style switch: Find the actual checkbox input if we're on the visual control
            if (el.classList && (el.classList.contains('a-switch-control') || el.classList.contains('a-switch-label'))) {
                const container = el.closest('.a-switch-row, [id*="toggle-switch"]');
                if (container) {
                    const checkbox = container.querySelector('input[type="checkbox"]');
                    if (checkbox) {
                        targetEl = checkbox;
                        
                        // Update container class (a-active = ON, a-disabled = OFF)
                        if (desired) {
                            container.classList.remove('a-disabled');
                            container.classList.add('a-active');
                        } else {
                            container.classList.remove('a-active');
                            container.classList.add('a-disabled');
                        }
                        
                        // Update label text
                        const label = container.querySelector('label');
                        if (label) {
                            const textNode = Array.from(label.childNodes).find(n => n.nodeType === Node.TEXT_NODE);
                            if (textNode) {
                                textNode.textContent = desired ? 'on' : 'off';
                            }
                        }
                        
                        console.log('Amazon switch: Found and updating checkbox input');
                    }
                }
            }
            
            // Check which attribute to update on the target element
            if (targetEl.hasAttribute('aria-checked')) {
                targetEl.setAttribute('aria-checked', desired ? 'true' : 'false');
            } else if (targetEl.hasAttribute('aria-pressed')) {
                targetEl.setAttribute('aria-pressed', desired ? 'true' : 'false');
            } else if (targetEl.type === 'checkbox' || targetEl.type === 'radio') {
                // For standard checkboxes, set the checked property
                targetEl.checked = desired;
                
                // Also update parent label classes if they indicate state
                // Some sites use CSS classes on the parent label to track checkbox state
                const parentLabel = targetEl.closest('label');
                if (parentLabel) {
                    if (desired) {
                        // Add checked indicator classes
                        if (parentLabel.classList.contains('label-container') && 
                            !parentLabel.classList.contains('validation-success')) {
                            parentLabel.classList.add('validation-success');
                        }
                        if (!parentLabel.classList.contains('checked')) {
                            parentLabel.classList.add('checked');
                        }
                    } else {
                        // Remove checked indicator classes
                        parentLabel.classList.remove('validation-success', 'checked', 'is-checked', 'selected');
                    }
                }
            } else {
                // Default to aria-checked if none exist
                targetEl.setAttribute('aria-checked', desired ? 'true' : 'false');
            }
            
            targetEl.dispatchEvent(new Event('input', { bubbles: true }));
            targetEl.dispatchEvent(new Event('change', { bubbles: true }));
            targetEl.dispatchEvent(new Event('click', { bubbles: true }));
            return true;
            """,
            element,
            bool(target_state),
        )
        return True
    except Exception as e:
        print(f"  ✗ JS force-set switch failed: {type(e).__name__}: {str(e)}")
        return False

def verify_and_enforce_state(driver, element, target_state, event, accumulated_dom_changes, max_attempts=3):
    """
    Verify that an element is in the target state and enforce it if not.
    Uses multiple verification methods and retry with force-set if needed.

    Args:
        driver: Selenium WebDriver instance
        element: The element to verify
        target_state: The desired state (True for ON/checked, False for OFF/unchecked)
        event: Event dictionary for re-finding element if needed
        accumulated_dom_changes: DOM changes for element finding
        max_attempts: Maximum number of attempts to set the state

    Returns:
        bool: True if state was verified and matches target, False otherwise
    """
    for attempt in range(max_attempts):
        try:
            current_state = is_element_checked_or_on(element)
            print(f"    State verification attempt {attempt+1}/{max_attempts}: current={'ON' if current_state else 'OFF'}, target={'ON' if target_state else 'OFF'}")

            if current_state == target_state:
                print(f"  ✓ State verified and matches target")
                return True

            # State doesn't match - try to fix it
            if attempt < max_attempts - 1:
                print(f"    State mismatch detected, attempting to correct (attempt {attempt+1}/{max_attempts})...")

                # Try clicking first
                refind = lambda: find_element_by_event(driver, event, accumulated_dom_changes)
                if click_element_with_fallback(driver, element, "state correction click", refind=refind):
                    time.sleep(0.3)
                else:
                    # Click failed, try force-set
                    print(f"    Click failed, trying force-set...")
                    if force_set_switch_state(driver, element, target_state):
                        time.sleep(0.3)
                    else:
                        print(f"    ⚠ Force-set also failed")

                # Re-check state after correction attempt
                try:
                    current_state = is_element_checked_or_on(element)
                except StaleElementReferenceException:
                    element = find_element_by_event(driver, event, accumulated_dom_changes)
                    current_state = is_element_checked_or_on(element)

                if current_state == target_state:
                    print(f"  ✓ State corrected successfully on attempt {attempt+1}")
                    return True

        except StaleElementReferenceException:
            print(f"    Element went stale during verification, re-finding...")
            try:
                element = find_element_by_event(driver, event, accumulated_dom_changes)
            except Exception as e:
                print(f"    ✗ Could not re-find element: {e}")
                return False
        except Exception as e:
            print(f"    ⚠ Error during state verification: {e}")
            if attempt == max_attempts - 1:
                return False

    print(f"  ✗ Could not verify/enforce target state after {max_attempts} attempts")
    return False

# DEPRECATED: These functions are no longer used (simplified event replay)
# Kept for reference only

# def is_toggle_sequence(events, index):
#     """
#     Check if a click event at the given index is followed by change event(s),
#     indicating a toggle/checkbox operation.
#     """
#     pass

# def get_actual_checkbox_element(driver, click_event, change_events):
#     """
#     For custom toggles, the click happens on a visual element (like a span),
#     but the actual state is on an underlying input element.
#     """
#     pass

def is_element_enabled(element):
    """
    Check if an element is enabled and clickable.
    
    Checks for:
    - disabled attribute
    - aria-disabled attribute
    - disabled/inactive classes
    - Selenium's is_enabled() method
    
    Returns: True if enabled, False if disabled
    """
    try:
        # Check Selenium's built-in is_enabled()
        if not element.is_enabled():
            return False
        
        # Check for disabled attribute
        disabled_attr = element.get_attribute('disabled')
        if disabled_attr is not None and disabled_attr != 'false':
            return False
        
        # Check for aria-disabled
        aria_disabled = element.get_attribute('aria-disabled')
        if aria_disabled and aria_disabled.lower() == 'true':
            return False
        
        # Check for common disabled classes
        class_attr = element.get_attribute('class') or ''
        disabled_classes = ['disabled', 'inactive', 'btn-disabled', 'is-disabled']
        if any(cls in class_attr.lower() for cls in disabled_classes):
            return False
        
        return True
    except Exception as e:
        print(f"  ⚠ Warning: Could not check if element is enabled: {e}")
        return True  # Default to enabled if we can't check

def click_element_with_fallback(driver, element, description="element", refind=None):
    """
    Try multiple click methods to handle stubborn elements (React Material-UI, etc.)
    
    Methods tried in order:
    1. Regular Selenium click
    2. JavaScript click
    3. ActionChains click
    
    Returns: True if click succeeded, False otherwise
    """
    # Import locally to avoid circular import
    #from utils import check_cloudflare
    
    # Try a few attempts, re-finding the element on stale references
    for attempt in range(3):
        # Method 1: Regular Selenium click
        try:
            element.click()
            print(f"  ✓ Clicked {description} (standard click)")
            return True
        except StaleElementReferenceException as e:
            print(f"  ⚠ Standard click stale: attempt {attempt+1}/3: {e}")
            if refind is not None:
                try:
                    element = refind()
                    continue
                except Exception as re:
                    print(f"✗ Re-find after stale failed: {type(re).__name__}: {str(re)}")
            # fallthrough to other methods without refind
        except Exception as e:
            print(f"  ⚠ Standard click failed: {type(e).__name__}: {str(e)}")

        # Method 2: JavaScript click
        try:
            driver.execute_script("arguments[0].click();", element)
            print(f"  ✓ Clicked {description} (JavaScript click)")
            #check_cloudflare(driver)
            return True
        except StaleElementReferenceException as e:
            print(f"  ⚠ JavaScript click stale: attempt {attempt+1}/3: {e}")
            if refind is not None:
                try:
                    element = refind()
                    continue
                except Exception as re:
                    print(f"    ✗ Re-find after stale failed: {type(re).__name__}: {str(re)}")
        except Exception as e:
            print(f"  ⚠ JavaScript click failed: {type(e).__name__}: {str(e)}")

        # Method 3: ActionChains click
        try:
            ActionChains(driver).move_to_element(element).click().perform()
            print(f"  ✓ Clicked {description} (ActionChains click)")
            #check_cloudflare(driver)
            return True
        except StaleElementReferenceException as e:
            print(f"  ⚠ ActionChains click stale: attempt {attempt+1}/3: {e}")
            if refind is not None:
                try:
                    element = refind()
                    continue
                except Exception as re:
                    print(f"    ✗ Re-find after stale failed: {type(re).__name__}: {str(re)}")
        except ElementClickInterceptedException as e:
            print(f"  ⚠ ActionChains click intercepted: {e}. Trying JS click fallback next.")
        except Exception as e:
            print(f"  ✗ ActionChains click failed: {type(e).__name__}: {str(e)}")

    print(f"  ✗ All click methods failed for {description} after retries")
    return False

def find_and_switch_to_iframe(driver, event_site):
    """
    Check if event_site is an iframe URL and switch to it if found.
    This handles cases where clicks happen inside iframes (e.g., Google Sign-In button).
    
    Args:
        driver: Selenium WebDriver instance
        event_site: URL from the event's 'site' property
    
    Returns:
        bool: True if switched to iframe, False otherwise
    """
    if not event_site:
        return False
    
    try:
        # Ensure we're at default content level before searching for iframes
        driver.switch_to.default_content()
        
        # Strategy 1: Google Sign-In iframe (most common OAuth case)
        # Look for iframe with specific title that Google uses
        try:
            google_iframes = driver.find_elements(By.CSS_SELECTOR, 
                'iframe[title="Sign in with Google Button"]')
            if google_iframes:
                # Verify the src matches (or contains) event_site domain
                for iframe in google_iframes:
                    src = iframe.get_attribute("src") or ""
                    if "accounts.google.com" in src and "gsi/button" in event_site:
                        driver.switch_to.frame(iframe)
                        print(f"  ✓ Switched to Google Sign-In iframe")
                        # Wait for iframe content to load
                        time.sleep(2)
                        print(f"  ⏳ Waited for iframe content to load")
                        return True
        except Exception as e:
            print(f"    (Google iframe check: {e})")
        
        # Strategy 2: Check all iframes for matching src URL
        try:
            all_iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in all_iframes:
                src = iframe.get_attribute("src") or ""
                if src:
                    # Check if event_site URL matches or is contained in iframe src
                    # Handle both full URLs and partial matches
                    from urllib.parse import urlparse
                    event_parsed = urlparse(event_site)
                    src_parsed = urlparse(src)
                    
                    # Match by domain and path pattern
                    if (event_parsed.netloc in src_parsed.netloc or 
                        src_parsed.netloc in event_parsed.netloc):
                        # Check if key parts of the URL match
                        if ("gsi/button" in event_site and "gsi/button" in src) or \
                           (event_parsed.path in src_parsed.path):
                            driver.switch_to.frame(iframe)
                            print(f"  ✓ Switched to iframe with matching URL")
                            print(f"     Iframe src: {src[:80]}...")
                            # Wait for iframe content to load
                            time.sleep(2)
                            print(f"  ⏳ Waited for iframe content to load")
                            return True
        except Exception as e:
            print(f"    (Iframe search failed: {e})")
                
    except Exception as e:
        print(f"  ⚠ Iframe detection error: {e}")
    
    return False

def check_and_switch_to_popup(driver, expected_domain):
    """
    Check for popup windows matching the expected domain and switch to it.
    
    Args:
        driver: Selenium WebDriver instance
        expected_domain: Domain to look for (e.g., 'accounts.google.com')
    
    Returns:
        bool: True if switched to popup, False otherwise
    """
    try:
        all_windows = driver.window_handles
        if len(all_windows) > 1:
            from urllib.parse import urlparse
            original_window = driver.current_window_handle
            
            for window in all_windows:
                if window != original_window:
                    driver.switch_to.window(window)
                    try:
                        window_url = driver.current_url
                        window_domain = urlparse(window_url).netloc
                        
                        if expected_domain in window_domain or window_domain in expected_domain:
                            print(f"  ✓ Switched to popup window: {window_domain}")
                            return True
                    except Exception:
                        continue
            
            # No matching popup found, switch back to original
            driver.switch_to.window(original_window)
        
        return False
    except Exception as e:
        print(f"  ⚠ Popup check failed: {e}")
        return False

def replay_events(driver, events, set_checked_state=None, skip_disabled_clicks=False, refresh_before_start=True, random_delay_range=(0.5, 1.5)):
    """
    Replay events from the JSON file
    
    Args:
        driver: Selenium WebDriver instance
        events: List of event dictionaries
        set_checked_state: If True, set checkboxes to checked; if False, set to unchecked; if None, use recorded state
        skip_disabled_clicks: If True, skip clicking on disabled buttons/elements
        refresh_before_start: Refresh the page before processing events
        random_delay_range: Tuple of (min, max) seconds for random delay between events (default: 0.5 to 1.5 seconds)
    """
    # Track accumulated DOM changes from all previous events
    accumulated_dom_changes = []
    if refresh_before_start:
        driver.refresh()
        time.sleep(3)

    for i, event in enumerate(events):
        # Add random delay before processing each event (skip for first event)
        if i > 0:
            delay = random.uniform(random_delay_range[0], random_delay_range[1])
            print(f"  ⏳ Random delay: {delay:.2f}s")
            time.sleep(delay)
        
        event_type = event.get('type')
        print(f"Processing event {i+1}/{len(events)}: {event_type}")
        
        # Skip informational events early (before frame switching)
        if event_type in ['dom-snapshot', 'initial-screenshot', 'final-screenshot', 'scroll-start']:
            print(f"  → Skipped {event_type}")
            continue
        
        # Check if event occurred in an iframe or popup (before standard frame switching)
        event_site = event.get('site', '')
        was_in_iframe = False
        
        if event_site and event_type in ['click', 'change', 'keydown']:
            # Check if this event's site URL is actually an iframe
            if find_and_switch_to_iframe(driver, event_site):
                was_in_iframe = True
                print(f"  → Event occurred in iframe, switched to iframe context")
            else:
                # Not an iframe - check if we need to switch to a popup
                from urllib.parse import urlparse
                try:
                    current_url = driver.current_url
                    current_domain = urlparse(current_url).netloc
                    event_domain = urlparse(event_site).netloc
                    
                    # If domains don't match, check for popups
                    if current_domain != event_domain:
                        oauth_domains = ['accounts.google.com', 'login.microsoftonline.com']
                        if any(domain in event_domain for domain in oauth_domains):
                            # Wait a bit for popup to open (if it's opening)
                            time.sleep(1.5)
                            if check_and_switch_to_popup(driver, event_domain):
                                print(f"  → Switched to popup window for OAuth flow")
                                # Wait a bit more for popup content to load
                                time.sleep(1)
                                # Clear DOM changes since we're in new context
                                accumulated_dom_changes = []
                except Exception as e:
                    print(f"  ⚠ Context check failed: {e}")
        
        # Switch to correct frame for actionable events only
        # BUT: Skip if we already switched to an iframe (to avoid switching out of it)
        if not was_in_iframe:
            switch_to_frame_path(driver, event.get('framePath', []))
        else:
            print(f"  → Skipping framePath switch (already in iframe context)")
        
        try:
            if event_type == 'click':
                # Check if this is a Google Ad Center style button
                # Type 1: Toggle buttons with aria-pressed ("Get more ads about:" / "See fewer ads about:")
                # Type 2: Switch buttons with role="switch" and aria-checked ("Limit ads about:")
                aria_label = event.get('ariaLabel') or ''
                is_google_ad_toggle = 'ads about:' in aria_label and ('Get more' in aria_label or 'See fewer' in aria_label)
                is_google_ad_switch = 'ads about:' in aria_label and ('Limit' in aria_label or 'Allow' in aria_label)
                is_google_ad_button = is_google_ad_toggle or is_google_ad_switch
                
                # Debug: Show current context
                if was_in_iframe:
                    try:
                        # Try to get current URL to verify we're in iframe
                        current_url = driver.current_url
                        print(f"  → Current context: iframe (URL: {current_url[:80]}...)")
                    except:
                        print(f"  → Current context: iframe (cannot get URL)")
                
                # Process click events - find element first
                element = find_element_by_event(driver, event, accumulated_dom_changes)
                # Try to scroll into view; if element went stale, re-find and retry once
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center', behavior:'instant'})", element)
                except StaleElementReferenceException:
                    element = find_element_by_event(driver, event, accumulated_dom_changes)
                    driver.execute_script("arguments[0].scrollIntoView({block:'center', behavior:'instant'})", element)
                time.sleep(0.3)

                # Verify textContent if available in recording
                # EXCEPTION: Skip verification for overlay trigger buttons (aria-haspopup="dialog" or "true")
                # because their text shows currently selected options which changes based on state
                expected_text = event.get('textContent')
                is_overlay_trigger = False
                try:
                    aria_haspopup = element.get_attribute('aria-haspopup')
                    is_overlay_trigger = (aria_haspopup == 'dialog' or aria_haspopup == 'true')
                except:
                    pass
                
                if expected_text is not None and not is_overlay_trigger:
                    try:
                        # Get actual text and normalize both
                        actual_text_raw = element.get_attribute('textContent') or ''

                        # Normalize: strip and collapse whitespace
                        normalized_expected = ' '.join(expected_text.split())
                        normalized_actual = ' '.join(actual_text_raw.split())

                        if normalized_expected != normalized_actual:
                            print(f"  → Skipped: Text mismatch.")
                            print(f"      Expected: '{normalized_expected[:100]}...'")
                            print(f"      Actual:   '{normalized_actual[:100]}...'")
                            time.sleep(0.5)
                            continue
                    except Exception as e:
                        print(f"    ⚠ Warning: Could not verify text content: {e}")

                # For Google Ad Center buttons, check current state and target state
                if is_google_ad_button and set_checked_state is not None:
                    try:
                        # Determine current state based on button type
                        current_state = False
                        state_attr = None
                        state_value = None

                        if is_google_ad_toggle:
                            # Toggle buttons use aria-pressed
                            state_attr = 'aria-pressed'
                            state_value = element.get_attribute('aria-pressed')
                            if state_value is not None:
                                current_state = (state_value == 'true')
                        elif is_google_ad_switch:
                            # Switch buttons use role="switch" with aria-checked
                            role = element.get_attribute('role')
                            if role == 'switch':
                                state_attr = 'aria-checked'
                                state_value = element.get_attribute('aria-checked')
                                if state_value is not None:
                                    current_state = (state_value == 'true')
                            else:
                                # Fallback: check for aria-checked even if role is not set
                                state_attr = 'aria-checked'
                                state_value = element.get_attribute('aria-checked')
                                if state_value is not None:
                                    current_state = (state_value == 'true')

                        target_state = bool(set_checked_state)

                        button_type = "toggle" if is_google_ad_toggle else "switch"
                        print(f"  Google Ad Center {button_type} button: '{aria_label[:60]}...'")
                        if state_attr and state_value is not None:
                            print(f"    Current {state_attr}: {state_value} ({'ON' if current_state else 'OFF'})")
                        print(f"    Target state: {'ON' if target_state else 'OFF'}")

                        if current_state == target_state:
                            # Already in target state, skip
                            print(f"  → Skipped: already in target state")
                            time.sleep(0.1)
                            dom_changes = process_dom_changes_before_event(event)
                            if dom_changes:
                                accumulated_dom_changes.extend(dom_changes)
                                if len(accumulated_dom_changes) > 50:
                                    accumulated_dom_changes = accumulated_dom_changes[-50:]
                            continue
                        else:
                            # Need to toggle - click the button
                            print(f"  → Clicking to toggle from {'ON' if current_state else 'OFF'} to {'ON' if target_state else 'OFF'}")
                    except Exception as e:
                        print(f"  ⚠ Could not determine Google Ad button state: {e}")
                        # If we can't determine state, continue with normal click
                        print(f"  → Continuing with normal click")

                # Check if element is enabled (if skip_disabled_clicks is True)
                if skip_disabled_clicks:
                    if not is_element_enabled(element):
                        selector = event.get('selectorPath', event.get('xpath'))
                        tag_name = element.tag_name if hasattr(element, 'tag_name') else 'unknown'
                        print(f"  → Skipped: Element is disabled ({tag_name}: {selector[:50]}...)")
                        time.sleep(0.1)
                        continue
                
                # Don't wait for clickability - let click_element_with_fallback handle it
                # This allows JS click to work even if element isn't "clickable" by Selenium standards
                
                # Try multiple click methods
                selector = event.get('selectorPath', event.get('xpath'))
                href = event.get('href')
                
                # Store original element for clicking (we'll check state on parent if needed)
                click_element = element
                state_check_element = element

                # If this is a switch-like control and state_mode is set, click only if needed
                is_switch_like = False
                try:
                    role_attr = (element.get_attribute('role') or '').lower()
                    aria_checked_attr = element.get_attribute('aria-checked')
                    aria_pressed_attr = element.get_attribute('aria-pressed')
                    aria_selected_attr = element.get_attribute('aria-selected')
                    class_attr = element.get_attribute('class') or ''

                    # Check for switch role, aria-checked, aria-pressed, or aria-selected attributes
                    # Also explicitly check for option, menuitemradio and menuitemcheckbox roles
                    is_switch_like = (role_attr == 'switch') or (role_attr == 'option') or (role_attr == 'menuitemradio') or (role_attr == 'menuitemcheckbox') or (role_attr == 'checkbox') or (aria_checked_attr is not None) or (aria_pressed_attr is not None) or (aria_selected_attr is not None)

                    # Also check if it's a standard checkbox/radio
                    # Also check if it's a standard checkbox (NOT radio - radio buttons should always be clicked)
                    if not is_switch_like:
                        tag_name = element.tag_name.lower()
                        type_attr = (element.get_attribute('type') or '').lower()
                        is_switch_like = (tag_name == 'input' and type_attr == 'checkbox')
                    
                    # Amazon-style switches: <a class="a-switch-control"> or <label class="a-switch-label">
                    # State is on the ancestor <div class="a-switch-row a-active|a-disabled">
                    if not is_switch_like:
                        if 'a-switch-control' in class_attr or 'a-switch-label' in class_attr:
                            is_switch_like = True
                            print(f"    Detected Amazon switch element (classes: {class_attr})")
                            try:
                                container = element.find_element(By.XPATH, "ancestor::*[contains(@class, 'a-switch-row')][1]")
                                if container:
                                    state_check_element = container
                                    print(f"    Using a-switch-row container for state check")
                            except Exception:
                                pass

                    # Check child elements for aria-checked/aria-pressed/aria-selected or checkbox/radio (e.g., label wrapping input)
                    if not is_switch_like:
                        try:
                            children = element.find_elements(By.XPATH, ".//input[@type='checkbox'] | .//input[@type='radio'] | .//*[@aria-checked] | .//*[@aria-pressed] | .//*[@aria-selected]")
                            if children:
                                is_switch_like = True
                                print(f"    Detected switch-like element via child elements")
                        except Exception:
                            pass
                    
                    # Also check parent elements for aria-selected/aria-checked (handles clicks on child divs inside <li role="option"> or <li role="menuitemradio">)
                    # Use parent for state checking, but keep original element for clicking
                    if not is_switch_like:
                        try:
                            parent = element.find_element(By.XPATH, "..")
                            if parent:
                                parent_role = (parent.get_attribute('role') or '').lower()
                                parent_aria_selected = parent.get_attribute('aria-selected')
                                parent_aria_checked = parent.get_attribute('aria-checked')
                                # Check for option, menuitemradio, menuitemcheckbox roles or aria-selected/aria-checked attributes
                                if (parent_role == 'option' or parent_role == 'menuitemradio' or parent_role == 'menuitemcheckbox' or
                                    parent_aria_selected is not None or parent_aria_checked is not None):
                                    is_switch_like = True
                                    print(f"    Detected switch-like element via parent (role={parent_role}, aria-selected={parent_aria_selected}, aria-checked={parent_aria_checked})")
                                    # Use parent for state checking, but click on original element
                                    state_check_element = parent
                        except Exception:
                            pass

                    # Debug output
                    if is_switch_like:
                        if role_attr == 'switch':
                            print(f"    Detected switch-like element:")
                        print(f"    Detected switch-like element:")
                        if role_attr in ['switch', 'option', 'menuitemradio', 'menuitemcheckbox']:
                            print(f"      role='{role_attr}'")
                        if aria_checked_attr is not None:
                            print(f"      aria-checked='{aria_checked_attr}'")
                        if aria_pressed_attr is not None:
                            print(f"      aria-pressed='{aria_pressed_attr}'")
                        if aria_selected_attr is not None:
                            print(f"      aria-selected='{aria_selected_attr}'")
                except Exception:
                    pass
                if is_switch_like and set_checked_state is not None:
                    try:
                        current_state = is_element_checked_or_on(state_check_element)
                        print(f"    Switch-like current state: {'ON' if current_state else 'OFF'}")
                        target_state = bool(set_checked_state)
                        if current_state == target_state:
                            print("  → Skipped click: already in target state for switch-like element")
                            time.sleep(0.1)
                            dom_changes = process_dom_changes_before_event(event)
                            if dom_changes:
                                accumulated_dom_changes.extend(dom_changes)
                                if len(accumulated_dom_changes) > 50:
                                    accumulated_dom_changes = accumulated_dom_changes[-50:]
                            continue
                    except Exception:
                        pass

                refind = lambda: find_element_by_event(driver, event, accumulated_dom_changes)
                if click_element_with_fallback(driver, click_element, selector, refind=refind):
                    # *** CRITICAL: If we clicked in an iframe, switch back and check for popups ***
                    if was_in_iframe:
                        try:
                            driver.switch_to.default_content()
                            print(f"  → Switched back to default content after iframe click")
                            
                            # Wait for popup to open (OAuth flows open popups after iframe button clicks)
                            time.sleep(10)
                            
                            # Check for popups that opened after clicking iframe button
                            if event_site:
                                from urllib.parse import urlparse
                                event_domain = urlparse(event_site).netloc
                                if check_and_switch_to_popup(driver, event_domain):
                                    print(f"  ✓ Switched to popup window that opened after iframe click")
                                    # Clear DOM changes since we're in a new context
                                    accumulated_dom_changes = []
                        except Exception as iframe_error:
                            print(f"  ⚠ Error handling iframe context: {iframe_error}")
                    
                    # Wait longer after navigation clicks that trigger React page loads
                    if href and href != '#':
                        print(f"  → Navigation click to: {href}")
                        print(f"  → Waiting for React SPA content to load...")
                        time.sleep(2.0)  # Wait for React to initialize and render
                        
                        # Verify we ended up at the right URL (or close to it for SPAs)
                        current_url = driver.current_url
                        if href not in current_url and not current_url.endswith(href.split('/')[-2] + '/'):
                            print(f"  ⚠ Warning: Expected URL containing '{href}', but got: {current_url}")
                        else:
                            print(f"  ✓ Verified navigation to correct page")
                    else:
                        time.sleep(0.5)
                    
                    # Process DOM changes that occurred due to this click
                    dom_changes = process_dom_changes_before_event(event)
                    if dom_changes:
                        accumulated_dom_changes.extend(dom_changes)
                        # Keep only last 50 changes to avoid memory bloat
                        if len(accumulated_dom_changes) > 50:
                            accumulated_dom_changes = accumulated_dom_changes[-50:]
                else:
                    print(f"  ✗ Failed to click element: {selector}")
                    if is_switch_like and set_checked_state is not None:
                        print("  → Attempting JS force-set for switch-like element")
                        # Use state_check_element for force-set (might be parent with aria-selected)
                        if force_set_switch_state(driver, state_check_element, bool(set_checked_state)):
                            time.sleep(0.3)
                            try:
                                new_state = is_element_checked_or_on(state_check_element)
                                if new_state == bool(set_checked_state):
                                    print("  ✓ Forced set via JS (switch-like) succeeded")
                                else:
                                    print("  ✗ Forced set via JS did not reach desired state")
                            except Exception:
                                pass
                    time.sleep(0.5)
                
            elif event_type == 'change':
                # Handle change events (checkboxes, toggles, text inputs)
                
                # Check if this is a checkbox/toggle change with 'checked' field
                if 'checked' in event:
                    # Small wait to let DOM settle from previous interactions (important for Google Ad Center buttons)
                    time.sleep(1)

                    # This is a checkbox/toggle
                    element = find_element_by_event(driver, event, accumulated_dom_changes)
                    try:
                        driver.execute_script("arguments[0].scrollIntoView({block:'center', behavior:'instant'})", element)
                    except StaleElementReferenceException:
                        element = find_element_by_event(driver, event, accumulated_dom_changes)
                        driver.execute_script("arguments[0].scrollIntoView({block:'center', behavior:'instant'})", element)
                    time.sleep(0.2)
                    
                    # Radio buttons should always be clicked regardless of state_mode
                    is_radio = False
                    try:
                        is_radio = (element.tag_name.lower() == 'input' and 
                                    (element.get_attribute('type') or '').lower() == 'radio')
                    except Exception:
                        pass
                    
                    if is_radio:
                        print(f"    Radio button detected — clicking unconditionally (ignoring state_mode)")
                        selector = event.get('selectorPath', event.get('xpath'))
                        refind = lambda: find_element_by_event(driver, event, accumulated_dom_changes)
                        if click_element_with_fallback(driver, element, f"radio {selector}", refind=refind):
                            time.sleep(0.5)
                            dom_changes = process_dom_changes_before_event(event)
                            if dom_changes:
                                accumulated_dom_changes.extend(dom_changes)
                                if len(accumulated_dom_changes) > 50:
                                    accumulated_dom_changes = accumulated_dom_changes[-50:]
                        else:
                            print(f"  ✗ Failed to click radio button: {selector}")
                        continue
                    
                    # Get current state
                    current_state = is_element_checked_or_on(element)
                    print(f"    Current state: {'ON' if current_state else 'OFF'}")
                    
                    # Determine target state
                    if set_checked_state is None:
                        # Use recorded state
                        target_state = event.get('checked', True)
                    else:
                        # Use forced state (ON or OFF mode)
                        target_state = set_checked_state
                    
                    print(f"Target state: {'ON' if target_state else 'OFF'}")
                    
                    # Only click if state needs to change
                    if current_state != target_state:
                        try:
                            # Don't wait for clickability here - let click_element_with_fallback handle it
                            # This allows JS click to work even if element isn't "clickable" by Selenium standards
                            
                            # Try multiple click methods
                            selector = event.get('selectorPath', event.get('xpath'))
                            refind = lambda: find_element_by_event(driver, event, accumulated_dom_changes)
                            if click_element_with_fallback(driver, element, f"checkbox/toggle {selector}", refind=refind):
                                # Wait for DOM to settle after toggle (especially important for Google Ad Center buttons)
                                time.sleep(1)
                                
                                # Verify and enforce target state (with retry logic)
                                try:
                                    element = find_element_by_event(driver, event, accumulated_dom_changes)
                                except StaleElementReferenceException:
                                    pass

                                if verify_and_enforce_state(driver, element, target_state, event, accumulated_dom_changes):
                                    print(f"  ✓ Toggled from {'ON' if current_state else 'OFF'} to {'ON' if target_state else 'OFF'}")
                                    
                                    # Process DOM changes that occurred due to this toggle
                                    dom_changes = process_dom_changes_before_event(event)
                                    if dom_changes:
                                        accumulated_dom_changes.extend(dom_changes)
                                        if len(accumulated_dom_changes) > 50:
                                            accumulated_dom_changes = accumulated_dom_changes[-50:]
                                else:
                                    print(f"  ⚠ Could not verify/enforce target state after multiple attempts")
                            else:
                                print(f"  ✗ Failed to click toggle element, trying force-set...")
                                # Click failed completely, try force-set as last resort
                                if force_set_switch_state(driver, element, target_state):
                                    time.sleep(0.3)
                                    if verify_and_enforce_state(driver, element, target_state, event, accumulated_dom_changes, max_attempts=1):
                                        print(f"  ✓ Force-set succeeded")

                                        # Process DOM changes
                                        dom_changes = process_dom_changes_before_event(event)
                                        if dom_changes:
                                            accumulated_dom_changes.extend(dom_changes)
                                            if len(accumulated_dom_changes) > 50:
                                                accumulated_dom_changes = accumulated_dom_changes[-50:]
                                    else:
                                        print(f"  ✗ Force-set failed to achieve target state")
                        except Exception as e:
                            print(f"  ✗ Error clicking toggle: {type(e).__name__}: {str(e)}")
                            print(f"     Traceback: {traceback.format_exc()}")
                    else:
                        print(f"  → Skipped: already in target state ({'ON' if current_state else 'OFF'})")
                        time.sleep(0.1)
                
                # Handle text input
                elif 'value' in event and event['value'] is not None and event.get('value') != 'on':
                    element = find_element_by_event(driver, event, accumulated_dom_changes)
                    element.clear()
                    element.send_keys(event['value'])
                    print(f"  ✓ Set value '{event['value']}' on element: {event.get('selectorPath', event.get('xpath'))}")
                    time.sleep(0.3)
                    
                    # Process DOM changes
                    dom_changes = process_dom_changes_before_event(event)
                    if dom_changes:
                        accumulated_dom_changes.extend(dom_changes)
                        if len(accumulated_dom_changes) > 50:
                            accumulated_dom_changes = accumulated_dom_changes[-50:]
                else:
                    print(f"  → Skipped change event (no actionable data)")
                    time.sleep(0.1)
                
            elif event_type == 'keydown':
                element = find_element_by_event(driver, event, accumulated_dom_changes)
                key = event.get('key', '')
                if key:
                    element.send_keys(key)
                    print(f"  ✓ Sent key '{key}' to element: {event.get('xpath', event.get('selectorPath'))}")
                    
                    # Process DOM changes
                    dom_changes = process_dom_changes_before_event(event)
                    if dom_changes:
                        accumulated_dom_changes.extend(dom_changes)
                        if len(accumulated_dom_changes) > 50:
                            accumulated_dom_changes = accumulated_dom_changes[-50:]
                time.sleep(0.2)
                
            elif event_type == 'scroll-end':
                scroll_left = event.get('scrollLeft', 0)
                scroll_top = event.get('scrollTop', 0)
                driver.execute_script(f"window.scrollTo({scroll_left}, {scroll_top})")
                print(f"  ✓ Scrolled to ({scroll_left}, {scroll_top})")
                time.sleep(0.3)
                
            elif event_type == 'navigation':
                nav_url = event.get('url')
                if nav_url:
                    driver.get(nav_url)
                    print(f"  ✓ Navigated to: {nav_url}")
                    time.sleep(1)
                
        except Exception as e:
            print(f"  ✗ Error processing {event_type} event: {type(e).__name__}: {str(e)}")
            print(f"     Traceback: {traceback.format_exc()}")
            continue
    
    print("Extension state reset completed!")
    print("Waiting 10 seconds to observe the state...")
    time.sleep(10)
