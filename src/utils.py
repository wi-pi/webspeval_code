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
        function getRandomColor(index) {
            let hue = (index * 137.5) % 360;
            return `hsl(${hue}, 80%, 40%)`;
        }
        function getFixedColor(index) { return '#000000'; }

        function markPage() {
            document.querySelectorAll("div[data-ai-marker]").forEach(el => el.remove());

            const vw = Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0);
            const vh = Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0);

            // Measure each element against its OWN document (so elements inside same-origin
            // iframes are evaluated in their local coordinate system), then offset into the
            // top page when drawing. gcs/vpW/vpH resolve style + viewport per ownerDocument.
            function gcs(el) { return (el.ownerDocument.defaultView || window).getComputedStyle(el); }
            function vpW(el) { const d = el.ownerDocument, w = d.defaultView || window;
                return Math.max(d.documentElement.clientWidth || 0, w.innerWidth || 0); }
            function vpH(el) { const d = el.ownerDocument, w = d.defaultView || window;
                return Math.max(d.documentElement.clientHeight || 0, w.innerHeight || 0); }

            // ---- Modal scoping: if a modal dialog is open, restrict candidates to its
            // subtree so background page content (behind the overlay) is not marked.
            function findActiveModal() {
                const candidates = Array.from(document.querySelectorAll(
                    '[aria-modal="true"], dialog[open], [role="dialog"], [role="alertdialog"]'
                )).filter(el => {
                    if (el.tagName === 'DIALOG' && !el.hasAttribute('open')) return false;
                    if (el.getAttribute('aria-hidden') === 'true') return false;
                    const s = window.getComputedStyle(el);
                    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
                    const r = el.getBoundingClientRect();
                    return r.width >= 80 && r.height >= 80;
                });
                if (candidates.length === 0) return null;
                function zOf(el) {
                    let cur = el, max = 0;
                    while (cur && cur !== document.body) {
                        const z = parseInt(window.getComputedStyle(cur).zIndex);
                        if (!isNaN(z) && z > max) max = z;
                        cur = cur.parentElement;
                    }
                    return max;
                }
                candidates.sort((a, b) => {
                    const dz = zOf(b) - zOf(a);
                    if (dz !== 0) return dz;
                    return (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) ? 1 : -1;
                });
                return candidates[0];
            }

            // Per-element offset from its own document's viewport to the TOP page viewport,
            // accumulated through same-origin <iframe> boundaries (0,0 for top-document
            // elements). Geometry is computed locally; this offset is added only when the
            // marker rect is built so boxes land in the right place over the iframe.
            const frameOffset = new Map();
            function getAllElements(root, offX, offY, collected) {
                const elements = root.querySelectorAll('*');
                for (const element of elements) {
                    collected.push(element);
                    frameOffset.set(element, { x: offX, y: offY });
                    if (element.shadowRoot) getAllElements(element.shadowRoot, offX, offY, collected);
                    if (element.tagName === 'IFRAME') {
                        let idoc = null;
                        try { idoc = element.contentDocument; } catch (e) { idoc = null; }
                        if (idoc && idoc.documentElement) {
                            const ir = element.getBoundingClientRect();
                            const ics = gcs(element);
                            const bl = parseFloat(ics.borderLeftWidth) || 0;
                            const bt = parseFloat(ics.borderTopWidth) || 0;
                            const pl = parseFloat(ics.paddingLeft) || 0;
                            const pt = parseFloat(ics.paddingTop) || 0;
                            getAllElements(idoc, offX + ir.left + bl + pl, offY + ir.top + bt + pt, collected);
                        }
                    }
                }
                return collected;
            }

            const activeModal = findActiveModal();
            const allElements = getAllElements(activeModal || document, 0, 0, []);

            // ---- Custom toggle/checkbox widgets: a hidden <input type=checkbox|radio>
            // controlled by a <label for=...> (or wrapping label). The label is the real
            // click target. We:
            //   1. Resolve each label-for-checkbox to its input and remember the label's rect.
            //   2. Drop the label itself and all its descendants from the candidate list
            //      so visual sub-parts (knobs, slider tracks) are not detected as separate
            //      items at slightly offset positions.
            const widgetRectByInput = new Map();   // input element -> rect to draw
            const widgetSkip = new Set();          // elements inside/being the label

            function resolveCheckboxLabel(label) {
                if (!label || label.tagName !== 'LABEL') return null;
                const forId = label.getAttribute('for');
                if (forId) {
                    const root = label.getRootNode();
                    const target = (root.getElementById && root.getElementById(forId))
                        || document.getElementById(forId);
                    if (target && target.tagName === 'INPUT' &&
                        ['checkbox','radio'].includes((target.getAttribute('type')||'').toLowerCase())) {
                        return target;
                    }
                }
                const inner = label.querySelector('input[type="checkbox"], input[type="radio"]');
                return inner || null;
            }

            for (const el of allElements) {
                if (el.tagName !== 'LABEL') continue;
                const input = resolveCheckboxLabel(el);
                if (!input) continue;

                // Only remap to the label's rect when the input itself is invisible
                // (custom-toggle pattern: hidden input + styled label/slider). For
                // native visible checkboxes the input has its own square and the
                // label is just associated text - leave the input alone so the bbox
                // sits on the actual checkbox, not on the label text.
                const inputRects = input.getClientRects();
                const inputCs = gcs(input);
                const inputVisible = inputRects.length > 0
                    && inputRects[0].width >= 3 && inputRects[0].height >= 3
                    && inputCs.display !== 'none' && inputCs.visibility !== 'hidden'
                    && inputCs.opacity !== '0';
                if (inputVisible) continue;

                const r = el.getBoundingClientRect();
                if (r.width < 3 || r.height < 3) continue;
                widgetRectByInput.set(input, r);
                widgetSkip.add(el);
                // Skip label descendants (visual sub-parts like the slider span) but
                // keep the input itself - it's the canonical interactive target and
                // will be drawn at the label's rect. Wrapping-label patterns put the
                // input inside the label, so we must exempt it explicitly.
                el.querySelectorAll('*').forEach(d => {
                    if (d !== input) widgetSkip.add(d);
                });
            }

            // ---- Hidden native checkbox/radio inputs styled via a sibling/wrapper with
            // NO <label> (e.g. Pinterest: <input type=checkbox> clipped to 0px next to a
            // visible decorative <div> acting as the checkbox skin). Remap the input to the
            // visible skin's rect so the toggle is detected, and skip the skin to avoid a
            // duplicate. This pass is strictly additive: native visible checkboxes and
            // label-controlled toggles (handled above) are skipped, so nothing that already
            // worked changes.
            function inputIsVisible(input) {
                const rs = input.getClientRects();
                const cs = gcs(input);
                return rs.length > 0 && rs[0].width >= 3 && rs[0].height >= 3
                    && cs.display !== 'none' && cs.visibility !== 'hidden' && cs.opacity !== '0';
            }
            const skinInteractiveRoles = ['button','link','checkbox','switch','radio','tab',
                'menuitem','menuitemcheckbox','menuitemradio','combobox','listbox','option'];
            for (const input of allElements) {
                if (input.tagName !== 'INPUT') continue;
                const itype = (input.getAttribute('type') || '').toLowerCase();
                if (itype !== 'checkbox' && itype !== 'radio') continue;
                if (widgetRectByInput.has(input)) continue;   // already mapped via a <label>
                if (inputIsVisible(input)) continue;           // native visible checkbox - leave alone
                const parent = input.parentElement;
                if (!parent) continue;

                // Decorative skin = a visible, checkbox-sized, NON-interactive element in the
                // input's immediate container (the parent wrapper itself, or a sibling).
                const skinCandidates = [parent, ...parent.querySelectorAll('*')].filter(node => {
                    if (node === input) return false;
                    const stag = node.tagName.toUpperCase();
                    if (['A','BUTTON','INPUT','SELECT','TEXTAREA'].includes(stag)) return false;
                    const srole = (node.getAttribute('role') || '').toLowerCase();
                    if (skinInteractiveRoles.includes(srole)) return false;
                    const cs = gcs(node);
                    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
                    const r = node.getBoundingClientRect();
                    return r.width >= 6 && r.height >= 6 && r.width <= 80 && r.height <= 80;
                });
                if (!skinCandidates.length) continue;
                // Prefer empty (purely decorative) skins over ones holding text; then smallest.
                skinCandidates.sort((a, b) => {
                    const at = (a.textContent || '').trim() === '' ? 0 : 1;
                    const bt = (b.textContent || '').trim() === '' ? 0 : 1;
                    if (at !== bt) return at - bt;
                    const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
                    return (ra.width * ra.height) - (rb.width * rb.height);
                });
                const skin = skinCandidates[0];
                const sr = skin.getBoundingClientRect();
                if (sr.width < 3 || sr.height < 3) continue;
                widgetRectByInput.set(input, sr);
                if (skin !== parent) {
                    widgetSkip.add(skin);
                    skin.querySelectorAll('*').forEach(d => widgetSkip.add(d));
                }
            }

            // ---- Build candidate list
            let items = allElements.map(element => {
                if (widgetSkip.has(element)) return { include: false };

                const tagName = element.tagName.toUpperCase();
                const role = (element.getAttribute('role') || '').toLowerCase();
                const type = (element.getAttribute('type') || '').toLowerCase();

                let bb = null;

                // Hidden checkbox/radio inputs: use the resolved label's rect.
                if (widgetRectByInput.has(element)) {
                    bb = widgetRectByInput.get(element);
                } else {
                    let rects = [...element.getClientRects()];
                    // Semantic interactive elements with collapsed rects: try the
                    // union of child rects so visually-laid-out wrappers get marked.
                    // Covers semantic tags AND elements carrying an explicit interactive
                    // role (e.g. <div role="checkbox"> whose checkmark child is absolutely
                    // positioned, collapsing the parent's own rect to 0 - Steam toggles).
                    const collapsibleRole = ['button','link','checkbox','switch','radio',
                        'tab','menuitem','menuitemcheckbox','menuitemradio','combobox',
                        'listbox','option'].includes(role);
                    if ((['BUTTON','A','INPUT','SELECT','TEXTAREA'].includes(tagName) || collapsibleRole)
                        && (rects.length === 0 || rects[0].width < 3 || rects[0].height < 3)) {
                        const cbb = element.getBoundingClientRect();
                        if (cbb.width >= 3 && cbb.height >= 3) {
                            rects = [cbb];
                        } else {
                            let l=Infinity, t=Infinity, r=-Infinity, b=-Infinity;
                            element.querySelectorAll('*').forEach(c => {
                                const cr = c.getBoundingClientRect();
                                if (cr.width > 0 && cr.height > 0) {
                                    l = Math.min(l, cr.left); t = Math.min(t, cr.top);
                                    r = Math.max(r, cr.right); b = Math.max(b, cr.bottom);
                                }
                            });
                            if (r > l && b > t) rects = [{left:l, top:t, right:r, bottom:b, width:r-l, height:b-t}];
                        }
                    }
                    if (rects.length === 0) return { include: false };
                    bb = rects[0];

                    // Icon-only submit/button/image inputs (e.g. Amazon's magnifying-glass
                    // search button) often have their visible click target rendered by a
                    // wrapping span/div carrying an aria-label or a sprite/background-image.
                    // The INPUT itself is sized smaller than the visible button. If the
                    // parent provides the visual/semantic identity and is meaningfully
                    // larger, draw the parent's rect instead.
                    //
                    // Conversely, hidden duplicate submits (e.g. Amazon's signed-in-user
                    // "Agent Search" helper) have no visible identity at all - no aria-label,
                    // no parent icon, and cursor:default. Drop those.
                    if (tagName === 'INPUT' && ['submit','button','image'].includes(type)) {
                        const elCursor = gcs(element).cursor;
                        const elAria = element.getAttribute('aria-label');
                        const parent = element.parentElement;
                        const ps = parent ? gcs(parent) : null;
                        const parentHasIcon = ps && ps.backgroundImage && ps.backgroundImage !== 'none';
                        const parentHasAriaLabel = parent && !!parent.getAttribute('aria-label');

                        if (!elAria && !parentHasAriaLabel && !parentHasIcon && elCursor !== 'pointer') {
                            return { include: false };
                        }
                        if (parent && (parentHasIcon || parentHasAriaLabel)) {
                            const pr = parent.getBoundingClientRect();
                            if (pr.width >= 3 && pr.height >= 3
                                && pr.width * pr.height > bb.width * bb.height * 1.1) {
                                bb = pr;
                            }
                        }
                    }
                }

                // Basic geometry / viewport check
                if (bb.width < 3 || bb.height < 3) return { include: false };
                if (bb.left > vpW(element) || bb.top > vpH(element) || bb.right < 0 || bb.bottom < 0) return { include: false };

                // Empty decoration: non-semantic elements (span/div/etc.) with no text,
                // no aria-label, no icon descendants, and no explicit interactive role
                // are pure visual padding inside a clickable parent (e.g. inherited
                // cursor:pointer). The semantic ancestor is the real click target.
                if (!['A','BUTTON','INPUT','SELECT','TEXTAREA'].includes(tagName)
                    && !['button','link','checkbox','switch','radio','tab','menuitem',
                         'menuitemcheckbox','menuitemradio','combobox','listbox','option'].includes(role)
                    && !(element.textContent || '').trim()
                    && !element.getAttribute('aria-label')
                    && !element.getAttribute('aria-labelledby')
                    && !element.getAttribute('title')
                    && !element.querySelector('svg, img')) {
                    return { include: false };
                }

                // Visibility: skip browser-hidden elements (unless we're using a
                // resolved widget rect, in which case the input's own display:none is fine).
                if (!widgetRectByInput.has(element)) {
                    const cs = gcs(element);
                    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') {
                        return { include: false };
                    }
                    // elementFromPoint hit test against center + 4 corners. Skips elements
                    // covered by an overlay (e.g. modal-backdrop'd page content). Coordinates
                    // and elementFromPoint are local to the element's own document, so the
                    // test works inside same-origin iframes too.
                    const evw = vpW(element), evh = vpH(element);
                    const edoc = element.ownerDocument;
                    const padX = Math.min(5, bb.width / 4);
                    const padY = Math.min(5, bb.height / 4);
                    const points = [
                        {x: bb.left + bb.width / 2, y: bb.top + bb.height / 2},
                        {x: bb.left + padX,        y: bb.top + padY},
                        {x: bb.right - padX,       y: bb.bottom - padY},
                        {x: bb.left + padX,        y: bb.bottom - padY},
                        {x: bb.right - padX,       y: bb.top + padY}
                    ];
                    const hit = points.some(p => {
                        if (p.x < 0 || p.x > evw || p.y < 0 || p.y > evh) return false;
                        const at = edoc.elementFromPoint(p.x, p.y);
                        if (!at) return false;
                        return at === element || element.contains(at) || at.contains(element) ||
                               (at.shadowRoot && at.shadowRoot.contains(element));
                    });
                    if (!hit) return { include: false };
                }

                // Interactivity check
                const style = gcs(element);
                const text = (element.textContent || '').trim().toLowerCase();
                // Action-verb labels: catches buttons that lack role/cursor signaling.
                // Excludes "on"/"off" - those are toggle status indicators, not buttons,
                // and would NMS-suppress the actual toggle input next to them.
                const buttonyText = /^(confirm|submit|accept|continue|save|apply|ok|close|cancel|reject|deny)/i.test(text)
                                    && text.split(' ').length <= 5;
                const isInteractive =
                    tagName === 'A' || tagName === 'BUTTON' || tagName === 'INPUT' ||
                    tagName === 'TEXTAREA' || tagName === 'SELECT' || tagName.startsWith('CR-') ||
                    (style.cursor === 'pointer' && style.pointerEvents !== 'none') ||
                    element.onclick != null ||
                    ['button','link','menuitem','menuitemcheckbox','menuitemradio','tab',
                     'checkbox','switch','radio','combobox','listbox','option'].includes(role) ||
                    buttonyText;
                if (!isInteractive) return { include: false };

                // Offset local (own-document) coords into the top page so the marker lands
                // over the element even when it lives inside a same-origin iframe.
                const off = frameOffset.get(element) || { x: 0, y: 0 };
                const rect = {
                    left: Math.max(0, bb.left) + off.x, top: Math.max(0, bb.top) + off.y,
                    width: bb.width, height: bb.height
                };
                return {
                    element: element, include: true,
                    rects: [rect],
                    area: rect.width * rect.height,
                    text: (element.textContent || '').trim().replace(/\\s+/g, ' ')
                };
            }).filter(item => item.include);

            // Containment resolution:
            //   (a) If a semantic interactive element (a, button, input, etc., or with
            //       an explicit interactive role) contains other items, those descendants
            //       are decoration (cursor:pointer inherited onto a child <span> inside
            //       a <button>, etc.) - drop them, keep the semantic parent.
            //   (b) Otherwise (non-semantic wrappers like <div cursor:pointer> around
            //       a real button), keep the leaf.
            const semanticTags = new Set(['A','BUTTON','INPUT','SELECT','TEXTAREA']);
            const semanticRoles = new Set(['button','link','checkbox','switch','radio','tab',
                'combobox','listbox','option','menuitem','menuitemcheckbox','menuitemradio']);
            function isSemanticInteractive(el) {
                if (semanticTags.has(el.tagName.toUpperCase())) return true;
                return semanticRoles.has((el.getAttribute('role') || '').toLowerCase());
            }
            const itemElements = new Set(items.map(it => it.element));
            // Step (a): drop items whose ancestor is a semantic interactive also in items.
            items = items.filter(item => {
                let cur = item.element.parentElement;
                while (cur) {
                    if (itemElements.has(cur) && isSemanticInteractive(cur)) return false;
                    cur = cur.parentElement;
                }
                return true;
            });
            // Step (b): existing leaf-priority for non-semantic wrappers.
            items = items.filter(parent => !items.some(child =>
                parent.element !== child.element && parent.element.contains(child.element)
            ));

            // Non-max suppression: collapse heavily-overlapping or near-coincident boxes.
            // Uses raw rects (no padding) - padding inflates small elements and incorrectly
            // suppresses tightly-stacked items like vertical lists of native checkboxes.
            // The center-proximity check (15px) already handles tight clusters.
            items.sort((a, b) => a.area - b.area);
            const keep = new Array(items.length).fill(true);
            for (let i = 0; i < items.length; i++) {
                if (!keep[i]) continue;
                const A = items[i].rects[0];
                const aA = A.width * A.height;
                const cxA = A.left + A.width / 2, cyA = A.top + A.height / 2;
                for (let j = i + 1; j < items.length; j++) {
                    if (!keep[j]) continue;
                    const B = items[j].rects[0];
                    const aB = B.width * B.height;
                    const cxB = B.left + B.width / 2, cyB = B.top + B.height / 2;
                    if (Math.hypot(cxA - cxB, cyA - cyB) < 15) { keep[j] = false; continue; }
                    const iL = Math.max(A.left, B.left);
                    const iT = Math.max(A.top, B.top);
                    const iR = Math.min(A.left + A.width, B.left + B.width);
                    const iB = Math.min(A.top + A.height, B.top + B.height);
                    if (iR <= iL || iB <= iT) continue;
                    const inter = (iR - iL) * (iB - iT);
                    if (inter / (aA + aB - inter) > 0.3) { keep[j] = false; continue; }
                    if (inter / aA > 0.5) keep[j] = false;
                }
            }
            items = items.filter((_, i) => keep[i]);

            // Draw markers. A native <dialog open> renders in the browser's top layer
            // which is above the entire document regardless of z-index. Markers placed
            // in document.body cannot appear above it. Append markers inside the dialog
            // so they share the same top layer.
            const markerParent = (activeModal && activeModal.tagName === 'DIALOG'
                && activeModal.hasAttribute('open')) ? activeModal : document.body;
            const labels = [];
            items.forEach((item, index) => {
                const bbox = item.rects[0];
                const marker = document.createElement('div');
                const color = COLOR_FUNCTION(index);

                const el = item.element;
                const tag = el.tagName.toUpperCase();
                const r = (el.getAttribute('role') || '').toLowerCase();
                const t = (el.getAttribute('type') || '').toLowerCase();
                const isToggle = (tag === 'INPUT' && (t === 'checkbox' || t === 'radio'))
                              || ['checkbox','switch','radio'].includes(r);

                marker.setAttribute('data-ai-marker', 'true');
                Object.assign(marker.style, {
                    position: 'fixed',
                    left: bbox.left + 'px', top: bbox.top + 'px',
                    width: bbox.width + 'px', height: bbox.height + 'px',
                    outline: '2px solid ' + color,
                    zIndex: '2147483647', pointerEvents: 'none', boxSizing: 'border-box'
                });

                const tag_label = document.createElement('span');
                tag_label.textContent = index;
                // Default to placing the number above the box; if the box is
                // too close to the top of the viewport (number would be clipped),
                // place it just inside the top edge instead.
                const placeAbove = !isToggle && bbox.top >= 18;
                Object.assign(tag_label.style, {
                    position: 'absolute', background: color, color: 'white',
                    fontSize: '11px', fontWeight: 'bold', padding: '1px 4px',
                    borderRadius: '2px', whiteSpace: 'nowrap',
                    top: isToggle ? '0px' : (placeAbove ? '-18px' : '0px'),
                    left: isToggle ? 'calc(-100% - 10px)' : '0px'
                });
                marker.appendChild(tag_label);
                markerParent.appendChild(marker);
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
