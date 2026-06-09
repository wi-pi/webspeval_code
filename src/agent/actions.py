"""actions helpers for the WebSP-Eval replay agent (split from run_with_replay.py)."""
import platform
import time
import logging

from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

from utils import check_cloudflare


def safe_remove_element(driver_task, element):
    """Safely remove an element from DOM, checking if it still exists to avoid stale element exceptions."""
    driver_task.execute_script("""
        if (arguments[0] && arguments[0].parentNode) {
            arguments[0].parentNode.removeChild(arguments[0]);
        }
    """, element)


def exec_action_click(info, web_ele, driver_task, screenshot=None):
    # Get element coordinates and dimensions
    rect = web_ele.rect
    x = rect['x'] + rect['width'] // 2  # Center x coordinate
    y = rect['y'] + rect['height'] // 2  # Center y coordinate

    # Get viewport dimensions and device scale factor
    viewport_width = driver_task.execute_script("return window.innerWidth")
    viewport_height = driver_task.execute_script("return window.innerHeight")
    device_scale_factor = driver_task.execute_script("return window.devicePixelRatio")

    # Scale coordinates based on DPI and device scale factor
    scaled_x = int(x * device_scale_factor)
    scaled_y = int(y * device_scale_factor)

    # Create visual marking at click location
    if screenshot:
        # Add a visible marker on the webpage before clicking
        # First, temporarily reduce z-index of elements at click location to ensure marker is visible
        marker_script = f"""
        // Store original z-index values for restoration
        window.tempZIndexChanges = [];
        
        // Get elements at the click location
        var clickX = {x};
        var clickY = {y};
        var elementsAtPoint = document.elementsFromPoint(clickX, clickY);
        
        // Temporarily reduce z-index of high z-index elements
        elementsAtPoint.forEach(function(el) {{
            var computedStyle = window.getComputedStyle(el);
            var currentZIndex = computedStyle.zIndex;
            
            // If element has a high z-index, temporarily reduce it
            if (currentZIndex !== 'auto' && parseInt(currentZIndex) > 1000000) {{
                window.tempZIndexChanges.push({{
                    element: el,
                    originalZIndex: el.style.zIndex || ''
                }});
                el.style.zIndex = '1000000';
            }}
        }});
        
        // Create the marker with maximum z-index
        var marker = document.createElement('div');
        marker.style.position = 'absolute';
        marker.style.left = clickX + 'px';
        marker.style.top = clickY + 'px';
        marker.style.width = '10px';
        marker.style.height = '10px';
        marker.style.backgroundColor = 'red';
        marker.style.border = '2px solid white';
        marker.style.borderRadius = '50%';
        marker.style.zIndex = '2147483647';
        marker.style.pointerEvents = 'none';
        marker.id = 'click-marker';
        document.body.appendChild(marker);
        """
        driver_task.execute_script(marker_script)

        # Brief pause to show the marker
        time.sleep(0.5)

    # Log the click coordinates
    print(f"Clicking at coordinates: ({scaled_x}, {scaled_y}) (scaled), original: ({x}, {y})")

    driver_task.save_screenshot(screenshot)

    # Store current window handles before click
    current_handles = driver_task.window_handles
    
    # Perform the click action
    try:
        # Attempt standard click first (to trigger hover/active states)
        web_ele.click()
        print("Clicked on the element using normal selenium click")
    except Exception as e:
        # Fallback to JS click 
        try:
           driver_task.execute_script("arguments[0].click();", web_ele)
           print("Clicked on the element using JavaScript click") 
        except Exception:
            # Fallback to ActionChains click
            ActionChains(driver_task).move_to_element(web_ele).click().perform()
            print("Clicked on the element using ActionChains click")
    
    
    # Check if new tab/window was opened
    new_handles = driver_task.window_handles
    if len(new_handles) > len(current_handles):
        # New tab opened - switch to it
        new_handle = [h for h in new_handles if h not in current_handles][0]
        driver_task.switch_to.window(new_handle)
        logging.info("Switched to new tab/window")

    # Remove the marker and restore original z-index values after clicking
    if screenshot:
        try:
            restore_script = """
            // Remove the marker
            var marker = document.getElementById('click-marker');
            if (marker) {
                marker.remove();
            }
            
            // Restore original z-index values
            if (window.tempZIndexChanges) {
                window.tempZIndexChanges.forEach(function(change) {
                    if (change.element) {
                        change.element.style.zIndex = change.originalZIndex;
                    }
                });
                delete window.tempZIndexChanges;
            }
            """
            driver_task.execute_script(restore_script)
        except:
            pass  # Marker may not exist or page may have changed

    time.sleep(3)


