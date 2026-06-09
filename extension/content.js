// content-option2.js
// ====================
// SHADOW DOM IMPLEMENTATION: Option 2 - TreeWalker API
// ====================
// This version uses the browser's native TreeWalker API for efficient DOM traversal.
// It's extended to manually descend into shadow roots when encountered.
// Most browser-native and potentially most performant.
//
// TO TEST THIS VERSION:
// 1. Copy this file over content.js, OR
// 2. Update manifest.json to point to content-option2.js instead of content.js

let recording = false;
let mutationObserver = null;
let webspIndexObserver = null; // Dedicated observer for WEBSP index assignment (always active)
// let domChangeObserver = null;
let lastScreenshotTime = 0;
const SCREENSHOT_DEBOUNCE_MS = 100; // Prevent duplicate screenshots within 100ms
let recentInteractions = new Map(); // Track recent interactions (mousedown/click/pointer) to prevent duplicates
const INTERACTION_DEDUPE_MS = 500; // Consider interactions within 500ms as duplicates (pointerdown triggers mousedown+click)
// let pendingDomChanges = []; // Accumulated DOM changes since last event
// let lastEventTimestamp = null; // Track when last event occurred

// WEBSP index assignment debouncing for dynamic content
let webspIndexTimer = null;
const WEBSP_INDEX_DEBOUNCE_MS = 500; // Wait 500ms after last DOM change before assigning indexes
// Note: Listeners are attached automatically after WEBSP indexing completes

// Note: State persistence is handled by background.js using chrome.storage.local
// Content scripts should not use localStorage as it belongs to the webpage

// ====================
// MONKEY-PATCH: Neutralize stopImmediatePropagation
// ====================
// This prevents websites (like Grammarly) from blocking our event listeners
// by calling stopImmediatePropagation() in their handlers.
// CRITICAL: This MUST run before any other code to be effective.
(function() {
  const originalStopImmediatePropagation = Event.prototype.stopImmediatePropagation;

  Event.prototype.stopImmediatePropagation = function() {
    console.log('[Monkey-patch] stopImmediatePropagation called on:', this.type, 'target:', this.target);

    // Option A: Completely disable it (our listeners will always fire)
    // Do nothing - don't call the original

    // Option B: Call original but log it (for debugging)
    // originalStopImmediatePropagation.call(this);

    // For now, we'll use Option A to ensure our listeners always fire
    // If this causes issues with the website's functionality, we can switch to Option B
  };

  console.log('[Monkey-patch] ✅ stopImmediatePropagation has been neutralized');
})();

// Also patch stopPropagation for completeness (in case websites use that instead)
(function() {
  const originalStopPropagation = Event.prototype.stopPropagation;

  Event.prototype.stopPropagation = function() {
    console.log('[Monkey-patch] stopPropagation called on:', this.type, 'target:', this.target);
    // DISABLE stopPropagation so events reach our document-level listeners
    // Do NOT call originalStopPropagation - let the event bubble!
  };

  console.log('[Monkey-patch] ✅ stopPropagation has been neutralized');
})();

// SHADOW DOM TRAVERSAL - Option 2: TreeWalker with Shadow DOM support
// Use browser's native TreeWalker API and extend it to enter shadow roots
function getAllElementsIncludingShadowDOM(root) {
  const elements = [];

  function walkTree(rootNode) {
    // Create a TreeWalker to traverse all element nodes
    const walker = document.createTreeWalker(
      rootNode,
      NodeFilter.SHOW_ELEMENT,
      null,
      false
    );

    let node;
    while (node = walker.nextNode()) {
      elements.push(node);

      // If this node has a shadow root, recursively walk it
      if (node.shadowRoot) {
        walkTree(node.shadowRoot);
      }
    }
  }

  // Start with the root element itself
  if (root.nodeType === Node.ELEMENT_NODE) {
    elements.push(root);
    if (root.shadowRoot) {
      walkTree(root.shadowRoot);
    }
  }

  // Walk all descendants
  walkTree(root);

  return elements;
}

// WEBSPindex: Assign sequential numbers to all tabbable elements by simulating tab navigation
function assignWEBSPIndexes() {
  try {
    // DETERMINISTIC INDEXING: Always start from 1 and re-index everything in DOM order
    // This prevents race conditions where different load times result in different indices for the same element
    let nextAvailableIndex = 1;
    
    // Find ALL focusable elements including those in shadow DOM using TreeWalker
    const allElements = getAllElementsIncludingShadowDOM(document.body);
    const tabbableElements = allElements.filter(el => {
      // Skip disabled elements
      if (el.disabled) return false;
      if (el.type === 'hidden') return false;
      
      // Check if element is visible
      const style = window.getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden') return false;
      if (style.opacity === '0' && style.pointerEvents === 'none') return false;
      
      // Check tabindex - skip negative tabindex (explicitly not tabbable)
      const tabindex = el.getAttribute('tabindex');
      const tabindexValue = tabindex ? parseInt(tabindex, 10) : null;
      if (tabindexValue !== null && tabindexValue < 0) return false;
      
      // Element is focusable if:
      // 1. It has a non-negative tabindex (explicit), OR
      // 2. It's a naturally focusable element, OR
      // 3. It has contenteditable, OR
      // 4. It has a role that implies interactivity
      
      if (tabindexValue !== null && tabindexValue >= 0) return true;
      
      // Check for naturally focusable elements
      const tagName = el.tagName.toLowerCase();
      if (tagName === 'a' && el.hasAttribute('href')) return true;
      if (tagName === 'button') return true;
      if (tagName === 'input') return true;
      if (tagName === 'select') return true;
      if (tagName === 'textarea') return true;
      if (tagName === 'audio' && el.hasAttribute('controls')) return true;
      if (tagName === 'video' && el.hasAttribute('controls')) return true;
      if (tagName === 'details') return true;
      if (tagName === 'iframe') return true;
      
      // Check for contenteditable
      if (el.isContentEditable) return true;
      
      // Check for interactive ARIA roles
      const role = el.getAttribute('role');
      const interactiveRoles = [
        'button', 'link', 'checkbox', 'radio', 'switch', 'tab',
        'menuitem', 'menuitemcheckbox', 'menuitemradio', 'option',
        'textbox', 'searchbox', 'slider', 'spinbutton', 'combobox',
        'listbox', 'grid', 'gridcell', 'tree', 'treeitem', 'treegrid'
      ];
      if (role && interactiveRoles.includes(role.toLowerCase())) return true;
      
      // Try to detect if element can receive focus by checking if it would accept focus
      // This is a last resort check - some elements might be focusable through JavaScript
      // but we can't easily detect them without attempting to focus
      try {
        // Check if element has any click handlers or is part of an interactive widget
        const hasClickHandler = el.onclick !== null || 
                               el.getAttribute('onclick') !== null ||
                               el.style.cursor === 'pointer';
        if (hasClickHandler && tabindexValue === null) {
          // Element seems interactive but has no explicit tabindex
          // We'll include it to be safe
          return true;
        }
      } catch (e) {
        // Ignore errors
      }
      
      return false;
    });
    
    // No sorting - just iterate in DOM order

    // Assign indices to elements in DOM order
    // NOTE: We do NOT call .focus() to avoid closing dropdowns/popups/menus
    // The index order is determined purely by DOM traversal order, not tab navigation
    let newlyIndexedCount = 0;
    const MAX_ITERATIONS = 10000; // Safety limit to prevent infinite loops
    const visitedElements = new Set();
    
    for (let i = 0; i < tabbableElements.length && i < MAX_ITERATIONS; i++) {
      const element = tabbableElements[i];
      
      // Skip if we've already visited this element (cycle detection)
      if (visitedElements.has(element)) {
        continue;
      }
      visitedElements.add(element);
      
      // Assign index based on deterministic DOM order
      element.webspIndex = nextAvailableIndex;
      element.setAttribute('data-websp-index', nextAvailableIndex);
      nextAvailableIndex++;
      newlyIndexedCount++;
    }

    const totalIndexed = nextAvailableIndex - 1;
    const timestamp = new Date().toISOString();
    console.log(`[assignWEBSPIndexes ${timestamp}] ✅ Complete - Re-indexed all elements (deterministic). Total: ${totalIndexed}`);

  } catch (error) {
    console.error('Error assigning WEBSPindex:', error);
  }
}

// Debounced version of assignWEBSPIndexes for dynamic content injections
// Waits 500ms after last DOM change before running to ensure all elements are rendered
function assignWEBSPIndexesDebounced() {
  // Clear any pending timer
  if (webspIndexTimer) {
    clearTimeout(webspIndexTimer);
    console.log(`[WEBSP Debounced ${new Date().toISOString()}] ⏱️  Reset timer - waiting ${WEBSP_INDEX_DEBOUNCE_MS}ms`);
  }

  // Set new timer to run after 500ms of inactivity
  webspIndexTimer = setTimeout(() => {
    console.log(`[WEBSP Debounced ${new Date().toISOString()}] 🚀 Running delayed WEBSP index assignment after dynamic injection`);
    assignWEBSPIndexes();
    webspIndexTimer = null;

    // IMPORTANT: Attach listeners AFTER WEBSP indexing completes
    // This ensures newly indexed elements get event listeners attached
    console.log(`[WEBSP Debounced ${new Date().toISOString()}] 🔗 Now attaching listeners to newly indexed elements`);
    attachListeners(document);
  }, WEBSP_INDEX_DEBOUNCE_MS);
}

// Set up a permanent mutation observer for WEBSP index assignment (runs regardless of recording state)
function startWEBSPIndexObserver() {
  if (webspIndexObserver) {
    console.log('WEBSP index observer already running');
    return;
  }
  
  try {
    webspIndexObserver = new MutationObserver(mutations => {
      let hasAddedNodes = false;
      for (const mutation of mutations) {
        if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
          mutation.addedNodes.forEach(node => {
            if (node.nodeType === Node.ELEMENT_NODE) {
              hasAddedNodes = true;
              
              // Check if this is an iframe and set up observer for when it loads
              if (node.tagName === 'IFRAME') {
                node.addEventListener('load', () => {
                  try {
                    const iframeDoc = node.contentDocument || node.contentWindow?.document;
                    if (iframeDoc && iframeDoc.body) {
                      console.log('[WEBSP Iframe] Assigning indexes to iframe content');
                      assignWEBSPIndexes();
                      // Also watch for mutations inside the iframe
                      const iframeWebspObserver = new MutationObserver(iframeMutations => {
                        let hasIframeAddedNodes = false;
                        for (const iframeMutation of iframeMutations) {
                          if (iframeMutation.type === 'childList' && iframeMutation.addedNodes.length > 0) {
                            iframeMutation.addedNodes.forEach(iframeNode => {
                              if (iframeNode.nodeType === Node.ELEMENT_NODE) {
                                hasIframeAddedNodes = true;
                              }
                            });
                          }
                        }
                        if (hasIframeAddedNodes) {
                          assignWEBSPIndexesDebounced();
                        }
                      });
                      iframeWebspObserver.observe(iframeDoc.body, { childList: true, subtree: true });
                    }
                  } catch (iframeError) {
                    // Cross-origin iframes will throw errors - that's expected
                    console.log('[WEBSP Iframe] Cannot access iframe content (cross-origin)');
                  }
                });
              }
            }
          });
        }
      }
      // Reassign WEBSPindex after DOM changes (debounced to handle rapid injections)
      if (hasAddedNodes) {
        assignWEBSPIndexesDebounced();
      }
    });
    
    webspIndexObserver.observe(document.body, { childList: true, subtree: true });
    console.log('WEBSP index observer started (always active)');
  } catch (error) {
    console.error('Error starting WEBSP index observer:', error);
  }
}

