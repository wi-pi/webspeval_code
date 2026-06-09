// background.js
// State variables (also persisted in chrome.storage for reliability)
let isRecording = false;
let startUrl = '';
let recordedEvents = [];
let screenshots = [];
let viewport = { width: 0, height: 0 };
let initialFormStates = {};
let activeTabId = null;
let taskId = '';
let sessionId = '';
let recordingTabIds = new Set(); // Track all tabs involved in recording

// Rate limiting for screenshot capture (Chrome limit: ~2 per second)
const SCREENSHOT_MIN_INTERVAL_MS = 500; // 500ms = 2 per second max
const SCREENSHOT_MAX_QUEUE_SIZE = 50; // Prevent memory issues from rapid events
let lastScreenshotTime = 0;
let screenshotQueue = [];
let isProcessingQueue = false;

// Initialize state from storage on service worker startup
chrome.storage.local.get(['isRecording', 'taskId', 'sessionId', 'startUrl', 'activeTabId', 'recordedEvents', 'screenshots', 'viewport', 'initialFormStates', 'recordingTabIds'], (result) => {
  if (result.isRecording) {
    isRecording = result.isRecording;
    taskId = result.taskId || '';
    sessionId = result.sessionId || '';
    startUrl = result.startUrl || '';
    activeTabId = result.activeTabId || null;
    recordedEvents = result.recordedEvents || [];
    screenshots = result.screenshots || [];
    viewport = result.viewport || { width: 0, height: 0 };
    initialFormStates = result.initialFormStates || {};
    recordingTabIds = new Set(result.recordingTabIds || []);
    console.log('State restored from storage:', { isRecording, taskId, sessionId, events: recordedEvents.length, tabs: recordingTabIds.size });
  }
});

// Helper function to persist state to storage
function persistState() {
  chrome.storage.local.set({
    isRecording,
    taskId,
    sessionId,
    startUrl,
    activeTabId,
    recordedEvents,
    screenshots,
    viewport,
    initialFormStates,
    recordingTabIds: Array.from(recordingTabIds) // Convert Set to Array for JSON serialization
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message.action) {
    case 'startRecording':
      taskId = message.taskId || 'unknown';
      startRecording().then(() => {
        sendResponse({ success: true });
      }).catch(error => {
        console.error('Start recording error:', error);
        sendResponse({ success: false, error: error.message });
      });
      return true; // Keep channel open for async response
      
    case 'stopRecording':
      stopRecording().then(() => {
        sendResponse({ success: true });
      }).catch(error => {
        console.error('Stop recording error:', error);
        sendResponse({ success: false, error: error.message });
      });
      return true;
      
    case 'recordEvent':
      recordEvent(message.eventData);
      // Note: Screenshots are captured via explicit 'captureScreenshot' messages from content.js
      // This prevents duplicate/unnecessary screenshots for every event
      break;
      
    case 'saveInitialFormStates':
      initialFormStates = message.states || {};
      persistState();
      break;
      
    case 'getRecordingState':
      sendResponse({ isRecording, startUrl, taskId, sessionId });
      return true;
      
    case 'captureScreenshot':
      captureScreenshot(message.eventType, message.timestamp);
      break;
      
    case 'getViewportSize':
      if (message.width && message.height) {
        viewport = { width: message.width, height: message.height };
        persistState();
      }
      break;
  }
});

async function startRecording() {
  console.log('=== START RECORDING CALLED ===');
  isRecording = true;
  recordedEvents = [];
  screenshots = [];
  initialFormStates = {};
  recordingTabIds.clear(); // Clear any previous tab IDs
  screenshotQueue = []; // Clear any pending screenshots from previous session
  lastScreenshotTime = 0; // Reset rate limiter
  
  // Generate session ID with timestamp
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5);
  sessionId = `session_${timestamp}`;
  console.log('Session ID:', sessionId);

  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const activeTab = tabs[0];
  activeTabId = activeTab.id;
  startUrl = activeTab.url;
  recordingTabIds.add(activeTab.id); // Add initial tab to recording tabs
  
  console.log('Starting recording on tab:', activeTabId, startUrl);
  
  // Persist state immediately
  persistState();
  console.log('State persisted to storage');
  
  // Capture initial screenshot FIRST (while we have user gesture)
  console.log('Attempting to capture initial screenshot...');
  try {
    await captureScreenshotSync('initial', new Date().toISOString());
    console.log('Initial screenshot capture completed');
  } catch (error) {
    console.error('Initial screenshot failed:', error);
  }
  
  // Request viewport size from content script
  try {
    await chrome.tabs.sendMessage(activeTab.id, { action: 'getViewportSize' });
  } catch (error) {
    console.error('Error getting viewport size:', error);
  }

  // Start recording in content script
  try {
    // Check if content script can receive messages (not on restricted pages)
    if (activeTab.url && !activeTab.url.startsWith('chrome://') && !activeTab.url.startsWith('chrome-extension://') && !activeTab.url.startsWith('edge://') && !activeTab.url.startsWith('about:')) {
      await chrome.tabs.sendMessage(activeTab.id, { action: 'startRecording' });
      console.log('Recording started in content script on tab:', activeTab.id);
    } else {
      console.error('Cannot start recording on restricted page:', activeTab.url);
      throw new Error('Cannot record on restricted pages (chrome://, edge://, etc.)');
    }
  } catch (error) {
    console.error('Error starting recording in content script:', error);
    // Reset state if content script failed
    isRecording = false;
    persistState();
    throw error; // Propagate error to caller
  }
  
  console.log('=== START RECORDING COMPLETED ===');
}

