// popup.js
const startButton = document.getElementById('startRecording');
const stopButton = document.getElementById('stopRecording');
const statusDiv = document.getElementById('status');
const taskIdInput = document.getElementById('taskId');

// Initialize button states
stopButton.disabled = true;

// Check recording state on popup open
chrome.runtime.sendMessage({ action: 'getRecordingState' }, (response) => {
  if (chrome.runtime.lastError) {
    console.error('Error getting recording state:', chrome.runtime.lastError);
    return;
  }
  
  if (response && response.isRecording) {
    startButton.disabled = true;
    stopButton.disabled = false;
    statusDiv.textContent = 'Recording...';
    statusDiv.className = 'status recording';
    
    // Display the persisted task ID and make it read-only during recording
    if (response.taskId) {
      taskIdInput.value = response.taskId;
      taskIdInput.disabled = true; // Prevent changing task ID mid-recording
      console.log('Loaded task ID from state:', response.taskId);
    }
  } else {
    // Not recording - enable task ID input
    taskIdInput.disabled = false;
  }
});

// Start recording
startButton.addEventListener('click', async () => {
  const taskId = taskIdInput.value.trim();
  
  if (!taskId) {
    alert('Please enter a Task ID');
    return;
  }
  
  try {
    // Disable button immediately to prevent double-clicks
    startButton.disabled = true;
    statusDiv.textContent = 'Starting...';
    statusDiv.className = 'status recording';
    
    console.log('Sending startRecording message with taskId:', taskId);
    
    // Send start recording message and wait for response
    const response = await chrome.runtime.sendMessage({ 
      action: 'startRecording',
      taskId: taskId 
    });
    
    console.log('Received response:', response);
    
    if (response && response.success) {
      stopButton.disabled = false;
      taskIdInput.disabled = true; // Disable task ID input during recording
      statusDiv.textContent = 'Recording...';
      console.log('Recording started successfully');
      
      // Keep popup open for a bit to ensure screenshot captures
      await new Promise(resolve => setTimeout(resolve, 1000));
      
      // Now close popup
      window.close();
    } else {
      // Re-enable if failed
      startButton.disabled = false;
      statusDiv.textContent = 'Failed to start';
      statusDiv.className = 'status stopped';
      console.error('Failed to start recording:', response);
    }
  } catch (error) {
    console.error('Error starting recording:', error);
    startButton.disabled = false;
    stopButton.disabled = true;
    statusDiv.textContent = 'Error: ' + error.message;
    statusDiv.className = 'status stopped';
  }
});

// Stop recording
stopButton.addEventListener('click', async () => {
  try {
    // Disable button immediately
    stopButton.disabled = true;
    statusDiv.textContent = 'Stopping...';
    
    console.log('Sending stopRecording message');
    
    // Send stop recording message and wait for response
    const response = await chrome.runtime.sendMessage({ 
      action: 'stopRecording' 
    });
    
    console.log('Received stop response:', response);
    
    if (response && response.success) {
      startButton.disabled = false;
      statusDiv.textContent = 'Recording saved!';
      statusDiv.className = 'status stopped';
      taskIdInput.value = ''; // Clear task ID
      taskIdInput.disabled = false; // Re-enable task ID input
      console.log('Recording stopped successfully');
      
      // Keep popup open longer to ensure download completes
      await new Promise(resolve => setTimeout(resolve, 2000));
      
      // Close popup
      window.close();
    } else {
      // Re-enable if failed
      stopButton.disabled = false;
      statusDiv.textContent = 'Failed to stop';
      console.error('Failed to stop recording:', response);
    }
  } catch (error) {
    console.error('Error stopping recording:', error);
    stopButton.disabled = false;
    statusDiv.textContent = 'Error: ' + error.message;
  }
});