// Note: All state management is now handled by background.js
// Content scripts query the background script for the current recording state

// Check if recording is already active on page load/refresh
(function checkRecordingState() {
  // Wait for entire page (including all resources) to be fully loaded before assigning WEBSPindex
  if (document.readyState !== 'complete') {
    window.addEventListener('load', () => {
      setTimeout(() => {
        // Assign WEBSPindex after entire page (including images, iframes, stylesheets) is loaded
        assignWEBSPIndexes();
        // Start the permanent WEBSP index observer (always active, regardless of recording state)
        startWEBSPIndexObserver();
      }, 500); // Slight delay to ensure all resources are settled
    });
  } else {
    setTimeout(() => {
        // Assign WEBSPindex after entire page (including images, iframes, stylesheets) is loaded
        assignWEBSPIndexes();
        // Start the permanent WEBSP index observer (always active, regardless of recording state)
        startWEBSPIndexObserver();
      }, 500); // Slight delay to ensure all resources are settled
  }
  
  // Query background script for current recording state (single source of truth)
  try {
    chrome.runtime.sendMessage({ action: 'getRecordingState' }, (response) => {
      if (chrome.runtime.lastError) {
        console.log('Could not check recording state:', chrome.runtime.lastError.message);
        return;
      }
      
      if (response && response.isRecording) {
        console.log('Background confirms recording is active, starting recording...');
        startRecording(true);
        
        // Send viewport size
        chrome.runtime.sendMessage({
          action: 'getViewportSize',
          width: window.innerWidth,
          height: window.innerHeight
        });
      } else {
        console.log('No active recording detected in background');
      }
    });
  } catch (error) {
    console.error('Error checking recording state:', error);
  }
})();

function startRecording(isReinitialization = false) {
  recording = true;
  lastScreenshotTime = 0; // Reset debounce timer
  recentInteractions.clear(); // Clear interaction deduplication map
  // pendingDomChanges = []; // Clear DOM changes
  // lastEventTimestamp = null;
  console.log('Recording started' + (isReinitialization ? ' (re-initialization after page load)' : ''));
  
  // Note: Recording state is managed by background.js

  // Assign WEBSPindex when recording starts
  assignWEBSPIndexes();

  // Only capture initial states if this is a fresh start, not a re-initialization
  if (!isReinitialization) {
    try {
      // Capture initial states of all form-like controls
      const states = captureInitialFormStates();
      chrome.runtime.sendMessage({ action: 'saveInitialFormStates', states });
      console.log('Initial form states captured:', Object.keys(states).length, 'elements');
    } catch (error) {
      console.error('Error capturing initial form states:', error);
    }
    
    // DOM snapshots commented out to reduce session file size
    // They contained large HTML payloads that aren't necessary for replay
    // try {
    //   // Also capture an initial DOM snapshot to aid element identification
    //   const snapshotEvent = {
    //     type: 'dom-snapshot',
    //     timestamp: new Date().toISOString(),
    //     html: document.documentElement.outerHTML,
    //     framePath: getFramePath()
    //   };
    //   chrome.runtime.sendMessage({ action: 'recordEvent', eventData: snapshotEvent });
    //   console.log('Initial DOM snapshot sent');
    // } catch (error) {
    //   console.error('Error sending initial DOM snapshot:', error);
    // }
  } else {
    console.log('Skipping initial form state capture (re-initialization)');
  }

  try {
    attachListeners(document);
    console.log('Listeners attached');
  } catch (error) {
    console.error('Error attaching listeners:', error);
  }

  try {
    // Observe for dynamically injected elements (SPAs, modals, iframes, etc.)
    mutationObserver = new MutationObserver(mutations => {
      console.log(`[MutationObserver] Detected ${mutations.length} mutations`);
      let hasAddedNodes = false;
      for (const mutation of mutations) {
        if (mutation.type === 'childList') {
          mutation.addedNodes.forEach(node => {
            if (node.nodeType === Node.ELEMENT_NODE) {
              try {
                console.log('[MutationObserver] Element added:', node.tagName, node.id || node.className);
                // Attach listeners immediately to the new node
                attachListeners(node);
                hasAddedNodes = true;
              } catch (err) {
                console.error('[MutationObserver] Error attaching listeners:', err);
              }
              
              // Check if this is an iframe and set up listener for when it loads
              if (node.tagName === 'IFRAME') {
                console.log('[MutationObserver] Iframe detected:', node.src || node.srcdoc);

                const attachToIframe = () => {
                  try {
                    const iframeDoc = node.contentDocument || node.contentWindow?.document;
                    if (iframeDoc && iframeDoc.body) {
                      console.log('[Iframe] Attaching listeners to iframe content');
                      attachListeners(iframeDoc);
                      // Also watch for mutations inside the iframe
                      const iframeMutationObserver = new MutationObserver(iframeMutations => {
                        let hasIframeAddedNodes = false;
                        for (const iframeMutation of iframeMutations) {
                          if (iframeMutation.type === 'childList') {
                            iframeMutation.addedNodes.forEach(iframeNode => {
                              if (iframeNode.nodeType === Node.ELEMENT_NODE) {
                                console.log('[Iframe MutationObserver] Element added:', iframeNode.tagName);
                                attachListeners(iframeNode);
                                hasIframeAddedNodes = true;
                              }
                            });
                          }
                        }
                        if (hasIframeAddedNodes) {
                          assignWEBSPIndexesDebounced();
                        }
                      });
                      iframeMutationObserver.observe(iframeDoc.body, { childList: true, subtree: true });
                    }
                  } catch (iframeError) {
                    // Cross-origin iframes will throw errors - that's expected
                    console.log('[Iframe] Cannot access iframe content (cross-origin):', iframeError.message);
                  }
                };

                // Try immediately
                attachToIframe();

                // Also attach on load (in case it reloads or wasn't ready)
                node.addEventListener('load', attachToIframe);
              }
            }
          });
        }
      }
      // Reassign WEBSPindex after DOM changes (debounced to handle rapid injections)
      // Listeners will be attached automatically after WEBSP indexing completes
      if (hasAddedNodes) {
        assignWEBSPIndexesDebounced();
      }
    });
    mutationObserver.observe(document.body, { childList: true, subtree: true });
    console.log('Mutation observer started');
  } catch (error) {
    console.error('Error starting mutation observer:', error);
  }

  // try {
  //   // Observe DOM changes to capture dynamic updates
  //   startDomChangeTracking();
  //   console.log('DOM change tracking started');
  // } catch (error) {
  //   console.error('Error starting DOM change tracking:', error);
  // }
}

function stopRecording() {
  recording = false;
  if (mutationObserver) mutationObserver.disconnect();
  // if (domChangeObserver) domChangeObserver.disconnect();
  detachListeners(document);
  // pendingDomChanges = [];
  
  // Note: Recording state is managed by background.js
  console.log('Recording stopped');
}

function captureInitialFormStates() {
  const controls = document.querySelectorAll('input, select, textarea, [role="switch"]');
  const states = {};

  controls.forEach(el => {
    try {
      const selector = getSelectorPath(el);
      const type = el.type || el.getAttribute('role');
      const checked = el.checked || el.getAttribute('aria-checked') === 'true';
      const name = el.name || null;
      const value = el.value || el.getAttribute('value') || null;
      const semanticInfo = getSemanticInfo(el);

      states[selector] = {
        selectorPath: selector,
        xpath: getXPath(el),
        framePath: getFramePath(),
        type,
        name,
        value,
        checked,
        ...semanticInfo
      };
    } catch (error) {
      console.error('Error capturing state for element:', el, error);
    }
  });

  return states;
}

function attachListeners(root) {
  const timestamp = new Date().toISOString();
  console.log(`[attachListeners ${timestamp}] Called with:`, root.tagName || 'document', root.id || root.className);
  
  // Form controls - check root itself first, then children
  const inputSelector = 'input, select, textarea';
  const inputs = root.nodeType === Node.ELEMENT_NODE 
    ? [root, ...root.querySelectorAll(inputSelector)].filter(el => el.matches(inputSelector))
    : root.querySelectorAll(inputSelector);
  
  console.log(`[attachListeners ${timestamp}] Found ${inputs.length} form controls`);

  inputs.forEach(el => {
    // For checkboxes and radios, only listen to 'change' event (not 'input')
    // For text inputs, listen to both 'change' and 'input'
    const isCheckboxOrRadio = el.type === 'checkbox' || el.type === 'radio';
    
    el.addEventListener('change', recordEvent, true);
    if (!isCheckboxOrRadio) {
      el.addEventListener('input', recordEvent, true);
    }
  });
  
  // Custom toggles (role="switch", aria-checked, etc.) - separate handler
  const customToggleSelector = '[role="switch"], [aria-checked]';
  const customToggles = root.nodeType === Node.ELEMENT_NODE
    ? [root, ...root.querySelectorAll(customToggleSelector)].filter(el => el.matches(customToggleSelector))
    : root.querySelectorAll(customToggleSelector);
  
  console.log(`[attachListeners ${timestamp}] Found ${customToggles.length} custom toggles`);

  customToggles.forEach(el => {
    el.addEventListener('click', recordCustomToggle, true);
  });

  // ADDED: Click tracking for all clickable elements - check root itself first, then children
  const clickableSelector = 'a, button, [role="button"], [onclick], input[type="button"], input[type="submit"], input[type="reset"], input[type="image"]';
  const clickables = root.nodeType === Node.ELEMENT_NODE
    ? [root, ...root.querySelectorAll(clickableSelector)].filter(el => el.matches(clickableSelector))
    : root.querySelectorAll(clickableSelector);
  
  console.log(`[attachListeners ${timestamp}] Found ${clickables.length} clickable elements`);
  
  clickables.forEach(el => {
    const webspIndex = el.getAttribute('data-websp-index');
    console.log(`[attachListeners ${timestamp}] Attaching to:`, el.tagName,
      `websp-index: ${webspIndex || 'none'}`,
      `id: ${el.id || 'none'}`,
      `class: ${el.className || 'none'}`);
    el.addEventListener('click', recordClick, true);
    el.addEventListener('mousedown', recordMousedown, true);
    el.addEventListener('pointerdown', recordPointerdown, true); // CRITICAL for modern sites

    // Store reference for verification
    if (webspIndex === '29') {
      console.log(`[attachListeners ${timestamp}] ⭐ CRITICAL BUTTON 29 - Storing reference`, el);
      window.__debugButton29 = el;
    }
  });

  // ADDED: General click tracking on document for any missed elements
  // Allow attachment to any document node (including iframe documents)
  if (root.nodeType === Node.DOCUMENT_NODE) {
    root.addEventListener('click', recordGeneralClick, true);
    root.addEventListener('mousedown', recordGeneralMousedown, true);
    root.addEventListener('pointerdown', recordGeneralPointerdown, true); // CRITICAL for modern sites
  }

  console.log(`[attachListeners ${timestamp}] ✅ Complete - Attached listeners to ${inputs.length} inputs, ${customToggles.length} toggles, ${clickables.length} clickables`);
}