def exec_action_hover(info, web_ele, driver_task, screenshot=None):
    """Execute a hover action on a web element.
    
    Args:
        info: Action information (not used for hover, but kept for API consistency)
        web_ele: The web element to hover over
        driver_task: The Selenium WebDriver instance
        screenshot: Path to save screenshot of hover location (optional)
    """
    # Get element coordinates and dimensions
    rect = web_ele.rect
    x = rect['x'] + rect['width'] // 2  # Center x coordinate
    y = rect['y'] + rect['height'] // 2  # Center y coordinate

    # Get viewport dimensions and device scale factor
    viewport_width = driver_task.execute_script("return window.innerWidth")
    viewport_height = driver_task.execute_script("return window.innerHeight")
    device_scale_factor = driver_task.execute_script("return window.devicePixelRatio")

    # Scale coordinates based on DPI and device scale factor
    scaled_x = int(x * device_scale_factor)
    scaled_y = int(y * device_scale_factor)

    # Create visual marking at hover location
    if screenshot:
        # Add a visible marker on the webpage before hovering
        marker_script = f"""
        // Store original z-index values for restoration
        window.tempZIndexChanges = [];
        
        // Get elements at the hover location
        var hoverX = {x};
        var hoverY = {y};
        var elementsAtPoint = document.elementsFromPoint(hoverX, hoverY);
        
        // Temporarily reduce z-index of high z-index elements
        elementsAtPoint.forEach(function(el) {{
            var computedStyle = window.getComputedStyle(el);
            var currentZIndex = computedStyle.zIndex;
            
            // If element has a high z-index, temporarily reduce it
            if (currentZIndex !== 'auto' && parseInt(currentZIndex) > 1000000) {{
                window.tempZIndexChanges.push({{
                    element: el,
                    originalZIndex: el.style.zIndex || ''
                }});
                el.style.zIndex = '1000000';
            }}
        }});
        
        // Create the marker with maximum z-index (blue for hover to differentiate from click)
        var marker = document.createElement('div');
        marker.style.position = 'absolute';
        marker.style.left = hoverX + 'px';
        marker.style.top = hoverY + 'px';
        marker.style.width = '10px';
        marker.style.height = '10px';
        marker.style.backgroundColor = 'blue';
        marker.style.border = '2px solid white';
        marker.style.borderRadius = '50%';
        marker.style.zIndex = '2147483647';
        marker.style.pointerEvents = 'none';
        marker.id = 'hover-marker';
        document.body.appendChild(marker);
        """
        driver_task.execute_script(marker_script)

        # Brief pause to show the marker
        time.sleep(0.5)

    # Log the hover coordinates
    print(f"Hovering at coordinates: ({scaled_x}, {scaled_y}) (scaled), original: ({x}, {y})")

    # Perform the hover action using ActionChains
    try:
        actions = ActionChains(driver_task)
        actions.move_to_element(web_ele).pause(1).perform()
        print("Hovered on the element using ActionChains")
        logging.info(f"Hovered on element successfully")
    except Exception as e:
        logging.error(f"Error hovering on element: {e}")
        # Fallback: Try JavaScript hover simulation
        try:
            driver_task.execute_script("""
                var event = new MouseEvent('mouseover', {
                    view: window,
                    bubbles: true,
                    cancelable: true
                });
                arguments[0].dispatchEvent(event);
            """, web_ele)
            print("Hovered on the element using JavaScript mouseover event")
            logging.info(f"Hovered on element using JavaScript fallback")
        except Exception as e2:
            logging.error(f"Error hovering on element (JavaScript fallback also failed): {e2}")

    # Remove the marker before taking screenshot so it doesn't cover hover effects
    if screenshot:
        try:
            restore_script = """
            // Remove the marker
            var marker = document.getElementById('hover-marker');
            if (marker) {
                marker.remove();
            }
            
            // Restore original z-index values
            if (window.tempZIndexChanges) {
                window.tempZIndexChanges.forEach(function(change) {
                    if (change.element) {
                        change.element.style.zIndex = change.originalZIndex;
                    }
                });
                delete window.tempZIndexChanges;
            }
            """
            driver_task.execute_script(restore_script)
        except:
            pass  # Marker may not exist or page may have changed
    
    # Wait longer for hover effects (tooltips, menus, etc.) to appear AFTER marker removal
    if screenshot:
        time.sleep(3)  # Increased delay to allow tooltips/menus to fully render
        driver_task.save_screenshot(screenshot)
        print(f"Screenshot saved after hover: {screenshot}")

    time.sleep(1)