async function stopRecording() {
  console.log('=== STOP RECORDING CALLED ===');
  console.log('Current state - Events:', recordedEvents.length, 'Screenshots:', screenshots.length);
  
  // Capture final screenshot FIRST (while we have user gesture)
  console.log('Attempting to capture final screenshot...');
  try {
    // Small delay to allow last UI updates (e.g., toggle animation) to render
    await new Promise(resolve => setTimeout(resolve, 200));
    await captureScreenshotSync('final', new Date().toISOString());
    console.log('Final screenshot capture completed');
  } catch (error) {
    console.error('Final screenshot failed:', error);
  }
  
  isRecording = false;
  
  // Update storage immediately to prevent recording new events
  persistState();
  console.log('Recording state set to false and persisted');
  
  // Send stop message to ALL recording tabs
  console.log('Stopping recording on', recordingTabIds.size, 'tabs');
  for (const tabId of recordingTabIds) {
    try {
      // First check if the tab still exists
      const tab = await chrome.tabs.get(tabId);
      if (tab) {
        // Only try to send message if tab is not on a restricted page
        if (tab.url && !tab.url.startsWith('chrome://') && !tab.url.startsWith('chrome-extension://') && !tab.url.startsWith('edge://') && !tab.url.startsWith('about:')) {
          await chrome.tabs.sendMessage(tabId, { action: 'stopRecording' });
          console.log('Stop message sent to tab:', tabId);
        } else {
          console.log('Tab', tabId, 'is on restricted page, skipping');
        }
      }
    } catch (error) {
      // Tab might have been closed or content script not available
      console.warn('Could not send stop message to tab', tabId, '(tab may be closed):', error);
      // This is not a critical error - recording is already stopped in background
    }
  }
  
  // Clear the recording tabs set
  recordingTabIds.clear();
  persistState();
  
  // Download after a short delay
  console.log('Scheduling download in 500ms...');
  setTimeout(() => {
    console.log('Executing download now...');
    downloadRecording();
  }, 500);
  
  console.log('=== STOP RECORDING COMPLETED ===');
}

function recordEvent(eventData) {
  // Always check storage state in case service worker was restarted
  chrome.storage.local.get(['isRecording'], (result) => {
    const shouldRecord = result.isRecording !== undefined ? result.isRecording : isRecording;
    
    if (shouldRecord) {
      recordedEvents.push(eventData);
      console.log('Event recorded:', eventData.type, '- Total events:', recordedEvents.length);
      
      // Persist state after recording event (includes the new event)
      persistState();
    } else {
      console.log('Event ignored - recording is stopped:', eventData.type);
    }
  });
}

// Process screenshot queue with rate limiting
function processScreenshotQueue() {
  if (isProcessingQueue || screenshotQueue.length === 0) {
    return;
  }
  
  isProcessingQueue = true;
  
  const processNext = () => {
    if (screenshotQueue.length === 0) {
      isProcessingQueue = false;
      return;
    }
    
    const now = Date.now();
    const timeSinceLastCapture = now - lastScreenshotTime;
    
    if (timeSinceLastCapture < SCREENSHOT_MIN_INTERVAL_MS) {
      // Wait before processing next screenshot
      const waitTime = SCREENSHOT_MIN_INTERVAL_MS - timeSinceLastCapture;
      setTimeout(processNext, waitTime);
      return;
    }
    
    // Process the next screenshot in queue
    const request = screenshotQueue.shift();
    lastScreenshotTime = Date.now();
    
    captureScreenshotImmediate(request.eventType, request.timestamp)
      .then(() => {
        if (request.resolve) request.resolve();
        // Continue processing queue after a short delay
        setTimeout(processNext, SCREENSHOT_MIN_INTERVAL_MS);
      })
      .catch(error => {
        console.error('Screenshot queue processing error:', error);
        if (request.reject) request.reject(error);
        // Continue processing queue even on error
        setTimeout(processNext, SCREENSHOT_MIN_INTERVAL_MS);
      });
  };
  
  processNext();
}