function detachListeners(root) {
  const inputs = root.querySelectorAll('input, select, textarea');
  inputs.forEach(el => {
    el.removeEventListener('change', recordEvent, true);
    el.removeEventListener('input', recordEvent, true);
  });
  
  const customToggles = root.querySelectorAll('[role="switch"], [aria-checked]');
  customToggles.forEach(el => {
    el.removeEventListener('click', recordCustomToggle, true);
  });

  const clickables = root.querySelectorAll('a, button, [role="button"], [onclick], input[type="button"], input[type="submit"], input[type="reset"], input[type="image"]');
  clickables.forEach(el => {
    el.removeEventListener('click', recordClick, true);
    el.removeEventListener('mousedown', recordMousedown, true);
    el.removeEventListener('pointerdown', recordPointerdown, true);
  });

  if (root.nodeType === Node.DOCUMENT_NODE) {
    root.removeEventListener('click', recordGeneralClick, true);
    root.removeEventListener('mousedown', recordGeneralMousedown, true);
    root.removeEventListener('pointerdown', recordGeneralPointerdown, true);
  }
}

function recordEvent(e) {
  if (!recording) return;

  try {
    // Capture target immediately before it's recycled
    const target = e.target;
    
    // Check for duplicate event
    if (isRecentClick(target)) {
      console.log('Change event skipped (duplicate):', getSelectorPath(target));
      return;
    }
    
    // Mark this element as recently changed
    recentInteractions.set(getSelectorPath(target), Date.now());
    
    const type = target.type || target.getAttribute('role');
    const isCheckbox = type === 'checkbox';
    const isRadio = type === 'radio';
    const isSwitch = type === 'switch' || target.getAttribute('role') === 'switch';
    
    // Synchronously capture identity data before any async delays
    const selectorPath = getSelectorPath(target);
    const xpath = getXPath(target);
    const framePath = getFramePath();
    const webspIndex = findWebspIndex(target, e);
    const formSelector = target.form ? getSelectorPath(target.form) : null;
    const outerHTML = safeOuterHTML(target);
    const innerHTML = safeInnerHTML(target);
    const targetOnClick = getOnClickSource(target);
    const semanticInfo = getSemanticInfo(target);

    // Additional context for switches/toggles (must be captured before potential detach)
    let switchContext = {};
    if (isCheckbox || isRadio || isSwitch || target.getAttribute('role') === 'switch') {
      switchContext = getSwitchContext(target);
    }

    // Small delay to allow DOM changes to propagate
    setTimeout(() => {
      // Detect checked state with multiple methods
      let checkedState = undefined;
      if (isCheckbox || isRadio || isSwitch) {
        // Primary method: check the element's checked property or aria-checked
        checkedState = target.checked || target.getAttribute('aria-checked') === 'true';

        // Additional detection: check parent label for validation/success classes
        // Some sites (like newsletter signups) use CSS classes on parent labels to indicate state
        const parentLabel = target.closest('label');
        if (parentLabel) {
          const labelClasses = parentLabel.className || '';

          // If parent has checked indicator classes, element is ON
          if (labelClasses.includes('validation-success') ||
              labelClasses.includes('is-checked')) {
            checkedState = true;
          }
          // If parent has explicit "checked"/"selected" classes, element is ON
          else if (labelClasses.includes('checked') || labelClasses.includes('selected')) {
            checkedState = true;
          }
          // If parent container exists but lacks success/checked classes, trust the element's state
          // (don't override unless we have positive indication)

          // Capture parent classes for replay to help with state verification
          switchContext.parentLabelClasses = labelClasses;
          switchContext.parentLabelSelector = getSelectorPath(parentLabel);
        }
      }

      const eventData = {
        type: 'change',
        timestamp: new Date().toISOString(),
        site: window.location.href,
        selectorPath: selectorPath,
        xpath: xpath,
        framePath: framePath,
        elementType: target.tagName.toLowerCase(),
        inputType: type,
        value: target.value || target.getAttribute('value') || null,
        checked: checkedState,
        webspIndex: webspIndex,
        formContext: {
          formSelector: formSelector,
          fieldName: target.name || null,
          groupName: (isRadio && target.name) ? target.name : null
        },
        // Extra labels for improved element identification
        outerHTML: outerHTML,
        innerHTML: innerHTML,
        targetOnClick: targetOnClick,
        ...semanticInfo,
        ...switchContext
      };

      chrome.runtime.sendMessage({ action: 'recordEvent', eventData });
      console.log('Event recorded:', eventData.type, eventData.selectorPath);
      console.log('Event recorded:', eventData);

      // Capture screenshot after form change, but avoid debouncing away toggle screenshots
      const isSwitchLike = isCheckbox || isRadio || isSwitch || target.getAttribute('role') === 'switch';
      if (!isSwitchLike) {
        captureScreenshot('change');
      }
    }, 100); // Small delay to ensure form value is captured
  } catch (error) {
    console.error('Error recording event:', error);
  }
}

// Handle visually custom toggles using aria-checked or role="switch"
function recordCustomToggle(e) {
  if (!recording) return;

  try {
    // Use composedPath to find switch element (handles shadow DOM)
    let target = getInteractiveTarget(e);

    // Verify it's actually a toggle/switch
    if (!target.matches('[role="switch"], [aria-checked], input[type="checkbox"]')) {
      // Search composedPath for a switch
      const path = e.composedPath();
      target = path.find(el => el instanceof Element &&
        el.matches('[role="switch"], [aria-checked], input[type="checkbox"]'));
    }

    if (!target) {
      console.log('Toggle not found in event path');
      return;
    }

    // Check for duplicate click
    if (isRecentClick(target)) {
      console.log('Toggle skipped (duplicate):', getSelectorPath(target));
      return;
    }
    
    // Mark this element as recently clicked
    recentInteractions.set(getSelectorPath(target), Date.now());

    // Capture element properties immediately
    const tagName = target.tagName.toLowerCase();
    const role = target.getAttribute('role');

    // Synchronously capture identity data before any async delays
    const selectorPath = getSelectorPath(target);
    const xpath = getXPath(target);
    const framePath = getFramePath();
    const webspIndex = findWebspIndex(target, e);
    const semanticInfo = getSemanticInfo(target);
    const switchContext = getSwitchContext(target);
    const outerHTML = safeOuterHTML(target);
    const innerHTML = safeInnerHTML(target);
    const targetOnClick = getOnClickSource(target);

    // Use requestAnimationFrame for better timing with state changes
    requestAnimationFrame(() => {
      setTimeout(() => {
        // Capture state after any click handlers and animations
        const checked = target.checked === true || target.getAttribute('aria-checked') === 'true';
        
        const eventData = {
          type: 'change',
          timestamp: new Date().toISOString(),
          site: window.location.href,
          selectorPath: selectorPath,
          xpath: xpath,
          framePath: framePath,
          elementType: tagName,
          inputType: role || 'switch',
          checked,
          value: null,
          webspIndex: webspIndex,
          formContext: { formSelector: null, fieldName: null, groupName: null },
          outerHTML: outerHTML,
          innerHTML: innerHTML,
          targetOnClick: targetOnClick,
          ...semanticInfo,
          ...switchContext
        };

        chrome.runtime.sendMessage({ action: 'recordEvent', eventData });
        console.log('[Switch] Custom toggle recorded:', eventData.selectorPath, 'checked:', checked, 'framePath:', eventData.framePath);

        // Capture screenshot after toggle
        captureScreenshot('toggle');
        
        // DOM snapshot commented out to reduce session file size
        // const snapshotEvent = {
        //   type: 'dom-snapshot',
        //   timestamp: new Date().toISOString(),
        //   html: document.documentElement.outerHTML,
        //   framePath: getFramePath()
        // };
        // chrome.runtime.sendMessage({ action: 'recordEvent', eventData: snapshotEvent });
      }, 100); // Increased delay to ensure state is fully updated
    });
  } catch (error) {
    console.error('Error recording custom toggle:', error);
  }
}

// Check if this interaction is a duplicate (event bubbling or mousedown+click on same element)
function isRecentClick(element) {
  const now = Date.now();
  const selector = getSelectorPath(element);
  
  // Clean up old entries
  for (const [key, timestamp] of recentInteractions.entries()) {
    if (now - timestamp > INTERACTION_DEDUPE_MS) {
      recentInteractions.delete(key);
    }
  }
  
  // Check if we recently recorded this element
  if (recentInteractions.has(selector)) {
    const timeSinceLastClick = now - recentInteractions.get(selector);
    console.log(`⏭️ [Deduplication] Skipping duplicate - ${selector} was clicked ${timeSinceLastClick}ms ago`);
    return true;
  }
  
  // Check if any parent was recently interacted with (to catch bubbling from child to parent)
  let parent = element.parentElement;
  let depth = 0;
  const MAX_DEPTH = 3; // Only check up to 3 levels to avoid performance issues
  
  while (parent && depth < MAX_DEPTH) {
    const parentSelector = getSelectorPath(parent);
    if (recentInteractions.has(parentSelector)) {
      return true;
    }
    parent = parent.parentElement;
    depth++;
  }
  
  return false;
}