def exec_action_type(info, web_ele, driver_task, captcha_setup=False):
    warn_obs = ""
    type_content = info['content']

    ele_tag_name = web_ele.tag_name.lower()
    ele_type = web_ele.get_attribute("type")
    # outer_html = web_ele.get_attribute("outerHTML")
    if (ele_tag_name != 'input' and ele_tag_name != 'textarea') or (ele_tag_name == 'input' and ele_type not in ['text', 'search', 'password', 'email', 'tel']):
        warn_obs = f"note: The web element you're trying to type may not be a textbox, and its tag name is <{web_ele.tag_name}>, type is {ele_type}."
    try:
        # Not always work to delete
        web_ele.clear()
        # Another way to delete
        if platform.system() == 'Darwin':
            web_ele.send_keys(Keys.COMMAND + "a")
        else:
            web_ele.send_keys(Keys.CONTROL + "a")
        web_ele.send_keys(" ")
        web_ele.send_keys(Keys.BACKSPACE)
    except:
        pass

    actions = ActionChains(driver_task)
    actions.click(web_ele).perform()
    if captcha_setup:
        check_cloudflare(driver_task)
    actions.pause(1)

    try:
        driver_task.execute_script("""window.onkeydown = function(e) {if(e.keyCode == 32 && e.target.type != 'text' && e.target.type != 'textarea' && e.target.type != 'search') {e.preventDefault();}};""")
    except:
        pass

    actions.send_keys(type_content)
    actions.pause(2)

    # Enter key removed - agents must explicitly click submit buttons if needed
    logging.info(f"Typed content: '{type_content}' (Enter key NOT pressed)")
    
    actions.perform()
    time.sleep(3)
    return warn_obs