// Immediate screenshot capture (internal, rate-limited by queue)
function captureScreenshotImmediate(eventType, timestamp) {
  return new Promise((resolve, reject) => {
    chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
      if (!tabs || !tabs[0]) {
        console.error('No active tab found');
        resolve(); // Don't reject, just continue
        return;
      }

      const tab = tabs[0];
      
      // Check if we can capture
      if (tab.url && (tab.url.startsWith('chrome://') || tab.url.startsWith('chrome-extension://') || tab.url.startsWith('edge://') || tab.url.startsWith('about:'))) {
        console.warn('Cannot capture screenshot on restricted pages:', tab.url);
        resolve();
        return;
      }

      chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' })
        .then(dataUrl => {
          if (dataUrl) {
            const screenshotData = {
              timestamp: timestamp,
              eventType: eventType,
              dataUrl: dataUrl,
              index: screenshots.length
            };
            
            screenshots.push(screenshotData);
            persistState(); // Persist after adding screenshot
            console.log(`✓ Screenshot captured: ${eventType} (${screenshots.length})`);
          }
          resolve();
        })
        .catch(error => {
          console.error('Screenshot capture error:', error);
          resolve(); // Don't reject, just continue
        });
    });
  });
}

// Synchronous screenshot capture with Promise (uses queue)
function captureScreenshotSync(eventType, timestamp) {
  console.log(`captureScreenshotSync called: ${eventType} at ${timestamp}`);
  
  return new Promise((resolve, reject) => {
    if (screenshotQueue.length >= SCREENSHOT_MAX_QUEUE_SIZE) {
      console.warn(`Screenshot queue full (${screenshotQueue.length}), skipping: ${eventType}`);
      resolve(); // Don't reject, just skip this screenshot
      return;
    }
    
    screenshotQueue.push({ eventType, timestamp, resolve, reject });
    processScreenshotQueue();
  });
}

// Async screenshot capture for events (uses queue)
function captureScreenshot(eventType, timestamp) {
  if (!isRecording && eventType !== 'initial' && eventType !== 'final') return;
  
  if (screenshotQueue.length >= SCREENSHOT_MAX_QUEUE_SIZE) {
    console.warn(`Screenshot queue full (${screenshotQueue.length}), skipping: ${eventType}`);
    return;
  }
  
  console.log(`Queueing screenshot: ${eventType} at ${timestamp}`);
  screenshotQueue.push({ eventType, timestamp });
  processScreenshotQueue();
}

// Extract domain from URL for folder structure
function getDomainFromUrl(url) {
  try {
    const urlObj = new URL(url);
    return urlObj.hostname.replace(/\./g, '_');
  } catch (e) {
    return 'unknown_domain';
  }
}