// Calculate interactivity score for an element based on semantic richness
function getElementInteractivityScore(element) {
  let score = 0;

  const tagName = element.tagName?.toLowerCase();
  const role = element.getAttribute('role');
  const ariaLabel = element.getAttribute('aria-label');
  const ariaLabelledby = element.getAttribute('aria-labelledby');
  const ariaChecked = element.getAttribute('aria-checked');
  const hasOnClick = element.onclick || element.getAttribute('onclick');

  // High priority: Has explicit interactive role
  const interactiveRoles = ['button', 'switch', 'checkbox', 'radio', 'link', 'tab', 'menuitem', 'menuitemcheckbox', 'menuitemradio'];
  if (role && interactiveRoles.includes(role)) {
    score += 10;
  }

  // High priority: Has aria-label or aria-labelledby (indicates semantically rich element)
  if (ariaLabel || ariaLabelledby) {
    score += 5;
  }

  // Medium-high priority: Has aria-checked (indicates toggle/checkbox)
  if (ariaChecked !== null) {
    score += 4;
  }

  // Medium priority: Is a native interactive element
  const nativeInteractive = ['a', 'button', 'input', 'select', 'textarea'];
  if (nativeInteractive.includes(tagName)) {
    score += 5;
  }

  // Medium priority: Has onclick handler
  if (hasOnClick) {
    score += 3;
  }

  // Check if this is a custom element (has hyphen in tag name)
  const isCustomElement = tagName && tagName.includes('-');

  if (isCustomElement) {
    // Low priority: Is a custom element (likely interactive)
    score += 1;

    // Penalty: Custom element with NO semantic attributes (likely a shadow host)
    const hasSemanticAttributes = role || ariaLabel || ariaLabelledby || ariaChecked !== null;
    if (!hasSemanticAttributes) {
      score -= 5;
    }
  }

  // Bonus: Has tabindex (can receive focus)
  const tabindex = element.getAttribute('tabindex');
  if (tabindex !== null && parseInt(tabindex, 10) >= 0) {
    score += 2;
  }

  // Bonus: Has cursor pointer style
  if (element.style?.cursor === 'pointer') {
    score += 1;
  }

  return score;
}

// Get the actual interactive element from event, traversing through shadow DOM
function getInteractiveTarget(event) {
  const path = event.composedPath();
  const candidates = [];

  // Debug: Log ALL elements in composedPath
  console.log('[getInteractiveTarget] Full composedPath:', path.slice(0, 10).map(el => {
    if (!(el instanceof Element)) return el;
    return {
      tag: el.tagName,
      role: el.getAttribute?.('role'),
      ariaLabel: el.getAttribute?.('aria-label'),
      tabindex: el.getAttribute?.('tabindex'),
      id: el.id,
      classes: el.className
    };
  }));

  // Collect all potentially interactive elements from the composed path
  for (const element of path) {
    if (!(element instanceof Element)) continue;
    if (element === document || element === window) break;

    const tagName = element.tagName?.toLowerCase();
    const role = element.getAttribute('role');

    // IMPORTANT: Check if this element or any parent (within same shadow root) is interactive
    // This handles cases where click happens on a child element (e.g., SPAN inside faceplate-switch-input)
    let currentElement = element;
    let searchDepth = 0;
    const MAX_PARENT_SEARCH = 5;

    while (currentElement && searchDepth < MAX_PARENT_SEARCH) {
      const currentTag = currentElement.tagName?.toLowerCase();
      const currentRole = currentElement.getAttribute('role');

      // Check if current element appears interactive
      const isInteractive =
        // Native interactive elements
        ['a', 'button', 'input', 'select', 'textarea'].includes(currentTag) ||
        // Interactive roles (including 'option' for selectable list items)
        (currentRole && ['button', 'switch', 'checkbox', 'radio', 'link', 'tab', 'menuitem', 'menuitemcheckbox', 'menuitemradio', 'option'].includes(currentRole)) ||
        // Elements with aria-selected (selectable options)
        currentElement.hasAttribute('aria-selected') ||
        // Elements with click handlers
        currentElement.onclick || currentElement.getAttribute('onclick') ||
        // Elements that look clickable
        (currentElement.style?.cursor === 'pointer' && currentElement.getAttribute('tabindex') !== null) ||
        // Custom elements with tabindex (likely interactive even with pointer-events: none)
        (currentTag && currentTag.includes('-') && currentElement.getAttribute('tabindex') !== null);

      if (isInteractive) {
        // Still check basic visibility/enabled status
        if (currentElement.disabled || currentElement.type === 'hidden') {
          console.log('[getInteractiveTarget] Filtered out (disabled/hidden):', currentElement.tagName, currentElement.getAttribute('role'));
          break; // Stop searching parents
        }

        // Check if element is completely hidden
        try {
          const style = window.getComputedStyle(currentElement);
          if (style.display === 'none' || style.visibility === 'hidden') {
            console.log('[getInteractiveTarget] Filtered out (not visible):', currentElement.tagName, currentElement.getAttribute('role'));
            break; // Stop searching parents
          }
          // Note: We don't filter out pointer-events: none because the actual element
          // might have pointer-events: none but still be the interactive target
        } catch (e) {
          // If we can't get style, include it
        }

        const score = getElementInteractivityScore(currentElement);
        console.log('[getInteractiveTarget] Adding candidate:', currentElement.tagName, 'role:', currentElement.getAttribute('role'), 'score:', score);
        candidates.push({ element: currentElement, score });
        break; // Found an interactive element, stop searching parents
      }

      // Special handling for labels - if we clicked a label, we probably mean the input
      if (currentTag === 'label') {
         const forId = currentElement.getAttribute('for');
         let input;
         if (forId) {
            // Try to find by ID (globally)
            input = document.getElementById(forId);
            // If not found globally, try in same shadow root if applicable
            if (!input && currentElement.getRootNode() instanceof ShadowRoot) {
               input = currentElement.getRootNode().getElementById(forId);
            }
         } else {
            // Nested input
            input = currentElement.querySelector('input, select, textarea');
         }

         if (input && !input.disabled) {
            console.log('[getInteractiveTarget] Found input for label:', input.tagName, input.type);
            const inputScore = getElementInteractivityScore(input) + 5; // Boost score for label-associated input
            candidates.push({ element: input, score: inputScore });
            break; // Found the real target
         }
      }

      // Move to parent, but stop at shadow root boundaries
      const parent = currentElement.parentElement;
      if (!parent || parent.nodeType === Node.DOCUMENT_FRAGMENT_NODE) {
        break; // Reached shadow root boundary
      }
      currentElement = parent;
      searchDepth++;
    }
  }

  // If we found candidates, return the one with highest score
  if (candidates.length > 0) {
    // Sort by score (highest first)
    candidates.sort((a, b) => b.score - a.score);

    // Debug: log the candidates and scores
    console.log('[getInteractiveTarget] Candidates:', candidates.map(c => ({
      tag: c.element.tagName,
      id: c.element.id,
      role: c.element.getAttribute('role'),
      ariaLabel: c.element.getAttribute('aria-label'),
      webspIndex: c.element.webspIndex,
      score: c.score
    })));

    return candidates[0].element;
  }

  // Fallback to target
  return event.target;
}

// Find the WEBSP index for an element, checking the element itself, event path, and parents
function findWebspIndex(element, event) {
  if (!element) return null;

  try {
    // 1. Check the target element itself for webspIndex property or data-websp-index attribute
    if (element.webspIndex) {
      return element.webspIndex;
    }
    const directIndex = element.getAttribute('data-websp-index');
    if (directIndex) {
      return parseInt(directIndex, 10);
    }

    // 2. Search the event's composedPath() for elements with webspIndex
    // This finds clicked children/descendants without the "multiple buttons" problem
    // because we only check elements that were actually in the click path
    if (event && event.composedPath) {
      const path = event.composedPath();
      for (const pathElement of path) {
        if (!(pathElement instanceof Element)) continue;
        if (pathElement === document || pathElement === window) break;

        // Check property first
        if (pathElement.webspIndex) {
          return pathElement.webspIndex;
        }
        // Check attribute as fallback
        const pathIndex = pathElement.getAttribute('data-websp-index');
        if (pathIndex) {
          return parseInt(pathIndex, 10);
        }
      }
    }

    // 3. Fall back to traversing up the DOM tree to find parent elements with webspIndex
    // This handles cases where the interactive element doesn't have the index but its parent does
    let parent = element.parentElement;
    let depth = 0;
    const MAX_PARENT_DEPTH = 5; // Limit traversal to avoid performance issues

    while (parent && depth < MAX_PARENT_DEPTH) {
      // Check property
      if (parent.webspIndex) {
        return parent.webspIndex;
      }
      // Check attribute
      const parentIndex = parent.getAttribute('data-websp-index');
      if (parentIndex) {
        return parseInt(parentIndex, 10);
      }

      parent = parent.parentElement;
      depth++;
    }
  } catch (error) {
    console.error('Error finding WEBSP index:', error);
  }

  return null;
}

// Check if element is truly interactive (not disabled, hidden, or placeholder)
function isElementInteractive(element) {
  // Check if element is disabled
  if (element.disabled) return false;

  // Check if input is hidden type
  if (element.type === 'hidden') return false;

  // Check tabindex - negative means not interactive/not focusable (placeholder element)
  const tabindex = element.getAttribute('tabindex');
  if (tabindex !== null) {
    const tabindexValue = parseInt(tabindex, 10);
    if (!isNaN(tabindexValue) && tabindexValue < 0) return false;
  }

  // Check if element is visible
  try {
    const style = window.getComputedStyle(element);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    if (style.opacity === '0' && style.pointerEvents === 'none') return false;
  } catch (e) {
    // If we can't get computed style, assume visible
  }

  return true;
}

// Check if we should ignore click/mousedown for this element (because it's handled by change event)
function shouldIgnoreClickForElement(element) {
  if (!element) return false;
  const tagName = element.tagName.toLowerCase();
  const type = element.type;
  // Ignore native radio and checkbox inputs - they fire 'change' events which we already capture
  // Capturing click/mousedown for them is redundant and often lacks the correct 'checked' state
  if (tagName === 'input' && (type === 'radio' || type === 'checkbox')) {
    return true;
  }
  return false;
}

