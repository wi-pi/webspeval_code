import base64
import re
import os
import json
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
import logging
import numpy as np
import requests
import socket
from PIL import Image
from state_reset.RecaptchaSolver import RecaptchaSolver
from utils_webarena import fetch_browser_info, fetch_page_accessibility_tree,\
                    parse_accessibility_tree, clean_accesibility_tree


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

    # 2. Check for the "g-recaptcha" class
    # Standard class for the widget container
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


def resize_image(image_path):
    image = Image.open(image_path)
    width, height = image.size

    if min(width, height) < 512:
        return image
    elif width < height:
        new_width = 512
        new_height = int(height * (new_width / width))
    else:
        new_height = 512
        new_width = int(width * (new_height / height))

    resized_image = image.resize((new_width, new_height), Image.LANCZOS)
    resized_image.save(image_path)
    # return resized_image


# base64 encoding
# Code from OpenAI Document
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


# interact with webpage and add rectangles on elements
def get_web_element_rect(browser, fix_color=False):
    time.sleep(2)
    if fix_color:
        selected_function = "getFixedColor"
    else:
        selected_function = "getRandomColor"

    js_script = """
        let labels = [];

        // 1. HELPER: Generate High-Contrast Colors
        function getRandomColor(index) {
            // Use HSL for distinct, bright colors (avoiding darks/blacks)
            let hue = (index * 137.5) % 360;
            return `hsl(${hue}, 80%, 40%)`;
        }

        function getFixedColor(index) {
            var color = '#000000';
            return color;
        }

        function markPage() {
            // A. CLEANUP: Remove existing markers to prevent interference
            document.querySelectorAll("div[data-ai-marker]").forEach(el => el.remove());

            const vw = Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0);
            const vh = Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0);

            // B. COLLECT: Get all elements (including Shadow DOM)
            function getAllElements(root, collected = []) {
                const elements = root.querySelectorAll('*');
                for (const element of elements) {
                    collected.push(element);
                    if (element.shadowRoot) {
                        getAllElements(element.shadowRoot, collected);
                    }

                }
                return collected;
            }
            const allElements = getAllElements(document);

            // C. FILTER: Identify Interactive & Visible Elements
            let items = allElements.map(element => {
                let rawRects = [...element.getClientRects()];

                // For semantic interactive elements with collapsed rects (width/height ~0),
                // compute a bounding rect from their children instead.
                const tagUpper = element.tagName.toUpperCase();
                if (['BUTTON', 'A', 'INPUT', 'SELECT', 'TEXTAREA'].includes(tagUpper) && rawRects.length > 0) {
                    const r = rawRects[0];
                    if (r.width < 3 || r.height < 3) {
                        const childBB = element.getBoundingClientRect();
                        if (childBB.width >= 3 && childBB.height >= 3) {
                            rawRects = [childBB];
                        } else {
                            // Try computing union of all child rects
                            let minL = Infinity, minT = Infinity, maxR = -Infinity, maxB = -Infinity;
                            element.querySelectorAll('*').forEach(child => {
                                const cr = child.getBoundingClientRect();
                                if (cr.width > 0 && cr.height > 0) {
                                    minL = Math.min(minL, cr.left);
                                    minT = Math.min(minT, cr.top);
                                    maxR = Math.max(maxR, cr.right);
                                    maxB = Math.max(maxB, cr.bottom);
                                }
                            });
                            if (maxR > minL && maxB > minT) {
                                rawRects = [{left: minL, top: minT, right: maxR, bottom: maxB,
                                             width: maxR - minL, height: maxB - minT}];
                            }
                        }
                    }
                }

                const rects = rawRects.filter(bb => {
                    // 1. Basic Dimensions Check
                    if (bb.width < 3 || bb.height < 3) return false;
                    if (bb.left > vw || bb.top > vh || bb.right < 0 || bb.bottom < 0) return false;

                    // 1.5. Skip invisible elements (except for switch/checkbox inputs which are often hidden)
                    const elemStyle = window.getComputedStyle(element);
                    const role = (element.getAttribute('role') || '').toLowerCase();
                    const tagName = element.tagName.toUpperCase();
                    const type = (element.getAttribute('type') || '').toLowerCase();
                    const isHiddenInteractiveInput = tagName === 'INPUT' && (['switch', 'checkbox'].includes(role) || ['checkbox', 'radio'].includes(type));

                    if (!isHiddenInteractiveInput && (elemStyle.opacity === '0' || elemStyle.visibility === 'hidden')) {
                        return false;
                    }

                    // 2. ROBUST VISIBILITY: Check Center AND Corners
                    // This fixes the "Dropdown" issue where the center might be transparent/covered
                    // Skip visibility test for semantic interactive elements
                    if (['BUTTON', 'A', 'INPUT', 'TEXTAREA', 'SELECT'].includes(tagName)) {
                        return true;  // Skip only the elementFromPoint test, not viewport check
                    }

                    const points = [
                        {x: bb.left + bb.width / 2, y: bb.top + bb.height / 2}, // Center
                        {x: bb.left + 5, y: bb.top + 5},                        // Top-Left
                        {x: bb.right - 5, y: bb.bottom - 5}                     // Bottom-Right
                    ];

                    return points.some(p => {
                        // Skip if point is outside viewport
                        if (p.x < 0 || p.x > vw || p.y < 0 || p.y > vh) return false;

                        let elAtPoint = document.elementFromPoint(p.x, p.y);
                        if (!elAtPoint) return false;

                        // Hit Test: Is it the element, a child, or inside the same Shadow DOM?
                        return elAtPoint === element ||
                               element.contains(elAtPoint) ||
                               (elAtPoint.shadowRoot && elAtPoint.shadowRoot.contains(element));
                    });
                }).map(bb => ({
                    left: Math.max(0, bb.left),
                    top: Math.max(0, bb.top),
                    width: bb.width,
                    height: bb.height
                }));

                if (rects.length === 0) return { include: false };

                // 3. INTERACTIVITY CHECK
                const tagName = element.tagName.toUpperCase();
                const role = (element.getAttribute('role') || '').toLowerCase();
                const style = window.getComputedStyle(element);

                // Heuristic: Is it clickable?
                const textContent = (element.textContent || "").trim().toLowerCase();
                const hasButtonText = /^(confirm|submit|accept|continue|save|apply|ok|close|cancel|reject|deny|on|off)/i.test(textContent);

                const isInteractive =
                    (tagName === "A" || tagName === "BUTTON" || tagName === "INPUT" || tagName === "TEXTAREA" || tagName === "SELECT" || tagName.startsWith("CR-")) ||
                    (style.cursor === "pointer" && style.pointerEvents !== 'none') ||
                    (element.onclick != null) ||
                    ['button', 'link', 'menuitem', 'tab', 'checkbox', 'switch', 'combobox', 'listbox', 'option'].includes(role) ||
                    (hasButtonText && textContent.split(' ').length <= 5);

                return {
                    element: element,
                    include: isInteractive,
                    rects: rects,
                    area: rects[0].width * rects[0].height,
                    text: (element.textContent || "").trim().replace(/\\s+/g, ' ')
                };
            }).filter(item => item.include);

            // D. DEDUPLICATION: Leaf-Node Priority
            // If Element A contains Element B, and both are interactive, KEEP B, REMOVE A.
            // This fixes the "Multiple boxes on one button" issue.
            items = items.filter(parent => {
                const hasInteractiveChild = items.some(child =>
                    parent.element !== child.element && parent.element.contains(child.element)
                );
                return !hasInteractiveChild;
            });

            // E. NON-MAX SUPPRESSION: Remove visually overlapping/tightly clustered boxes
            // Targets the case where many elements pile on top of each other (e.g. icon toolbars)
            // Keeps the smaller (more specific) element in each overlapping pair
            items.sort((a, b) => a.area - b.area);
            const nmsKeep = new Array(items.length).fill(true);
            const NMS_PAD = 5;

            for (let i = 0; i < items.length; i++) {
                if (!nmsKeep[i]) continue;
                const bA = items[i].rects[0];
                const aA = bA.width * bA.height;
                const cxA = bA.left + bA.width / 2;
                const cyA = bA.top + bA.height / 2;

                for (let j = i + 1; j < items.length; j++) {
                    if (!nmsKeep[j]) continue;
                    const bB = items[j].rects[0];
                    const aB = bB.width * bB.height;

                    // 1. Center proximity: nearly identical positions -> suppress larger
                    const cxB = bB.left + bB.width / 2;
                    const cyB = bB.top + bB.height / 2;
                    const dist = Math.sqrt(Math.pow(cxA - cxB, 2) + Math.pow(cyA - cyB, 2));
                    if (dist < 15) {
                        nmsKeep[j] = false;
                        continue;
                    }

                    // 2. Padded-box overlap to catch tightly packed clusters
                    const iL = Math.max(bA.left - NMS_PAD, bB.left - NMS_PAD);
                    const iT = Math.max(bA.top - NMS_PAD, bB.top - NMS_PAD);
                    const iR = Math.min(bA.left + bA.width + NMS_PAD, bB.left + bB.width + NMS_PAD);
                    const iB = Math.min(bA.top + bA.height + NMS_PAD, bB.top + bB.height + NMS_PAD);
                    if (iR <= iL || iB <= iT) continue;

                    const interArea = (iR - iL) * (iB - iT);
                    const iou = interArea / (aA + aB - interArea);
                    if (iou > 0.3) {
                        nmsKeep[j] = false;
                        continue;
                    }

                    // 3. Containment: smaller box mostly inside larger -> suppress larger
                    const containment = interArea / aA;
                    if (containment > 0.5) {
                        nmsKeep[j] = false;
                    }
                }
            }
            items = items.filter((_, i) => nmsKeep[i]);

            // F. DRAW MARKERS
            items.forEach((item, index) => {
                const bbox = item.rects[0];
                const marker = document.createElement("div");
                const color = COLOR_FUNCTION(index);

                // Check if element is a checkbox or switch (place label on side)
                const element = item.element;
                const tagName = element.tagName.toUpperCase();
                const role = (element.getAttribute('role') || '').toLowerCase();
                const type = (element.getAttribute('type') || '').toLowerCase();
                const isCheckboxOrSwitch =
                    (tagName === 'INPUT' && (type === 'checkbox' || type === 'radio')) ||
                    (role === 'checkbox') ||
                    (role === 'switch') ||
                    (role === 'radio');

                marker.setAttribute("data-ai-marker", "true"); // Tag for cleanup
                Object.assign(marker.style, {
                    position: 'fixed', // Fixed ensures alignment with viewport coordinates
                    left: bbox.left + 'px',
                    top: bbox.top + 'px',
                    width: bbox.width + 'px',
                    height: bbox.height + 'px',
                    outline: `2px solid ${color}`,
                    zIndex: '2147483647', // Max Z-Index
                    pointerEvents: 'none',
                    boxSizing: 'border-box'
                });

                const label = document.createElement("span");
                label.textContent = index;
                Object.assign(label.style, {
                    position: 'absolute',
                    background: color,
                    color: 'white',
                    fontSize: '11px',
                    fontWeight: 'bold',
                    padding: '1px 4px',
                    borderRadius: '2px',
                    whiteSpace: 'nowrap'
                });

                // Position label on side for checkboxes/switches, on top for others
                if (isCheckboxOrSwitch) {
                    label.style.top = '0px';
                    label.style.left = 'calc(-100% - 10px)';
                } else {
                    label.style.top = '-18px';
                    label.style.left = '0px';
                }

                marker.appendChild(label);
                document.body.appendChild(marker);
                labels.push(marker);
            });

            return [labels, items];
        }
        return markPage();""".replace("COLOR_FUNCTION", selected_function)

    result = browser.execute_script(js_script)
    rects, items_raw = result[0], result[1]

    format_ele_text = []
    for web_ele_id in range(len(items_raw)):
        label_text = items_raw[web_ele_id]['text']
        ele_tag_name = items_raw[web_ele_id]['element'].tag_name
        ele_type = items_raw[web_ele_id]['element'].get_attribute("type")
        ele_aria_label = items_raw[web_ele_id]['element'].get_attribute("aria-label")
        input_attr_types = ['text', 'search', 'password', 'email', 'tel']

        if not label_text:
            if (ele_tag_name.lower() == 'input' and ele_type in input_attr_types) or ele_tag_name.lower() == 'textarea' or (ele_tag_name.lower() == 'button' and ele_type in ['submit', 'button']):
                if ele_aria_label:
                    format_ele_text.append(f"[{web_ele_id}]: <{ele_tag_name}> \"{ele_aria_label}\";")
                else:
                    format_ele_text.append(f"[{web_ele_id}]: <{ele_tag_name}> \"{label_text}\";" )

        elif label_text and len(label_text) < 200:
            if not ("<img" in label_text and "src=" in label_text):
                if ele_tag_name in ["button", "input", "textarea"]:
                    if ele_aria_label and (ele_aria_label != label_text):
                        format_ele_text.append(f"[{web_ele_id}]: <{ele_tag_name}> \"{label_text}\", \"{ele_aria_label}\";")
                    else:
                        format_ele_text.append(f"[{web_ele_id}]: <{ele_tag_name}> \"{label_text}\";")
                else:
                    if ele_aria_label and (ele_aria_label != label_text):
                        format_ele_text.append(f"[{web_ele_id}]: \"{label_text}\", \"{ele_aria_label}\";")
                    else:
                        format_ele_text.append(f"[{web_ele_id}]: \"{label_text}\";")

    format_ele_text = '\t'.join(format_ele_text)
    return rects, [web_ele['element'] for web_ele in items_raw], format_ele_text