// Sanitize filename to remove invalid characters
function sanitizeFilename(filename) {
  return filename.replace(/[<>:"/\\|?*\x00-\x1F]/g, '_');
}

async function downloadRecording() {
  console.log('=== DOWNLOAD RECORDING CALLED ===');
  console.log('Final counts - Events:', recordedEvents.length, 'Screenshots:', screenshots.length);
  
  const domain = getDomainFromUrl(startUrl);
  const sanitizedTaskId = sanitizeFilename(taskId);
  
  // Base folder structure: usersfirst-path-recordings/domain/taskname/sessionID/
  const baseFolder = `usersfirst-path-recordings/${domain}/${sanitizedTaskId}/${sessionId}`;
  console.log('Base folder:', baseFolder);
  
  // Download each screenshot as a separate PNG file
  for (let i = 0; i < screenshots.length; i++) {
    const screenshot = screenshots[i];
    const screenshotFilename = `${baseFolder}/screenshots/screenshot_${String(i).padStart(3, '0')}_${screenshot.eventType}.png`;
    
    try {
      // Remove the data URL prefix to get just the base64 data
      const base64Data = screenshot.dataUrl.split(',')[1];
      const dataUrl = `data:image/png;base64,${base64Data}`;
      
      await chrome.downloads.download({
        url: dataUrl,
        filename: screenshotFilename,
        saveAs: false, // Don't prompt user
        conflictAction: 'overwrite'
      });
      
      console.log(`Screenshot ${i + 1}/${screenshots.length} downloaded: ${screenshotFilename}`);
    } catch (error) {
      console.error(`Error downloading screenshot ${i}:`, error);
    }
    
    // Small delay to avoid overwhelming the download system
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  
  // Prepare JSON data WITHOUT screenshot dataUrls (they're saved separately)
  // Structure compatible with selenium_state_reset_check.py:
  // Required fields: startUrl, viewportWidth, viewportHeight, events
  // Each event needs: type, timestamp, selectorPath, xpath, framePath, checked (for toggles)
  // Plus all semantic info: labelText, ariaLabel, dataTestId, id, name, etc.
  const recordingData = {
    taskId,
    sessionId,
    startUrl,
    domain,
    viewportWidth: Math.max(viewport.width || 1280, 1280),
    viewportHeight: Math.max(viewport.height || 1024, 1024),
    initialFormStates,
    events: recordedEvents,
    screenshots: screenshots.map(s => ({
      timestamp: s.timestamp,
      eventType: s.eventType,
      index: s.index,
      filename: `screenshots/screenshot_${String(s.index).padStart(3, '0')}_${s.eventType}.png`
    })),
    metadata: {
      totalEvents: recordedEvents.length,
      totalScreenshots: screenshots.length,
      recordingDate: new Date().toISOString()
    }
  };

  console.log('Recording data prepared, creating JSON...');
  const jsonString = JSON.stringify(recordingData, null, 2);
  console.log('JSON created, length:', jsonString.length);
  
  // Convert JSON string to base64 data URL (service worker compatible)
  const base64 = btoa(unescape(encodeURIComponent(jsonString)));
  const dataUrl = `data:application/json;base64,${base64}`;
  console.log('Data URL created');

  // Use session-{timestamp}.json format to match selenium script expectations
  const jsonFilename = `${baseFolder}/session-${sessionId.replace('session_', '')}.json`;
  
  console.log('Initiating JSON download with filename:', jsonFilename);
  chrome.downloads.download({
    url: dataUrl,
    filename: jsonFilename,
    saveAs: false, // Don't prompt user
    conflictAction: 'overwrite'
  }, (downloadId) => {
    if (chrome.runtime.lastError) {
      console.error('Download error:', chrome.runtime.lastError);
    } else {
      console.log('JSON download initiated with ID:', downloadId);
    }
  });

  console.log('Recording saved:', {
    taskId,
    sessionId,
    folder: baseFolder,
    events: recordedEvents.length,
    screenshots: screenshots.length
  });
  
  // Clear state from storage after download
  chrome.storage.local.remove(['isRecording', 'taskId', 'sessionId', 'startUrl', 'activeTabId', 'recordedEvents', 'screenshots', 'viewport', 'initialFormStates', 'recordingTabIds'], () => {
    console.log('Recording state cleared from storage');
  });
  
  console.log('=== DOWNLOAD RECORDING COMPLETED ===');
}

// Tab event listeners for cross-tab and cross-domain recording

// Handle new tab creation
chrome.tabs.onCreated.addListener((tab) => {
  if (isRecording && tab.id) {
    console.log('New tab created during recording:', tab.id);
    // Content script will be injected when tab finishes loading (handled by onUpdated)
  }
});

// Handle tab updates (navigation, loading complete)
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (!isRecording) return;
  
  // Only act when page has finished loading
  if (changeInfo.status === 'complete') {
    const url = tab.url;
    
    // Skip restricted pages
    if (url && (url.startsWith('chrome://') || url.startsWith('chrome-extension://') || url.startsWith('edge://') || url.startsWith('about:'))) {
      console.log('Tab', tabId, 'navigated to restricted page, skipping');
      return;
    }
    
    console.log('Tab', tabId, 'loaded:', url);
    
    // Check if this is a NEW tab to recording (not already tracked)
    const isNewTab = !recordingTabIds.has(tabId);
    
    if (isNewTab) {
      // Add tab to recording set
      recordingTabIds.add(tabId);
      persistState();
      console.log('Added new tab', tabId, 'to recording. Total tabs:', recordingTabIds.size);
      
      // Inject content script only for NEW tabs
      // (existing tabs already have content script via manifest.json and will auto-start via localStorage)
      try {
        await chrome.scripting.executeScript({
          target: { tabId: tabId },
          files: ['content.js']
        });
        console.log('Content script injected into new tab:', tabId);
        
        // The content script will auto-start recording via localStorage check
      } catch (error) {
        console.error('Failed to inject content script into tab', tabId, ':', error);
      }
    } else {
      // Tab was already being recorded - this is a refresh or navigation
      // The content script will be automatically loaded via manifest.json
      // and will auto-start via localStorage check
      console.log('Tab', tabId, 'refreshed/navigated. Content script will auto-load from manifest.');
    }
  }
});

// Handle tab removal
chrome.tabs.onRemoved.addListener((tabId) => {
  if (recordingTabIds.has(tabId)) {
    recordingTabIds.delete(tabId);
    persistState();
    console.log('Tab', tabId, 'closed. Remaining tabs:', recordingTabIds.size);
  }
});