// ADDED: Record mousedown - fires before click, preventing issues with elements that vanish on click
function recordMousedown(e) {
  console.log('🔵 [recordMousedown] HANDLER CALLED - recording:', recording, 'target:', e.target);
  if (!recording) return;

  try {
    // DEBUG: Log what we're capturing
    console.log('[recordMousedown] e.target:', e.target.tagName, e.target.id || e.target.className);
    console.log('[recordMousedown] e.currentTarget:', e.currentTarget.tagName, e.currentTarget.id || e.currentTarget.className);

    // Use getInteractiveTarget to find the actual interactive element (handles shadow DOM)
    let target = getInteractiveTarget(e);

    console.log('[recordMousedown] Interactive target found:', target.tagName, target.id || target.className);
    console.log('[recordMousedown] Interactive target found:', target);

    // ADDED: Ignore native radio/checkbox (handled by change event)
    if (shouldIgnoreClickForElement(target)) {
      console.log('Mousedown skipped for radio/checkbox (handled by change):', getSelectorPath(target));
      return;
    }

    // Check for duplicate click
    if (isRecentClick(target)) {
      console.log('Mousedown skipped (duplicate):', getSelectorPath(target));
      return;
    }

    // Mark this element as recently clicked to prevent click handler from also firing
    recentInteractions.set(getSelectorPath(target), Date.now());

    // Capture element info immediately and synchronously
    const href = target.href || null;
    const tagName = target.tagName.toLowerCase();
    const form = target.form;
    const name = target.name || null;
    const semanticInfo = getSemanticInfo(target);

    // Synchronously capture identity data before the element potentially vanishes
    const selectorPath = getSelectorPath(target);
    const xpath = getXPath(target);
    const framePath = getFramePath();
    const webspIndex = findWebspIndex(target, e);
    const formSelector = form ? getSelectorPath(form) : null;
    const outerHTML = safeOuterHTML(target);
    const innerHTML = safeInnerHTML(target);
    const targetOnClick = getOnClickSource(target);

    // Check if this is a toggle button
    // Type 1: aria-pressed or aria-selected (traditional toggle)
    const hasAriaToggle = target.hasAttribute('aria-pressed') ||
                          target.hasAttribute('aria-selected') ||
                          target.getAttribute('role') === 'switch';

    // Type 2: State indicated by aria-label text (Google Ad Center style)
    const ariaLabel = target.getAttribute('aria-label') || '';
    const isGoogleStyleToggle = ariaLabel.includes('Get more ads about:') ||
                                ariaLabel.includes('See fewer ads about:');

    const isToggleButton = hasAriaToggle || isGoogleStyleToggle;

    // Capture current toggle state (before the click changes it)
    let toggleState = false;
    if (hasAriaToggle) {
      toggleState = target.getAttribute('aria-pressed') === 'true' ||
                   target.getAttribute('aria-selected') === 'true';
    } else if (isGoogleStyleToggle) {
      toggleState = ariaLabel.includes('See fewer');
    }

    const eventData = {
      type: 'click',
      timestamp: new Date().toISOString(),
      site: window.location.href,
      selectorPath: selectorPath,
      xpath: xpath,
      framePath: framePath,
      elementType: tagName,
      href: href,
      webspIndex: webspIndex,
      formContext: {
        formSelector: formSelector,
        fieldName: name,
        groupName: null
      },
      outerHTML: outerHTML,
      innerHTML: innerHTML,
      targetOnClick: targetOnClick,
      // Add toggle state if this is a toggle button
      ...(isToggleButton && {
        isToggle: true,
        toggleState: toggleState,
        toggleType: hasAriaToggle ? 'aria-toggle' : 'google-ad-center'
      }),
      ...semanticInfo
    };

    chrome.runtime.sendMessage({ action: 'recordEvent', eventData });
    console.log('✅ [recordMousedown] Event saved - Selector:', eventData.selectorPath, 'ID:', eventData.id, 'Tag:', eventData.elementType);
    console.log('eventData', eventData)

    // ADDED: Capture screenshot after mousedown
    captureScreenshot('click');
  } catch (error) {
    console.error('Error recording mousedown:', error);
  }
}

// ADDED: Record pointerdown - CRITICAL for modern sites that use pointer events
function recordPointerdown(e) {
  console.log('🔵 [recordPointerdown] HANDLER CALLED - recording:', recording, 'target:', e.target);
  if (!recording) return;

  try {
    // DEBUG: Log what we're capturing
    console.log('[recordPointerdown] e.target:', e.target.tagName, e.target.id || e.target.className);
    console.log('[recordPointerdown] e.currentTarget:', e.currentTarget.tagName, e.currentTarget.id || e.currentTarget.className);

    // Use getInteractiveTarget to find the actual interactive element (handles shadow DOM)
    let target = getInteractiveTarget(e);

    console.log('[recordPointerdown] Interactive target found:', target.tagName, target.id || target.className);
    console.log('[recordPointerdown] Interactive target found:', target);

    // ADDED: Ignore native radio/checkbox (handled by change event)
    if (shouldIgnoreClickForElement(target)) {
      console.log('Pointerdown skipped for radio/checkbox (handled by change):', getSelectorPath(target));
      return;
    }

    // Check for duplicate
    if (isRecentClick(target)) {
      console.log('Pointerdown skipped (duplicate):', getSelectorPath(target));
      return;
    }

    // Mark this element as recently clicked
    recentInteractions.set(getSelectorPath(target), Date.now());

    // Capture element info immediately and synchronously
    const href = target.href || null;
    const tagName = target.tagName.toLowerCase();
    const form = target.form;
    const name = target.name || null;
    const semanticInfo = getSemanticInfo(target);

    // Synchronously capture identity data before the element potentially vanishes
    const selectorPath = getSelectorPath(target);
    const xpath = getXPath(target);
    const framePath = getFramePath();
    const webspIndex = findWebspIndex(target, e);
    const formSelector = form ? getSelectorPath(form) : null;
    const outerHTML = safeOuterHTML(target);
    const innerHTML = safeInnerHTML(target);
    const targetOnClick = getOnClickSource(target);

    // Check if this is a toggle button
    const hasAriaToggle = target.hasAttribute('aria-pressed') ||
                          target.hasAttribute('aria-selected') ||
                          target.getAttribute('role') === 'switch';

    const ariaLabel = target.getAttribute('aria-label') || '';
    const isGoogleStyleToggle = ariaLabel.includes('Get more ads about:') ||
                                ariaLabel.includes('See fewer ads about:');

    const isToggleButton = hasAriaToggle || isGoogleStyleToggle;

    // Capture current toggle state
    let toggleState = false;
    if (hasAriaToggle) {
      toggleState = target.getAttribute('aria-pressed') === 'true' ||
                   target.getAttribute('aria-selected') === 'true';
    } else if (isGoogleStyleToggle) {
      toggleState = ariaLabel.includes('See fewer');
    }

    const eventData = {
      type: 'click',
      timestamp: new Date().toISOString(),
      site: window.location.href,
      selectorPath: selectorPath,
      xpath: xpath,
      framePath: framePath,
      elementType: tagName,
      href: href,
      webspIndex: webspIndex,
      formContext: {
        formSelector: formSelector,
        fieldName: name,
        groupName: null
      },
      outerHTML: outerHTML,
      innerHTML: innerHTML,
      targetOnClick: targetOnClick,
      ...(isToggleButton && {
        isToggle: true,
        toggleState: toggleState,
        toggleType: hasAriaToggle ? 'aria-toggle' : 'google-ad-center'
      }),
      ...semanticInfo
    };

    chrome.runtime.sendMessage({ action: 'recordEvent', eventData });
    console.log('✅ [recordPointerdown] Event saved - Selector:', eventData.selectorPath, 'ID:', eventData.id, 'Tag:', eventData.elementType);
    console.log('eventData', eventData)

    // Capture screenshot
    captureScreenshot('click');
  } catch (error) {
    console.error('Error recording pointerdown:', error);
  }
}