def extract_information(text):
    patterns = {
        "click": r"Click \[?(\d+)\]?",
        "hover": r"Hover \[?(\d+)\]?",
        "type": r"Type \[?(\d+)\]?[; ]+\[?([^\]]*)\]?",
        # "delete_and_type": r"Delete_and_Type \[?(\d+)\]?[; ]+\[?(.[^\]]*)\]?",
        "scroll": r"Scroll \[?(\d+|WINDOW)\]?[; ]+\[?(up|down|left|right)\]?",
        "scroll_to_end": r"Scroll_to_end",
        "scroll_within_popup": r"Scroll_within_popup[; ]+\[?(up|down|left|right)\]?",
        "switch_tab": r"Switch_tab \[?([^\]]+)\]?",
        "wait": r"^Wait",
        "goback": r"^GoBack",
        "google": r"^Google",
        "answer": r"ANSWER[; ]+\[?([^\]]*)\]?"
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            if key in ["click", "hover", "wait", "goback", "google", "scroll_to_end"]:
                # no content
                return key, match.groups()
            elif key == "scroll_within_popup":
                # Return direction as content
                return key, {"content": match.group(1)}
            else:
                return key, {"number": match.group(1), "content": match.group(2)} if key in ["type", "scroll"] else {"content": match.group(1)}
    return None, None


def clip_message(msg, max_img_num):
    clipped_msg = []
    img_num = 0
    for idx in range(len(msg)):
        curr_msg = msg[len(msg) - 1 - idx]
        if curr_msg['role'] != 'user':
            clipped_msg = [curr_msg] + clipped_msg
        else:
            if type(curr_msg['content']) == str:
                clipped_msg = [curr_msg] + clipped_msg
            elif img_num < max_img_num:
                img_num += 1
                clipped_msg = [curr_msg] + clipped_msg
            else:
                # Extract text from content (handles both GPT/Claude and Gemini formats)
                content_text = curr_msg['content'][0]
                if isinstance(content_text, dict):
                    content_text = content_text["text"]  # GPT/Claude format
                # else: it's already a string (Gemini format)
                
                curr_msg_clip = {
                    'role': curr_msg['role'],
                    'content': content_text
                }
                clipped_msg = [curr_msg_clip] + clipped_msg
    return clipped_msg


def clip_message_and_obs(msg, max_img_num):
    clipped_msg = []
    img_num = 0
    for idx in range(len(msg)):
        curr_msg = msg[len(msg) - 1 - idx]
        if curr_msg['role'] != 'user':
            clipped_msg = [curr_msg] + clipped_msg
        else:
            if type(curr_msg['content']) == str:
                clipped_msg = [curr_msg] + clipped_msg
            elif img_num < max_img_num:
                img_num += 1
                clipped_msg = [curr_msg] + clipped_msg
            else:
                # Extract text from content (handles both GPT/Claude and Gemini formats)
                content_text = curr_msg['content'][0]
                if isinstance(content_text, dict):
                    content_text = content_text["text"]  # GPT/Claude format
                # else: it's already a string (Gemini format)
                
                msg_no_pdf = content_text.split("Observation:")[0].strip() + "Observation: A screenshot and some texts. (Omitted in context.)"
                msg_pdf = content_text.split("Observation:")[0].strip() + "Observation: A screenshot, a PDF file and some texts. (Omitted in context.)"
                curr_msg_clip = {
                    'role': curr_msg['role'],
                    'content': msg_no_pdf if "You downloaded a PDF file" not in content_text else msg_pdf
                }
                clipped_msg = [curr_msg_clip] + clipped_msg
    return clipped_msg


def clip_message_and_obs_text_only(msg, max_tree_num):
    clipped_msg = []
    tree_num = 0
    for idx in range(len(msg)):
        curr_msg = msg[len(msg) - 1 - idx]
        if curr_msg['role'] != 'user':
            clipped_msg = [curr_msg] + clipped_msg
        else:
            if tree_num < max_tree_num:
                tree_num += 1
                clipped_msg = [curr_msg] + clipped_msg
            else:
                msg_no_pdf = curr_msg['content'].split("Observation:")[0].strip() + "Observation: An accessibility tree. (Omitted in context.)"
                msg_pdf = curr_msg['content'].split("Observation:")[0].strip() + "Observation: An accessibility tree and a PDF file. (Omitted in context.)"
                curr_msg_clip = {
                    'role': curr_msg['role'],
                    'content': msg_no_pdf if "You downloaded a PDF file" not in curr_msg['content'] else msg_pdf
                }
                clipped_msg = [curr_msg_clip] + clipped_msg
    return clipped_msg


def print_message(json_object, save_dir=None):
    remove_b64code_obj = []
    for obj in json_object:
        if obj['role'] != 'user':
            # print(obj)
            logging.info(obj)
            remove_b64code_obj.append(obj)
        else:
            if type(obj['content']) == str:
                # print(obj)
                logging.info(obj)
                remove_b64code_obj.append(obj)

            elif isinstance(obj['content'], list): #handles Gemini format
                # Gemini format: [text_string, image_Part_object]
                content_text = obj['content'][0]
                # Just log text + placeholder for image (image Part can't be serialized)
                print_obj = {
                    'role': obj['role'],
                    'content': [content_text, "<image_part>"]
                }
                logging.info(print_obj)
                remove_b64code_obj.append(print_obj)
            else:
                print_obj = {
                    'role': obj['role'],
                    'content': obj['content']
                }
                for item in print_obj['content']:
                    if item['type'] == 'image_url':
                        item['image_url'] =  {"url": "data:image/png;base64,{b64_img}"}
                # print(print_obj)
                logging.info(print_obj)
                remove_b64code_obj.append(print_obj)
    if save_dir:
        with open(os.path.join(save_dir, 'interact_messages.json'), 'w', encoding='utf-8') as fw:
            json.dump(remove_b64code_obj, fw, indent=2)
    # return remove_b64code_obj


def get_webarena_accessibility_tree(browser, save_file=None):
    browser_info = fetch_browser_info(browser)
    accessibility_tree = fetch_page_accessibility_tree(browser_info, browser, current_viewport_only=True)
    content, obs_nodes_info = parse_accessibility_tree(accessibility_tree)
    content = clean_accesibility_tree(content)
    if save_file:
        with open(save_file + '.json', 'w', encoding='utf-8') as fw:
            json.dump(obs_nodes_info, fw, indent=2)
        with open(save_file + '.txt', 'w', encoding='utf-8') as fw:
            fw.write(content)


    return content, obs_nodes_info


def compare_images(img1_path, img2_path):
    img1 = Image.open(img1_path)
    img2 = Image.open(img2_path)

    img1_array = np.asarray(img1)
    img2_array = np.asarray(img2)

    difference = np.abs(img1_array - img2_array)

    total_difference = np.sum(difference)

    return total_difference


def get_pdf_retrieval_ans_from_assistant(client, pdf_path, task):
    # print("You download a PDF file that will be retrieved using the Assistant API.")
    logging.info("You download a PDF file that will be retrieved using the Assistant API.")
    file = client.files.create(
        file=open(pdf_path, "rb"),
        purpose='assistants'
    )
    # print("Create assistant...")
    logging.info("Create assistant...")
    assistant = client.beta.assistants.create(
        instructions="You are a helpful assistant that can analyze the content of a PDF file and give an answer that matches the given task, or retrieve relevant content that matches the task.",
        model="gpt-5",
        tools=[{"type": "retrieval"}],
        file_ids=[file.id]
    )
    thread = client.beta.threads.create()
    message = client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=task,
        file_ids=[file.id]
    )
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant.id
    )
    while True:
        # Retrieve the run status
        run_status = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
        if run_status.status == 'completed':
            break
        time.sleep(2)
    messages = client.beta.threads.messages.list(thread_id=thread.id)
    messages_text = messages.data[0].content[0].text.value
    file_deletion_status = client.beta.assistants.files.delete(
        assistant_id=assistant.id,
        file_id=file.id
    )
    # print(file_deletion_status)
    logging.info(file_deletion_status)
    assistant_deletion_status = client.beta.assistants.delete(assistant.id)
    # print(assistant_deletion_status)
    logging.info(assistant_deletion_status)
    return messages_text