def exec_action_scroll(info, web_eles, driver_task, args, obs_info):
    scroll_ele_number = info['number']
    scroll_content = info['content']
    
    # Determine scroll amount and direction based on content
    if scroll_content == 'down':
        amount_y = args.window_height * 2 // 3
        amount_x = 0
    elif scroll_content == 'up':
        amount_y = -(args.window_height * 2 // 3)
        amount_x = 0
    elif scroll_content == 'right':
        amount_y = 0
        amount_x = args.window_width * 2 // 3
    elif scroll_content == 'left':
        amount_y = 0
        amount_x = -(args.window_width * 2 // 3)
    else:  # to_end or other
        amount_y = args.window_height * 2 // 3
        amount_x = 0
    
    # Get bbox for the element to scroll
    if scroll_ele_number == "WINDOW":
        # For window, use full viewport dimensions as bbox
        bbox = [0, 0, 1000, 1000]  # Normalized coordinates for full window
    else:
        if not args.text_only:
            scroll_ele_number = int(scroll_ele_number)
            web_ele = web_eles[scroll_ele_number]
            # Get element rect and convert to normalized coordinates (0-1000 scale)
            rect = web_ele.rect
            viewport_width = driver_task.execute_script("return window.innerWidth")
            viewport_height = driver_task.execute_script("return window.innerHeight")
            
            # Convert to normalized coordinates (0-1000 scale)
            x1 = int((rect['x'] / viewport_width) * 1000)
            y1 = int((rect['y'] / viewport_height) * 1000)
            x2 = int(((rect['x'] + rect['width']) / viewport_width) * 1000)
            y2 = int(((rect['y'] + rect['height']) / viewport_height) * 1000)
            bbox = [y1, x1, y2, x2]  # [y1, x1, y2, x2] format as expected by JS
        else:
            element_box = obs_info[scroll_ele_number]['union_bound']
            # Convert element_box to normalized coordinates if needed
            # Assuming element_box is already in the right format or pixel coordinates
            viewport_width = driver_task.execute_script("return window.innerWidth")
            viewport_height = driver_task.execute_script("return window.innerHeight")
            
            x1 = int((element_box[0] / viewport_width) * 1000)
            y1 = int((element_box[1] / viewport_height) * 1000)
            x2 = int((element_box[2] / viewport_width) * 1000)
            y2 = int((element_box[3] / viewport_height) * 1000)
            bbox = [y1, x1, y2, x2]  # [y1, x1, y2, x2] format as expected by JS
    
    # Execute the improved scrolling JavaScript that handles both horizontal and vertical scrolling
    scroll_script = f"""
try {{
    const [y1, x1, y2, x2] = {bbox};
    const amountX = {amount_x};
    const amountY = {amount_y};
    const w = window.innerWidth, h = window.innerHeight;
    const cx = ((x1 + x2) / 2 / 1000) * w;
    const cy = ((y1 + y2) / 2 / 1000) * h;

    let elems = document.elementsFromPoint(cx, cy);
    if (!elems || elems.length === 0) {{
        // If no element found, try scrolling the window as a fallback
        window.scrollBy(amountX, amountY);
        return {{ success: true, message: `Scrolled window by ${{amountX}}px horizontal, ${{amountY}}px vertical as fallback.` }};
    }}

    // Try to find the first scrollable element starting from the top
    let scrollableElement = null;
    for (let el of elems) {{
        const style = window.getComputedStyle(el);
        const hasVerticalScroll = style.overflowY === 'auto' || style.overflowY === 'scroll' || style.overflow === 'auto' || style.overflow === 'scroll';
        const hasHorizontalScroll = style.overflowX === 'auto' || style.overflowX === 'scroll' || style.overflow === 'auto' || style.overflow === 'scroll';
        
        if (hasVerticalScroll || hasHorizontalScroll || el.tagName === 'BODY' || el.tagName === 'HTML') {{
            // Check if element can actually scroll more in the desired direction
            let canScrollVertical = (amountY > 0) ? (el.scrollHeight > el.clientHeight + el.scrollTop + 1) : (el.scrollTop > 0);
            let canScrollHorizontal = (amountX > 0) ? (el.scrollWidth > el.clientWidth + el.scrollLeft + 1) : (el.scrollLeft > 0);
            
            // Special handling for body/html
            if (el.tagName === 'BODY' || el.tagName === 'HTML') {{
                let docEl = document.documentElement;
                canScrollVertical = (amountY > 0) ? (docEl.scrollHeight > docEl.clientHeight + docEl.scrollTop + 1) : (docEl.scrollTop > 0);
                canScrollHorizontal = (amountX > 0) ? (docEl.scrollWidth > docEl.clientWidth + docEl.scrollLeft + 1) : (docEl.scrollLeft > 0);
                
                if((amountY !== 0 && canScrollVertical) || (amountX !== 0 && canScrollHorizontal)) {{
                   scrollableElement = window;
                   break;
                }}
            }} else if ((amountY !== 0 && canScrollVertical) || (amountX !== 0 && canScrollHorizontal)) {{
                 scrollableElement = el;
                 break;
            }}
        }}
    }}

    if (scrollableElement) {{
        scrollableElement.scrollBy(amountX, amountY);
        return {{ success: true, message: `Scrolled element '${{scrollableElement.tagName}}' by ${{amountX}}px horizontal, ${{amountY}}px vertical.` }};
    }} else {{
        // Fallback: If no specific element is scrollable, scroll the window
        window.scrollBy(amountX, amountY);
        return {{ success: true, message: `No specific scrollable element found, scrolled window by ${{amountX}}px horizontal, ${{amountY}}px vertical.` }};
    }}
}} catch (error) {{
    console.error("Scroll script error:", error);
    try {{
        window.scrollBy({amount_x}, {amount_y});
        return {{ success: true, message: `Scrolled window by ${{amountX}}px horizontal, ${{amountY}}px vertical after error.`, error: error.toString() }};
    }} catch (finalError) {{
         return {{ success: false, message: "Error during scroll script execution.", error: finalError.toString() }};
    }}
}}
"""
    
    # Execute the scroll script
    result = driver_task.execute_script(scroll_script)
    if result:
        logging.info(f"Scroll result: {result}")
    
    time.sleep(1.5)


def exec_action_scroll_to_end(driver_task):
    """Scroll to the very end of the page using an intelligent script that handles dynamic content."""
    # Use execute_async_script with callback for proper async handling
    scroll_to_end_script = """
var callback = arguments[arguments.length - 1];
try {
    const maxAttempts = 50
    let attempts = 0;
    let lastHeight = 0;

    function autoScroll() {
        if (attempts >= maxAttempts) {
            callback({ success: true, message: 'Reached stable bottom.', totalHeight: lastHeight });
            return;
        }
        
        const currentHeight = Math.max(
            document.body.scrollHeight,
            document.documentElement.scrollHeight
        );

        window.scrollTo({ top: currentHeight, behavior: 'smooth' });

        setTimeout(function() {
            const newHeight = Math.max(
                document.body.scrollHeight,
                document.documentElement.scrollHeight
            );

            if (newHeight === lastHeight) {
                attempts++;
            } else {
                attempts = 0;
                lastHeight = newHeight;
            }
            
            autoScroll();
        }, 500);  // reduced delay (was 1000ms)
    }

    autoScroll();
} catch (error) {
    callback({ success: false, message: error.toString() });
}
"""
    
    # Execute the scroll to end script using execute_async_script for proper async handling
    try:
        result = driver_task.execute_async_script(scroll_to_end_script)
        if result:
            logging.info(f"Scroll to end result: {result}")
    except Exception as e:
        logging.warning(f"Scroll to end failed: {e}")
    
    time.sleep(2)  # Wait for any dynamic content to load


def exec_action_scroll_within_popup(info, driver_task, args):
    """
    Scroll within a detected popup/modal/overlay element.
    
    This function automatically detects visible popup elements on the page
    (modals, cookie notices, dialogs, overlays) and scrolls within them.
    
    Args:
        info: Dictionary with 'content' key containing scroll direction (up/down/left/right)
        driver_task: Selenium WebDriver instance
        args: Command line arguments (for window dimensions)
    """
    scroll_direction = info['content']
    
    # Determine scroll amount and direction based on content
    if scroll_direction == 'down':
        amount_y = args.window_height * 1 // 3
        amount_x = 0
    elif scroll_direction == 'up':
        amount_y = -(args.window_height * 1 // 3)
        amount_x = 0
    elif scroll_direction == 'right':
        amount_y = 0
        amount_x = args.window_width * 1 // 3
    elif scroll_direction == 'left':
        amount_y = 0
        amount_x = -(args.window_width * 1 // 3)
    else:
        amount_y = args.window_height * 1 // 3
        amount_x = 0
    
    # JavaScript to detect and scroll within popup/modal elements
    scroll_popup_script = f"""
try {{
    const amountX = {amount_x};
    const amountY = {amount_y};
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    
    // Helper function to check if element is visible
    function isElementVisible(el) {{
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && 
               style.visibility !== 'hidden' && 
               parseFloat(style.opacity) > 0 &&
               rect.width > 0 && 
               rect.height > 0;
    }}
    
    // Helper function to check if element is a popup/modal/overlay
    function isPopupElement(el) {{
        if (!el || !isElementVisible(el)) return false;
        
        const style = window.getComputedStyle(el);
        const tagName = el.tagName.toLowerCase();
        const role = (el.getAttribute('role') || '').toLowerCase();
        const className = (el.className || '').toString().toLowerCase();
        const id = (el.id || '').toLowerCase();
        const ariaModal = el.getAttribute('aria-modal');
        
        // Check for dialog role
        if (role === 'dialog' || role === 'alertdialog') return true;
        
        // Check for aria-modal attribute
        if (ariaModal === 'true') return true;
        
        // Check for dialog element
        if (tagName === 'dialog' && el.open) return true;
        
        // Check for common popup/modal class names
        const popupKeywords = ['modal', 'popup', 'dialog', 'overlay', 'cookie', 'consent', 
                               'banner', 'notice', 'gdpr', 'privacy', 'lightbox', 'drawer',
                               'sheet', 'alert'];
        
        for (const keyword of popupKeywords) {{
            if (className.includes(keyword) || id.includes(keyword)) {{
                return true;
            }}
        }}
        
        // Check for fixed/absolute positioned elements with high z-index covering significant area
        const position = style.position;
        const zIndex = parseInt(style.zIndex) || 0;
        const rect = el.getBoundingClientRect();
        
        if ((position === 'fixed' || position === 'absolute') && zIndex >= 100) {{
            // Check if it covers at least 10% of viewport and is reasonably sized
            const coverageRatio = (rect.width * rect.height) / (vw * vh);
            if (coverageRatio >= 0.05 && rect.width >= 200 && rect.height >= 100) {{
                return true;
            }}
        }}
        
        return false;
    }}
    
    // Helper function to find scrollable element within a container
    function findScrollableChild(container) {{
        // First check if the container itself is scrollable
        const containerStyle = window.getComputedStyle(container);
        const isContainerScrollable = 
            (containerStyle.overflowY === 'auto' || containerStyle.overflowY === 'scroll' ||
             containerStyle.overflowX === 'auto' || containerStyle.overflowX === 'scroll' ||
             containerStyle.overflow === 'auto' || containerStyle.overflow === 'scroll');
        
        if (isContainerScrollable) {{
            const canScrollVertical = container.scrollHeight > container.clientHeight;
            const canScrollHorizontal = container.scrollWidth > container.clientWidth;
            if (canScrollVertical || canScrollHorizontal) {{
                return container;
            }}
        }}
        
        // Search for scrollable children
        const children = container.querySelectorAll('*');
        for (const child of children) {{
            const style = window.getComputedStyle(child);
            const hasScroll = 
                style.overflowY === 'auto' || style.overflowY === 'scroll' ||
                style.overflowX === 'auto' || style.overflowX === 'scroll' ||
                style.overflow === 'auto' || style.overflow === 'scroll';
            
            if (hasScroll && isElementVisible(child)) {{
                const canScrollVertical = child.scrollHeight > child.clientHeight;
                const canScrollHorizontal = child.scrollWidth > child.clientWidth;
                if (canScrollVertical || canScrollHorizontal) {{
                    return child;
                }}
            }}
        }}
        
        // If no scrollable child found, return the container itself as fallback
        return container;
    }}
    
    // Collect all potential popup elements
    let popupCandidates = [];
    const allElements = document.querySelectorAll('*');
    
    for (const el of allElements) {{
        if (isPopupElement(el)) {{
            const style = window.getComputedStyle(el);
            const zIndex = parseInt(style.zIndex) || 0;
            const rect = el.getBoundingClientRect();
            popupCandidates.push({{
                element: el,
                zIndex: zIndex,
                area: rect.width * rect.height,
                rect: rect
            }});
        }}
    }}
    
    if (popupCandidates.length === 0) {{
        return {{ success: false, message: 'No popup/modal element detected on the page.' }};
    }}
    
    // Sort by z-index (highest first), then by area (largest first)
    popupCandidates.sort((a, b) => {{
        if (b.zIndex !== a.zIndex) return b.zIndex - a.zIndex;
        return b.area - a.area;
    }});
    
    // Get the topmost popup
    const topPopup = popupCandidates[0];
    const popupElement = topPopup.element;
    
    // Find scrollable element within the popup
    const scrollableElement = findScrollableChild(popupElement);
    
    if (!scrollableElement) {{
        return {{ success: false, message: 'Popup found but no scrollable content detected.' }};
    }}
    
    // Check if we can actually scroll in the desired direction
    let canScrollVertical, canScrollHorizontal;
    if (amountY > 0) {{
        canScrollVertical = scrollableElement.scrollHeight > scrollableElement.clientHeight + scrollableElement.scrollTop + 1;
    }} else if (amountY < 0) {{
        canScrollVertical = scrollableElement.scrollTop > 0;
    }} else {{
        canScrollVertical = false;
    }}
    
    if (amountX > 0) {{
        canScrollHorizontal = scrollableElement.scrollWidth > scrollableElement.clientWidth + scrollableElement.scrollLeft + 1;
    }} else if (amountX < 0) {{
        canScrollHorizontal = scrollableElement.scrollLeft > 0;
    }} else {{
        canScrollHorizontal = false;
    }}
    
    // Perform the scroll
    scrollableElement.scrollBy(amountX, amountY);
    
    const popupInfo = popupElement.className || popupElement.id || popupElement.tagName;
    const scrollInfo = scrollableElement.className || scrollableElement.tagName;
    
    return {{ 
        success: true, 
        message: `Scrolled within popup '${{popupInfo}}' (scrollable: '${{scrollInfo}}') by ${{amountX}}px horizontal, ${{amountY}}px vertical.`,
        popupFound: true,
        couldScroll: canScrollVertical || canScrollHorizontal
    }};
    
}} catch (error) {{
    console.error("Scroll within popup error:", error);
    return {{ success: false, message: "Error during scroll within popup: " + error.toString() }};
}}
"""
    
    # Execute the scroll script
    result = driver_task.execute_script(scroll_popup_script)
    if result:
        logging.info(f"Scroll within popup result: {result}")
        if not result.get('success'):
            logging.warning(f"Scroll within popup warning: {result.get('message')}")
    
    time.sleep(1.5)


def get_tabs_info(driver_task):
    """Get information about all open tabs."""
    tabs_info = {}
    current_handle = driver_task.current_window_handle
    
    for handle in driver_task.window_handles:
        driver_task.switch_to.window(handle)
        try:
            title = driver_task.title
            url = driver_task.current_url
            tabs_info[handle] = {
                'title': title,
                'url': url,
                'is_current': handle == current_handle
            }
        except Exception as e:
            logging.warning(f"Could not get info for tab {handle}: {e}")
            tabs_info[handle] = {
                'title': 'Unknown',
                'url': 'Unknown',
                'is_current': handle == current_handle
            }
    
    # Switch back to current tab
    driver_task.switch_to.window(current_handle)
    return tabs_info


def switch_to_latest_tab(driver_task, previous_handles):
    """Switch to the most recently opened tab."""
    current_handles = driver_task.window_handles
    new_handles = [h for h in current_handles if h not in previous_handles]
    
    if new_handles:
        # Switch to the newest tab (last in the list)
        latest_tab = new_handles[-1]
        driver_task.switch_to.window(latest_tab)
        logging.info(f"Switched to new tab: {latest_tab}")
        return True
    return False


def switch_to_tab_by_url(driver_task, target_url):
    """Switch to a tab based on URL.
    
    Handles URL matching flexibly to account for:
    - Redirects (e.g., stackoverflow.com -> stackoverflow.com/questions)
    - www variations (e.g., www.github.com -> github.com)
    - Trailing slashes
    - Query parameters and fragments
    """
    from urllib.parse import urlparse
    
    # Parse target URL
    target_parsed = urlparse(target_url)
    target_domain = target_parsed.netloc.lower().replace('www.', '')
    target_path = target_parsed.path.rstrip('/')
    
    for handle in driver_task.window_handles:
        driver_task.switch_to.window(handle)
        current_url = driver_task.current_url
        
        # Try exact match first
        if current_url == target_url:
            logging.info(f"Switched to tab with URL (exact match): {target_url}")
            return True
        
        # Try flexible matching
        current_parsed = urlparse(current_url)
        current_domain = current_parsed.netloc.lower().replace('www.', '')
        current_path = current_parsed.path.rstrip('/')
        
        # Match if domain matches and path starts with target path (or vice versa)
        if current_domain == target_domain:
            # If target path is empty or root, match any path on same domain
            if not target_path or target_path == '/':
                logging.info(f"Switched to tab with URL (domain match): {target_url} -> {current_url}")
                return True
            # If target path matches beginning of current path (handles redirects like / -> /questions)
            elif current_path.startswith(target_path) or target_path.startswith(current_path):
                logging.info(f"Switched to tab with URL (path prefix match): {target_url} -> {current_url}")
                return True
    
    logging.warning(f"Could not find tab with URL: {target_url}")
    return False