// ADDED: Record general clicks
function recordClick(e) {
  console.log('🔵 [recordClick] HANDLER CALLED - recording:', recording, 'target:', e.target);
  if (!recording) return;

  try {
    // DEBUG: Log what we're capturing
    console.log('[recordClick] e.target:', e.target.tagName, e.target.id || e.target.className);
    console.log('[recordClick] e.currentTarget:', e.currentTarget.tagName, e.currentTarget.id || e.currentTarget.className);
    
    // Use getInteractiveTarget to find the actual interactive element (handles shadow DOM)
    let target = getInteractiveTarget(e);

    console.log('[recordClick] Interactive target found:', target.tagName, target.id || target.className);

    // ADDED: Ignore native radio/checkbox (handled by change event)
    if (shouldIgnoreClickForElement(target)) {
      console.log('Click skipped for radio/checkbox (handled by change):', getSelectorPath(target));
      return;
    }

    // Check for duplicate click (skip if mousedown already recorded this)
    console.log('[recordClick] Interactive target found:', target.tagName, target.id || target.className);

    // Check for duplicate click
    if (isRecentClick(target)) {
      console.log('✋ [recordClick] Skipped (duplicate - mousedown already recorded):', getSelectorPath(target));
      return;
    }
    
    // Mark this element as recently clicked
    recentInteractions.set(getSelectorPath(target), Date.now());

    // Capture element info immediately
    const href = target.href || null;
    const tagName = target.tagName.toLowerCase();
    const form = target.form;
    const name = target.name || null;
    const semanticInfo = getSemanticInfo(target);

    // Synchronously capture identity data before any async delays
    // This ensures we handle cases where the element is removed from DOM immediately (e.g., modal close)
    const selectorPath = getSelectorPath(target);
    const xpath = getXPath(target);
    const framePath = getFramePath();
    const webspIndex = findWebspIndex(target, e);
    const formSelector = form ? getSelectorPath(form) : null;
    const outerHTML = safeOuterHTML(target);
    const innerHTML = safeInnerHTML(target);
    const targetOnClick = getOnClickSource(target);

    // Check if this is a toggle button
    // Type 1: aria-pressed, aria-selected, or aria-checked (traditional toggle)
    // Also check for menuitemradio/menuitemcheckbox roles (they use aria-checked)
    const targetRole = target.getAttribute('role');
    let hasAriaToggle = target.hasAttribute('aria-pressed') ||
                        target.hasAttribute('aria-selected') ||
                        target.hasAttribute('aria-checked') ||
                        targetRole === 'switch' ||
                        targetRole === 'menuitemradio' ||
                        targetRole === 'menuitemcheckbox';

    // Check parent elements for aria-selected/aria-checked (handles clicks on child divs inside <li role="option"> or <li role="menuitemradio">)
    if (!hasAriaToggle) {
      let parent = target.parentElement;
      let depth = 0;
      while (parent && depth < 3) {
        const parentRole = parent.getAttribute('role');
        if (parent.hasAttribute('aria-selected') ||
            parent.hasAttribute('aria-checked') ||
            parent.hasAttribute('aria-pressed') ||
            parentRole === 'option' ||
            parentRole === 'menuitemradio' ||
            parentRole === 'menuitemcheckbox') {
          hasAriaToggle = true;
          // Update target to the parent element with the state attribute
          target = parent;
          break;
        }
        parent = parent.parentElement;
        depth++;
      }
    }
    
    // Type 2: State indicated by aria-label text (Google Ad Center style)
    const ariaLabel = target.getAttribute('aria-label') || '';
    const isGoogleStyleToggle = ariaLabel.includes('Get more ads about:') || 
                                ariaLabel.includes('See fewer ads about:');
    
    const isToggleButton = hasAriaToggle || isGoogleStyleToggle;
    
    // Check if this click will cause navigation
    const willNavigate = href && !href.startsWith('#') && !href.startsWith('javascript:');
    
    // For navigation clicks, capture immediately without delay
    // For toggle buttons, use small delay to capture state after toggle
    const delay = (isToggleButton && !willNavigate) ? 50 : 0;
    
    // Define the recording logic as a function to be called either immediately or after delay
    const sendEvent = () => {
      // Re-check toggle state after delay (if applicable)
      let toggleState = false;
      if (hasAriaToggle) {
        toggleState = target.getAttribute('aria-pressed') === 'true' || 
                     target.getAttribute('aria-selected') === 'true' ||
                     target.getAttribute('aria-checked') === 'true';
      } else if (isGoogleStyleToggle) {
        toggleState = ariaLabel.includes('See fewer');
      }
      
      const eventData = {
        type: 'click',
        timestamp: new Date().toISOString(),
        site: window.location.href,
        selectorPath: selectorPath,
        xpath: xpath,
        framePath: framePath,
        elementType: tagName,
        href: href,
        webspIndex: webspIndex,
        formContext: {
          formSelector: formSelector,
          fieldName: name,
          groupName: null
        },
        outerHTML: outerHTML,
        innerHTML: innerHTML,
        targetOnClick: targetOnClick,
        // Add toggle state if this is a toggle button
        ...(isToggleButton && {
          isToggle: true,
          toggleState: toggleState,
          toggleType: hasAriaToggle ? 'aria-toggle' : 'google-ad-center'
        }),
        ...semanticInfo
      };

      chrome.runtime.sendMessage({ action: 'recordEvent', eventData });
      console.log('✅ [recordClick] Event saved - Selector:', eventData.selectorPath, 'ID:', eventData.id, 'Tag:', eventData.elementType);
      console.log('eventData', eventData)

      // ADDED: Capture screenshot after click
      captureScreenshot('click');
    };

    // Execute immediately if no delay is needed (CRITICAL for buttons that close modals/iframes)
    if (delay === 0) {
      sendEvent();
    } else {
      setTimeout(sendEvent, delay);
    }
  } catch (error) {
    console.error('Error recording click:', error);
  }
}

// ADDED: Record general mousedown that might not be on specific elements
function recordGeneralMousedown(e) {
  console.log('🔵 [recordGeneralMousedown] HANDLER CALLED - recording:', recording, 'target:', e.target);
  if (!recording) return;

  console.log('[recordGeneralMousedown] e.target:', e.target.tagName, e.target.id || e.target.className);

  // Use getInteractiveTarget to find the actual interactive element (handles shadow DOM)
  let target = getInteractiveTarget(e);

  console.log('[recordGeneralMousedown] Interactive target found:', target.tagName, target.id || target.className);

  // ADDED: Ignore native radio/checkbox (handled by change event)
  if (shouldIgnoreClickForElement(target)) {
    console.log('General mousedown skipped for radio/checkbox (handled by change):', getSelectorPath(target));
    return;
  }

  // Check if this is a switch/toggle element
  if (target.matches('[role="switch"], [aria-checked], input[type="checkbox"][role="switch"]')) {
    console.log('[recordGeneralMousedown] Detected as switch element');

    // De-dup
    if (isRecentClick(target)) {
      console.log('General mousedown (switch) skipped (duplicate):', getSelectorPath(target));
      return;
    }
    recentInteractions.set(getSelectorPath(target), Date.now());

    // Synchronously capture identity data and current state
    const selectorPath = getSelectorPath(target);
    const xpath = getXPath(target);
    const framePath = getFramePath();
    const webspIndex = findWebspIndex(target, e);
    const semanticInfo = getSemanticInfo(target);
    const switchContext = getSwitchContext(target);
    const outerHTML = safeOuterHTML(target);
    const innerHTML = safeInnerHTML(target);
    const targetOnClick = getOnClickSource(target);
    const tagName = (target.tagName || '').toLowerCase();
    const role = target.getAttribute('role') || 'switch';
    const checked = (target.checked === true) || (target.getAttribute('aria-checked') === 'true');

    try {
      const eventData = {
        type: 'change',
        timestamp: new Date().toISOString(),
        site: window.location.href,
        selectorPath: selectorPath,
        xpath: xpath,
        framePath: framePath,
        elementType: tagName,
        inputType: role,
        checked,
        value: null,
        webspIndex: webspIndex,
        formContext: { formSelector: null, fieldName: null, groupName: null },
        outerHTML: outerHTML,
        innerHTML: innerHTML,
        targetOnClick: targetOnClick,
        ...semanticInfo,
        ...switchContext
      };

      chrome.runtime.sendMessage({ action: 'recordEvent', eventData });
      console.log('✅ [recordGeneralMousedown] Switch change saved - Selector:', eventData.selectorPath, 'Checked:', checked);
      console.log('✅ [recordGeneralMousedown] Switch change saved - Selector:', eventData);

      captureScreenshot('toggle');
    } catch (err2) {
      console.error('Error recording mapped switch:', err2);
    }
    return;
  }

  console.log('[recordGeneralMousedown] Final target:', target.tagName, target.id || target.className);

  // Check for duplicate click
  if (isRecentClick(target)) {
    console.log('General mousedown skipped (duplicate):', getSelectorPath(target));
    return;
  }

  // Mark this element as recently clicked
  recentInteractions.set(getSelectorPath(target), Date.now());

  // Capture element info immediately and synchronously
  const tagName = target.tagName.toLowerCase();
  const href = target.href || null;
  const semanticInfo = getSemanticInfo(target);

  try {
    const eventData = {
      type: 'click',
      timestamp: new Date().toISOString(),
      site: window.location.href,
      selectorPath: getSelectorPath(target),
      xpath: getXPath(target),
      framePath: getFramePath(),
      elementType: tagName,
      href: href,
      webspIndex: findWebspIndex(target, e),
      formContext: {
        formSelector: null,
        fieldName: null,
        groupName: null
      },
      outerHTML: safeOuterHTML(target),
      innerHTML: safeInnerHTML(target),
      targetOnClick: getOnClickSource(target),
      ...semanticInfo
    };

    chrome.runtime.sendMessage({ action: 'recordEvent', eventData });
    console.log('✅ [recordGeneralMousedown] Event saved - Type:', eventData.type, 'Selector:', eventData.selectorPath, 'Tag:', eventData.elementType);
    console.log('✅ [recordGeneralMousedown] Full event:', eventData);

    // ADDED: Capture screenshot after mousedown
    captureScreenshot('click');
  } catch (error) {
    console.error('Error recording general mousedown:', error);
  }
}

// ADDED: Record general pointerdown - CRITICAL for modern sites
function recordGeneralPointerdown(e) {
  console.log('🔵 [recordGeneralPointerdown] HANDLER CALLED - recording:', recording, 'target:', e.target);
  if (!recording) return;

  console.log('[recordGeneralPointerdown] e.target:', e.target.tagName, e.target.id || e.target.className);

  // Use getInteractiveTarget to find the actual interactive element
  let target = getInteractiveTarget(e);

  console.log('[recordGeneralPointerdown] Interactive target found:', target.tagName, target.id || target.className);

  // ADDED: Ignore native radio/checkbox (handled by change event)
  if (shouldIgnoreClickForElement(target)) {
    console.log('General pointerdown skipped for radio/checkbox (handled by change):', getSelectorPath(target));
    return;
  }

  // Check if this is a switch/toggle element
  if (target.matches('[role="switch"], [aria-checked], input[type="checkbox"][role="switch"]')) {
    console.log('[recordGeneralPointerdown] Detected as switch element');

    if (isRecentClick(target)) {
      console.log('General pointerdown (switch) skipped (duplicate):', getSelectorPath(target));
      return;
    }
    recentInteractions.set(getSelectorPath(target), Date.now());

    const selectorPath = getSelectorPath(target);
    const xpath = getXPath(target);
    const framePath = getFramePath();
    const webspIndex = findWebspIndex(target, e);
    const semanticInfo = getSemanticInfo(target);
    const switchContext = getSwitchContext(target);
    const outerHTML = safeOuterHTML(target);
    const innerHTML = safeInnerHTML(target);
    const targetOnClick = getOnClickSource(target);
    const tagName = (target.tagName || '').toLowerCase();
    const role = target.getAttribute('role') || 'switch';
    const checked = (target.checked === true) || (target.getAttribute('aria-checked') === 'true');

    try {
      const eventData = {
        type: 'change',
        timestamp: new Date().toISOString(),
        site: window.location.href,
        selectorPath: selectorPath,
        xpath: xpath,
        framePath: framePath,
        elementType: tagName,
        inputType: role,
        checked,
        value: null,
        webspIndex: webspIndex,
        formContext: { formSelector: null, fieldName: null, groupName: null },
        outerHTML: outerHTML,
        innerHTML: innerHTML,
        targetOnClick: targetOnClick,
        ...semanticInfo,
        ...switchContext
      };

      chrome.runtime.sendMessage({ action: 'recordEvent', eventData });
      console.log('✅ [recordGeneralPointerdown] Switch change saved - Selector:', eventData.selectorPath, 'Checked:', checked);

      captureScreenshot('toggle');
    } catch (err2) {
      console.error('Error recording switch:', err2);
    }
    return;
  }

  console.log('[recordGeneralPointerdown] Final target:', target.tagName, target.id || target.className);

  if (isRecentClick(target)) {
    console.log('General pointerdown skipped (duplicate):', getSelectorPath(target));
    return;
  }

  recentInteractions.set(getSelectorPath(target), Date.now());

  const tagName = target.tagName.toLowerCase();
  const href = target.href || null;
  const semanticInfo = getSemanticInfo(target);

  try {
    const eventData = {
      type: 'click',
      timestamp: new Date().toISOString(),
      site: window.location.href,
      selectorPath: getSelectorPath(target),
      xpath: getXPath(target),
      framePath: getFramePath(),
      elementType: tagName,
      href: href,
      webspIndex: findWebspIndex(target, e),
      formContext: {
        formSelector: null,
        fieldName: null,
        groupName: null
      },
      outerHTML: safeOuterHTML(target),
      innerHTML: safeInnerHTML(target),
      targetOnClick: getOnClickSource(target),
      ...semanticInfo
    };

    chrome.runtime.sendMessage({ action: 'recordEvent', eventData });
    console.log('✅ [recordGeneralPointerdown] Event saved - Type:', eventData.type, 'Selector:', eventData.selectorPath, 'Tag:', eventData.elementType);
    console.log('✅ [recordGeneralPointerdown] Full event:', eventData);

    captureScreenshot('click');
  } catch (error) {
    console.error('Error recording general pointerdown:', error);
  }
}

// ADDED: Record general clicks that might not be on specific elements
function recordGeneralClick(e) {
  console.log('🔵 [recordGeneralClick] HANDLER CALLED - recording:', recording, 'target:', e.target);
  if (!recording) return;
  
  console.log('[recordGeneralClick] e.target:', e.target.tagName, e.target.id || e.target.className);
  
  // Use getInteractiveTarget to find the actual interactive element (handles shadow DOM)
  let target = getInteractiveTarget(e);

  console.log('[recordGeneralClick] Interactive target found:', target.tagName, target.id || target.className);
  
  // ADDED: Ignore native radio/checkbox (handled by change event)
  if (shouldIgnoreClickForElement(target)) {
    console.log('General click skipped for radio/checkbox (handled by change):', getSelectorPath(target));
    return;
  }

  // Check if this is a switch/toggle element (including role="option", "menuitemradio", "menuitemcheckbox" with aria-selected/aria-checked)
  // Also check parent elements for aria-selected/aria-checked (e.g., <li role="option" aria-selected="true"> or <li role="menuitemradio" aria-checked="true">)
  let isSwitchElement = target.matches('[role="switch"], [role="menuitemradio"], [role="menuitemcheckbox"], [aria-checked], [aria-selected], input[type="checkbox"][role="switch"]');
  if (!isSwitchElement) {
    // Check parent elements for aria-selected/aria-checked
    let parent = target.parentElement;
    let depth = 0;
    while (parent && depth < 3) {
      const parentRole = parent.getAttribute('role');
      if (parent.hasAttribute('aria-selected') ||
          parent.hasAttribute('aria-checked') ||
          parent.hasAttribute('aria-pressed') ||
          parentRole === 'option' ||
          parentRole === 'menuitemradio' ||
          parentRole === 'menuitemcheckbox') {
        isSwitchElement = true;
        target = parent;
        break;
      }
      parent = parent.parentElement;
      depth++;
    }
  }

  if (isSwitchElement) {
    console.log('[recordGeneralClick] Detected as switch element');
    
    // De-dup
    if (isRecentClick(target)) {
      console.log('✋ [recordGeneralClick] Switch skipped (duplicate - mousedown already recorded):', getSelectorPath(target));
      return;
    }
    recentInteractions.set(getSelectorPath(target), Date.now());

    // Synchronously capture identity data before any async delays
    const selectorPath = getSelectorPath(target);
    const xpath = getXPath(target);
    const framePath = getFramePath();
    const webspIndex = findWebspIndex(target, e);
    const semanticInfo = getSemanticInfo(target);
    const switchContext = getSwitchContext(target);
    const outerHTML = safeOuterHTML(target);
    const innerHTML = safeInnerHTML(target);
    const targetOnClick = getOnClickSource(target);
    
    // Delay slightly to read updated checked/aria-checked/aria-selected state after click
    setTimeout(() => {
      try {
        const tagName = (target.tagName || '').toLowerCase();
        const role = target.getAttribute('role') || 'switch';
        const checked = (target.checked === true) ||
                       (target.getAttribute('aria-checked') === 'true') ||
                       (target.getAttribute('aria-selected') === 'true') ||
                       (target.getAttribute('aria-pressed') === 'true');
        const semanticInfo = getSemanticInfo(target);
        const switchContext = getSwitchContext(target);

        const eventData = {
          type: 'change',
          timestamp: new Date().toISOString(),
          site: window.location.href,
          selectorPath: selectorPath,
          xpath: xpath,
          framePath: framePath,
          elementType: tagName,
          inputType: role,
          checked,
          value: null,
          webspIndex: webspIndex,
          formContext: { formSelector: null, fieldName: null, groupName: null },
          outerHTML: outerHTML,
          innerHTML: innerHTML,
          targetOnClick: targetOnClick,
          ...semanticInfo,
          ...switchContext
        };
        
        chrome.runtime.sendMessage({ action: 'recordEvent', eventData });
        console.log('✅ [recordGeneralClick] Switch change saved - Selector:', eventData.selectorPath, 'Checked:', checked);
        console.log('✅ [recordGeneralClick] Switch change saved - Selector:', eventData);

        captureScreenshot('toggle');
      } catch (err2) {
        console.error('Error recording mapped switch:', err2);
      }
    }, 120);
    return;
  }

  console.log('[recordGeneralClick] Final target:', target.tagName, target.id || target.className);
  
  // Check for duplicate click (skip if mousedown already recorded this)
  if (isRecentClick(target)) {
    console.log('✋ [recordGeneralClick] Skipped (duplicate - mousedown already recorded):', getSelectorPath(target));
    return;
  }

  // Mark this element as recently clicked
  recentInteractions.set(getSelectorPath(target), Date.now());

  // Capture element info immediately
  const tagName = target.tagName.toLowerCase();
  const href = target.href || null;
  const semanticInfo = getSemanticInfo(target);

  try {
    const eventData = {
      type: 'click',
      timestamp: new Date().toISOString(),
      site: window.location.href,
      selectorPath: getSelectorPath(target),
      xpath: getXPath(target),
      framePath: getFramePath(),
      elementType: tagName,
      href: href,
      webspIndex: findWebspIndex(target, e),
      formContext: {
        formSelector: null,
        fieldName: null,
        groupName: null
      },
      outerHTML: safeOuterHTML(target),
      innerHTML: safeInnerHTML(target),
      targetOnClick: getOnClickSource(target),
      ...semanticInfo
    };

    chrome.runtime.sendMessage({ action: 'recordEvent', eventData });
    console.log('✅ [recordGeneralClick] Event saved - Type:', eventData.type, 'Selector:', eventData.selectorPath, 'Tag:', eventData.elementType);
    console.log('✅ [recordGeneralClick] Full event:', eventData);

    // ADDED: Capture screenshot after click
    captureScreenshot('click');
  } catch (error) {
    console.error('Error recording general click:', error);
  }
}

// ADDED: Capture screenshot function with debouncing
function captureScreenshot(eventType) {
  try {
    const now = Date.now();
    
    // Debounce: Skip if screenshot was captured very recently, but NEVER skip toggles
    if (eventType !== 'toggle' && (now - lastScreenshotTime < SCREENSHOT_DEBOUNCE_MS)) {
      console.log('Screenshot skipped (debounced):', eventType);
      return;
    }
    
    lastScreenshotTime = now;
    
    chrome.runtime.sendMessage({ 
      action: 'captureScreenshot',
      eventType: eventType,
      timestamp: new Date().toISOString()
    });
  } catch (error) {
    console.error('Error requesting screenshot:', error);
  }
}

// Semantic info extraction for stable element identification
function getSemanticInfo(element) {
  const info = {};
  
  try {
    // Basic tag/role/type
    try {
      info.tagName = element.tagName ? element.tagName.toLowerCase() : null;
    } catch (e) { info.tagName = null; }
    try {
      info.role = element.getAttribute('role') || null;
    } catch (e) { info.role = null; }
    try {
      info.typeAttr = element.getAttribute('type') || null;
    } catch (e) { info.typeAttr = null; }
    
    // Capture ARIA attributes
    info.ariaLabel = element.getAttribute('aria-label') || null;
    info.ariaLabelledby = element.getAttribute('aria-labelledby') || null;
    info.ariaDescribedby = element.getAttribute('aria-describedby') || null;
    info.ariaSelected = element.getAttribute('aria-selected') || null;

    // Capture data attributes (test IDs, etc.)
    info.dataTestId = element.getAttribute('data-testid') || element.getAttribute('data-test-id') || null;
    info.dataCy = element.getAttribute('data-cy') || null;
    info.dataAutomation = element.getAttribute('data-automation') || null;
    
    // Capture placeholder and title
    info.placeholder = element.getAttribute('placeholder') || null;
    info.title = element.getAttribute('title') || null;
    
    // Find associated label text
    try {
      info.labelText = getLabelText(element);
    } catch (e) {
      info.labelText = null;
    }
    
    // Capture nearby text (for buttons/divs acting as controls)
    try {
      const innerTextRaw = element.innerText;
      info.innerText = innerTextRaw ? innerTextRaw.trim().substring(0, 100) : null;
    } catch (e) {
      info.innerText = null;
    }
    
    try {
      const textContentRaw = element.textContent;
      info.textContent = textContentRaw ? textContentRaw.trim().substring(0, 100) : null;
    } catch (e) {
      info.textContent = null;
    }
    
    // Capture ID and name (more stable than position)
    info.id = element.id || null;
    info.name = element.name || null;
    
    // Capture class list (may contain semantic info)
    try {
      info.classList = element.classList && element.classList.length > 0 
        ? Array.from(element.classList) 
        : [];
    } catch (e) {
      info.classList = [];
    }
    
    // Get parent context (nearest labeled ancestor)
    try {
      info.parentContext = getParentContext(element);
    } catch (e) {
      info.parentContext = null;
    }
    
    // Capture nearby text from siblings to help identify elements
    try {
      info.nearbyLabelText = findNearbyLabelText(element);
    } catch (e) {
      info.nearbyLabelText = null;
    }
    
    // Capture parent text context for additional identification
    try {
      info.parentTextContext = findParentTextContext(element);
    } catch (e) {
      info.parentTextContext = null;
    }
  } catch (e) {
    console.error('Error in getSemanticInfo:', e);
  }
  
  return info;
}

// Extra helpers for improved element identification
function safeOuterHTML(element) {
  try {
    const html = element && element.outerHTML ? String(element.outerHTML) : null;
    // Avoid gigantic payloads; keep enough for identification
    return html ? html.slice(0, 5000) : null;
  } catch (e) {
    return null;
  }
}

function safeInnerHTML(element) {
  try {
    const html = element && element.innerHTML ? String(element.innerHTML) : null;
    return html ? html.slice(0, 2000) : null;
  } catch (e) {
    return null;
  }
}

function getOnClickSource(element) {
  try {
    const handler = element ? (element.onclick || null) : null;
    return handler ? String(handler.toString()).slice(0, 2000) : null;
  } catch (e) {
    return null;
  }
}

// Capture rich context around switches to help disambiguate in replay
function getSwitchContext(element) {
  const ctx = {};
  try {
    // 1) Control label or nearby heading text
    try {
      const heading = element.closest('section, div, article')?.querySelector('h1, h2, h3, h4, h5, h6');
      ctx.headingText = heading && heading.innerText ? heading.innerText.trim().substring(0, 200) : null;
    } catch (e) { ctx.headingText = null; }

    // 2) Immediate textual label for the control (preceding p/span)
    try {
      let labelText = null;
      const prev = element.closest('div, section, article')?.querySelector('p, span');
      if (prev && prev.innerText && prev.innerText.trim().length > 10) {
        labelText = prev.innerText.trim().substring(0, 300);
      }
      ctx.controlLabelText = labelText;
    } catch (e) { ctx.controlLabelText = null; }

    // 3) Larger section text (unique descriptive paragraph)
    try {
      let container = element.closest('section, article, [role="region"], [role="group"], [role="dialog"], div');
      // Climb a bit to get a bigger section if current is too small
      let depth = 0;
      while (container && depth < 3) {
        const text = (container.innerText || '').trim();
        if (text && text.length > 50) break;
        container = container.parentElement;
        depth++;
      }
      const sectionText = container && container.innerText ? container.innerText.trim().substring(0, 800) : null;
      ctx.sectionText = sectionText;
    } catch (e) { ctx.sectionText = null; }
  } catch (e) {}
  return ctx;
}

function getLabelText(element) {
  try {
    // Method 1: Associated label via 'for' attribute
    if (element.id) {
      const label = document.querySelector(`label[for="${element.id}"]`);
      if (label && label.innerText) return label.innerText.trim() || null;
    }
  } catch (e) {}
  
  try {
    // Method 2: Wrapped in label
    const parentLabel = element.closest('label');
    if (parentLabel) {
      // Clone and remove input to get just label text
      const clone = parentLabel.cloneNode(true);
      const inputs = clone.querySelectorAll('input, select, textarea');
      inputs.forEach(inp => inp.remove());
      if (clone.innerText) return clone.innerText.trim() || null;
    }
  } catch (e) {}
  
  try {
    // Method 3: aria-labelledby reference
    const labelledby = element.getAttribute('aria-labelledby');
    if (labelledby) {
      const labelEl = document.getElementById(labelledby);
      if (labelEl && labelEl.innerText) return labelEl.innerText.trim() || null;
    }
  } catch (e) {}
  
  try {
    // Method 4: Previous sibling label
    const prevSibling = element.previousElementSibling;
    if (prevSibling && prevSibling.tagName === 'LABEL' && prevSibling.innerText) {
      return prevSibling.innerText.trim() || null;
    }
  } catch (e) {}
  
  try {
    // Method 5: Next sibling label (for some layouts)
    const nextSibling = element.nextElementSibling;
    if (nextSibling && nextSibling.tagName === 'LABEL' && nextSibling.innerText) {
      return nextSibling.innerText.trim() || null;
    }
  } catch (e) {}
  
  return null;
}

function getParentContext(element) {
  try {
    // Find nearest parent with semantic meaning (fieldset, section with label, etc.)
    const fieldset = element.closest('fieldset');
    if (fieldset) {
      const legend = fieldset.querySelector('legend');
      if (legend && legend.innerText) return legend.innerText.trim() || null;
    }
  } catch (e) {}
  
  try {
    const section = element.closest('section, article, [role="group"], [role="region"]');
    if (section) {
      const heading = section.querySelector('h1, h2, h3, h4, h5, h6');
      if (heading && heading.innerText) return heading.innerText.trim() || null;
      
      const ariaLabel = section.getAttribute('aria-label');
      if (ariaLabel) return ariaLabel;
    }
  } catch (e) {}
  
  return null;
}

function findNearbyLabelText(element) {
  // Look at siblings for text
  try {
    const parent = element.parentElement;
    if (parent) {
      // Check previous sibling
      const prevSibling = element.previousElementSibling;
      if (prevSibling && prevSibling.textContent && prevSibling.textContent.trim()) {
        return prevSibling.textContent.trim().substring(0, 100);
      }
      
      // Check next sibling
      const nextSibling = element.nextElementSibling;
      if (nextSibling && nextSibling.textContent && nextSibling.textContent.trim()) {
        return nextSibling.textContent.trim().substring(0, 100);
      }
      
      // Check parent's text (without element's text)
      const parentText = parent.textContent || '';
      const elementText = element.textContent || '';
      if (parentText.length > elementText.length) {
        const parentOnlyText = parentText.replace(elementText, '').trim();
        if (parentOnlyText) {
          return parentOnlyText.substring(0, 100);
        }
      }
    }
  } catch (e) {
    // Ignore errors
  }
  return null;
}

function findParentTextContext(element) {
  // Look up the tree for any text-bearing elements
  try {
    let parent = element.parentElement;
    let depth = 0;
    while (parent && depth < 5) {
      const text = parent.textContent?.trim();
      const role = parent.getAttribute('role');
      
      // Check if this is a meaningful container (not just generic div/span)
      const tagName = parent.tagName?.toLowerCase() || '';
      const isMeaningfulContainer = (
        tagName === 'section' || tagName === 'article' || 
        tagName === 'aside' || tagName === 'nav' || tagName === 'main' ||
        role === 'dialog' || role === 'region' || role === 'complementary' ||
        role === 'navigation' || role === 'banner' || role === 'contentinfo'
      );
      
      if (text && text.length > 10 && (isMeaningfulContainer || depth === 0)) {
        return text.substring(0, 150);
      }
      
      parent = parent.parentElement;
      depth++;
    }
  } catch (e) {
    // Ignore errors
  }
  return null;
}

// Utility functions
function getSelectorPath(element) {
  if (!(element instanceof Element)) return '';
  const path = [];
  while (element && element.nodeType === Node.ELEMENT_NODE) {
    let selector = element.nodeName.toLowerCase();
    if (element.id) {
      selector += `#${element.id}`;
      path.unshift(selector);
      break;
    } else {
      let sibling = element;
      let nth = 1;
      while (sibling = sibling.previousElementSibling)
        if (sibling.nodeName.toLowerCase() === selector) nth++;
      selector += `:nth-of-type(${nth})`;
    }
    path.unshift(selector);

    // Handle shadow DOM - if parent is a shadow root, use the host element
    let parent = element.parentNode;
    if (!parent) break; // Detached element

    if (parent.nodeType === Node.DOCUMENT_FRAGMENT_NODE) {
      // Inside shadow root - add marker and use shadow host as parent
      if (parent.host) {
        path.unshift('::shadow');
        element = parent.host;
      } else {
        break; // Shadow root without host
      }
    } else {
      element = parent;
    }
  }
  return path.join(' > ');
}

function getXPath(element) {
  if (!element || element.nodeType !== Node.ELEMENT_NODE) return '';
  if (element.id) return `//*[@id="${element.id}"]`;
  if (element === document.body) return '/html/body';
  if (element === document.documentElement) return '/html';

  // Handle shadow DOM - if parent is a shadow root, use the host element
  let parent = element.parentNode;
  if (!parent) return ''; // Detached element

  if (parent.nodeType === Node.DOCUMENT_FRAGMENT_NODE) {
    // Inside shadow root - use shadow host as parent
    parent = parent.host;
    if (!parent) return ''; // Shadow root without host
  }

  // Check if parent has children
  if (!parent.children) return '';

  const ix = Array.from(parent.children)
    .filter(sib => sib.nodeName === element.nodeName)
    .indexOf(element) + 1;

  // If element not found in parent's children, return empty
  if (ix === 0) return '';

  return getXPath(parent) + '/' + element.nodeName.toLowerCase() + `[${ix}]`;
}

function getFramePath() {
  let win = window;
  const path = [];
  while (win !== win.top) {
    try {
      const frames = Array.from(win.parent.document.querySelectorAll('iframe'));
      const frame = frames.find(f => f.contentWindow === win);
      if (!frame) break;

      // Try to get a stable selector using ID, name, or src first
      let selector = null;

      // Priority 1: Use ID if available (most stable)
      if (frame.id) {
        selector = `iframe#${frame.id}`;
      }
      // Priority 2: Use name attribute
      else if (frame.name) {
        selector = `iframe[name="${frame.name}"]`;
      }
      // Priority 3: Use src attribute (partial match for stability)
      else if (frame.src) {
        try {
          // Extract meaningful part of src (e.g., filename or key path segment)
          const url = new URL(frame.src);
          const pathname = url.pathname;
          // Use last non-empty path segment
          const segments = pathname.split('/').filter(s => s);
          if (segments.length > 0) {
            const lastSegment = segments[segments.length - 1];
            // Remove query params from segment if present
            const cleanSegment = lastSegment.split('?')[0];
            if (cleanSegment) {
              selector = `iframe[src*="${cleanSegment}"]`;
            }
          }
        } catch (urlError) {
          // src is not a valid URL, skip
        }
      }

      // Priority 4: Use getSelectorPath (might use classes, structure)
      if (!selector) {
        selector = getSelectorPath(frame);
      }

      // Priority 5 (last resort): Use nth-of-type with warning
      if (!selector || !selector.trim()) {
        const iframeIndex = frames.indexOf(frame);
        if (iframeIndex >= 0) {
          console.warn('[getFramePath] Using fragile nth-of-type selector for iframe. Consider adding id/name to iframe.');
          selector = `iframe:nth-of-type(${iframeIndex + 1})`;
        }
      }

      if (selector) {
        path.unshift(selector);
      }

      win = win.parent;
    } catch (e) {
      // Cross-origin frame - can't access parent
      console.log('[getFramePath] Cannot access parent frame (cross-origin)');
      break;
    }
  }
  return path;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === 'startRecording') {
    startRecording();
    sendResponse({ success: true });
  }
  if (message.action === 'stopRecording') {
    stopRecording();
    sendResponse({ success: true });
  }
  if (message.action === 'getViewportSize') {
    chrome.runtime.sendMessage({
      action: 'getViewportSize',
      width: window.innerWidth,
      height: window.innerHeight
    });
    sendResponse({ success: true });
  }
  return true; // Keep channel open for async response
});