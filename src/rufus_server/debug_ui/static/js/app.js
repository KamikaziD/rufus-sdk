// --- Global State ---
let currentWorkflow = null;
let availableWorkflows = [];
let workflowSocket = null;
let currentStepInfoCache = null; // Cache for step info to avoid redundant fetches

// Declare dom globally, but initialize its properties in init()
let dom = {}; 

const API_BASE_URL = '/api/v1'; // This remains global

// --- Initialization ---

function init() {
    // Initialize dom object after DOM is loaded
    dom = {
        body: document.body,
        themeToggle: document.getElementById('theme-toggle'),
        // Header controls
        restartButtonHeader: document.getElementById('restart-button-header'),
        // Main views
        initialView: document.getElementById('initial-view'),
        workflowView: document.getElementById('workflow-view'),
        // Start Card (now within initialView)
        startCard: document.getElementById('workflow-start-card'),
        workflowSelect: document.getElementById('workflow-type-select'),
        initialDataTextArea: document.getElementById('initial-data'),
        // Visualizer Card
        visualizerCard: document.getElementById('workflow-visualizer-card'),
        visualizerList: document.getElementById('step-visualizer-list'),
        // Right Pane Tabs
        tabControls: document.querySelector('.tab-controls'),
        tabButtons: document.querySelectorAll('.tab-button'),
        tabPanes: document.querySelectorAll('.tab-pane'),
        // Workflow Control Section (replaces old control panel elements)
        workflowControlSection: document.querySelector('.workflow-control-section'),
        statusDisplay: document.getElementById('workflow-status-display'),
        currentStepName: document.getElementById('current-step-name'),
        actionButtons: document.querySelector('.action-buttons'),
        nextStepButton: document.getElementById('next-step-button'),
        checkStatusButton: document.getElementById('check-status-button'),
        resumeButton: document.getElementById('resume-button'),
        retryButton: document.getElementById('retry-button'),
        // Required Inputs Tab elements
        requiredInputsViewTabButton: document.querySelector('.tab-button[data-tab="required-inputs-view"]'),
        requiredInputsViewTabPane: document.getElementById('required-inputs-view'),
        dynamicFormInputs: document.getElementById('dynamic-form-inputs'),
        // New: Full State Pre element
        fullStatePre: document.getElementById('full-state-pre'), 
    };

    log('Initializing frontend...'); // Now log is called after dom is initialized
    setupEventListeners();
    applyInitialTheme();
    loadAvailableWorkflows();
    showTab('log-view'); // Default to showing the log view
}

document.addEventListener('DOMContentLoaded', init); // Simplified event listener, calls init directly

function updateInitialDataExample() { // Moved this function below init()
    const selectedType = dom.workflowSelect.value;
    const selectedWorkflow = availableWorkflows.find(wf => wf.type === selectedType);
    if (selectedWorkflow && selectedWorkflow.initial_data_example) {
        dom.initialDataTextArea.value = JSON.stringify(selectedWorkflow.initial_data_example, null, 2);
    }
}
function setupEventListeners() {
    dom.themeToggle.addEventListener('change', handleThemeToggle);
    dom.workflowSelect.addEventListener('change', updateInitialDataExample);

    // Tab buttons
    dom.tabControls.addEventListener('click', (event) => {
        if (event.target.classList.contains('tab-button')) {
            const tabId = event.target.dataset.tab;
            showTab(tabId);
        }
    });

    // Control Panel Buttons
    dom.nextStepButton.onclick = () => handleSubmissionAttempt(false);
    dom.resumeButton.onclick = () => handleSubmissionAttempt(true);
    dom.checkStatusButton.onclick = getWorkflowStatus;
    dom.retryButton.onclick = retryWorkflow;
    dom.restartButtonHeader.onclick = resetUI;
}

async function loadAvailableWorkflows() {
    try {
        const response = await fetch(`${API_BASE_URL}/workflows`);
        availableWorkflows = await response.json();
        
        dom.workflowSelect.innerHTML = availableWorkflows
            .map(wf => `<option value="${wf.type}">${wf.description}</option>`)
            .join('');
        
        updateInitialDataExample();
        log('Available workflows loaded.', null, 'success');
    } catch (error) {
        log('Error fetching workflows', error, 'error');
    }
}

// --- Theme Management ---

function applyInitialTheme() {
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark' || (savedTheme === null && prefersDark)) {
        dom.body.classList.add('dark-mode');
        dom.themeToggle.checked = false;
    } else {
        dom.body.classList.remove('dark-mode');
        dom.themeToggle.checked = true;
    }
}

function handleThemeToggle() {
    dom.body.classList.toggle('dark-mode');
    const isDarkMode = dom.body.classList.contains('dark-mode');
    localStorage.setItem('theme', isDarkMode ? 'dark' : 'light');
}

// --- UI & State Management ---

function showTab(tabId) {
    dom.tabButtons.forEach(button => button.classList.remove('active'));
    dom.tabPanes.forEach(pane => pane.classList.remove('active'));

    document.querySelector(`.tab-button[data-tab="${tabId}"]`).classList.add('active');
    document.getElementById(tabId).classList.add('active');
}


function resetUI() {
    disconnectWebSocket();
    currentWorkflow = null;
    currentStepInfoCache = null; // Clear cache on reset
    
    // Show initial view, hide workflow view
    dom.initialView.style.display = 'flex';
    dom.workflowView.style.display = 'none';
    dom.restartButtonHeader.style.display = 'none';

    // Clear dynamic content
    dom.logOutput.innerHTML = '';
    dom.fullStatePre.textContent = '';
    dom.visualizerList.innerHTML = '';
    dom.dynamicFormInputs.innerHTML = ''; // Clear form inputs in the tab

    log('UI Reset. Ready to start a new workflow.');
}

// --- Workflow Execution ---

async function startWorkflow() {
    const workflowType = dom.workflowSelect.value;
    let initialData;
    try {
        initialData = JSON.parse(dom.initialDataTextArea.value);
    } catch (e) {
        log('Invalid JSON in Initial Data', e, 'error');
        return;
    }

    log(`Starting workflow: ${workflowType}...`);
    try {
        const response = await fetch(`${API_BASE_URL}/workflow/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ workflow_type: workflowType, initial_data: initialData }),
        });
        const data = await response.json();

        if (!response.ok) throw new Error(data.detail || 'Failed to start workflow');

        log('Workflow started successfully', data, 'success');
        
        // Hide initial view, show workflow view
        dom.initialView.style.display = 'none';
        dom.workflowView.style.display = 'flex';
        dom.restartButtonHeader.style.display = 'inline-block';

        // Connect WebSocket for real-time updates
        connectWebSocket(data.workflow_id);
        showTab('log-view'); // Always show log when starting a new workflow

    } catch (error) {
        log('Error starting workflow', error, 'error');
    }
}

// --- Dynamic Form Submission ---

async function collectFormDataFromTab() { // Renamed from collectFormData
    const formContainer = dom.dynamicFormInputs; // Get data from the tab's form container
    const inputData = {};
    let isValid = true;

    formContainer.querySelectorAll('input, select, textarea').forEach(el => {
        if (!el.reportValidity()) {
            isValid = false;
        }

        if (el.name) {
            if (el.type === 'checkbox') {
                inputData[el.name] = el.checked;
            } else {
                const value = el.value;
                if (el.type === 'number' && value !== '') {
                     inputData[el.name] = el.step.includes('.') ? parseFloat(value) : parseInt(value, 10);
                } else {
                     inputData[el.name] = value;
                }
            }
        }
    });
    return { inputData, isValid };
}

async function submitNextStep(inputData) {
    if (!currentWorkflow) return;
    
    if (Object.keys(inputData).length > 0) {
        log('Advancing workflow with data:', inputData);
    } else {
        log('Advancing workflow.', null, 'info');
    }
    try {
        const response = await fetch(`${API_BASE_URL}/workflow/${currentWorkflow.id}/next`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ input_data: inputData }),
        });
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.detail || 'Failed to advance workflow');
        }
        log('"/next" call successful. Waiting for WebSocket update...', null, 'info');

    } catch (error) {
        log('Error advancing workflow', error, 'error');
    }
}

async function submitResume(inputData) {
    if (!currentWorkflow) return;
    
    if (Object.keys(inputData).length > 0) {
        log('Submitting human review with data:', inputData);
    } else {
        log('Submitting human review.', null, 'info');
    }
    try {
        const response = await fetch(`${API_BASE_URL}/workflow/${currentWorkflow.id}/resume`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(inputData),
        });
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.detail || 'Failed to submit review');
        }
        log('Review submitted. Waiting for WebSocket update...', null, 'info');

    } catch (error) {
        log('Error submitting review', error, 'error');
    }
}


// --- Action Button Handlers (in Control Panel) ---

// New: handle submission attempt for Next Step / Submit Review buttons
async function handleSubmissionAttempt(isResume) {
    let inputData = {};
    let isValid = true;

    // If input is required, collect from the form in the "Required Inputs" tab
    if (currentStepInfoCache && currentStepInfoCache.input_schema && Object.keys(currentStepInfoCache.input_schema.properties || {}).length > 0) {
        const formData = await collectFormDataFromTab();
        inputData = formData.inputData;
        isValid = formData.isValid;
    }

    if (!isValid) {
        log('Please fill out all required fields in the form.', null, 'warn');
        showTab('required-inputs-view'); // Auto-switch to form tab if validation fails
        return;
    }

    if (isResume) {
        await submitResume(inputData);
    } else {
        await submitNextStep(inputData);
    }
}


async function getWorkflowStatus() {
    if (!currentWorkflow) return;
    log(`Manually checking status for ${currentWorkflow.id}...`, null, 'info');
    try {
        const response = await fetch(`${API_BASE_URL}/workflow/${currentWorkflow.id}/status`);
        if (!response.ok) throw new Error((await response.json()).detail);
    } catch (error) {
        log('Error getting status', error, 'error');
    }
}

async function retryWorkflow() {
    if (!currentWorkflow) return;
    log(`Retrying workflow ${currentWorkflow.id}...`, null, 'info');
    try {
        const response = await fetch(`${API_BASE_URL}/workflow/${currentWorkflow.id}/retry`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.detail || 'Failed to retry workflow');
        }
        log('Workflow retry initiated successfully.', null, 'success');
    } catch (error) {
        log('Error retrying workflow', error, 'error');
    }
}


// --- Rendering ---

async function updateUI(workflowData) { // Make updateUI async
    if (!workflowData) return;
    
    currentWorkflow = workflowData;
    const { id, status, state, steps_config, current_step } = currentWorkflow;

    // 1. Update Status Display & Full State View
    const stateString = JSON.stringify(state, null, 2);
    let statusHTML = `<div><span>ID:</span> ${id}</div><div><span>Status:</span> <span class="status-badge status-${status.replace(/\s+/g, '_')}">${status}</span></div>`;

    // Show additional info for sub-workflows
    if (currentWorkflow.parent_execution_id) {
        statusHTML += `<div><span>Parent ID:</span> ${currentWorkflow.parent_execution_id}</div>`;
    }
    if (currentWorkflow.blocked_on_child_id) {
        statusHTML += `<div><span>Child ID:</span> ${currentWorkflow.blocked_on_child_id}</div>`;
    }
    if (currentWorkflow.workflow_type) {
        statusHTML += `<div><span>Type:</span> ${currentWorkflow.workflow_type}</div>`;
    }

    dom.statusDisplay.innerHTML = statusHTML;
    dom.fullStatePre.textContent = stateString;

    // 2. Render Step Visualizer
    renderStepVisualizer(steps_config, current_step, status);

    // 3. Reset and show/hide buttons based on status
    dom.nextStepButton.style.display = 'none';
    dom.checkStatusButton.style.display = 'none';
    dom.resumeButton.style.display = 'none';
    dom.retryButton.style.display = 'none';
    // dom.openFormButton.style.display = 'none'; // No longer needed
    dom.currentStepName.innerHTML = '...';

    // 4. Update UI based on status
    if (status === 'COMPLETED') {
        dom.currentStepName.innerHTML = `Workflow COMPLETED`;
        disconnectWebSocket();
        return;
    }
    if (status === 'FAILED') {
        dom.currentStepName.innerHTML = `Workflow FAILED`;
        dom.retryButton.style.display = 'block';
        return;
    }
    if (status === 'FAILED_ROLLED_BACK') {
        dom.currentStepName.innerHTML = `Workflow FAILED (Saga Rolled Back)`;
        dom.retryButton.style.display = 'block';
        log('Workflow failed and saga compensation was executed', null, 'warn');
        return;
    }
    if (status === 'PENDING_ASYNC') {
        dom.currentStepName.innerHTML = `Waiting for async task...`;
        dom.checkStatusButton.style.display = 'block';
        return;
    }
    if (status === 'PENDING_SUB_WORKFLOW') {
        const childId = currentWorkflow.blocked_on_child_id || 'unknown';
        dom.currentStepName.innerHTML = `Waiting for sub-workflow...`;
        dom.checkStatusButton.style.display = 'block';
        log(`Parent workflow paused, waiting for child workflow: ${childId}`, null, 'info');
        return;
    }

    // 5. Determine whether to show "Next Step" or "Submit Review"
    // and if input is needed (which might auto-switch tab)
    await fetchCurrentStepInfo(); // AWAIT this call
}

function renderStepVisualizer(steps = [], currentStepIndex, status) {
    dom.visualizerList.innerHTML = steps.map((step, index) => {
        let className = '';
        if (status === 'COMPLETED') {
            className = 'completed';
        } else if (index < currentStepIndex) {
            className = 'completed';
        } else if (index === currentStepIndex) {
            className = 'current';
        }
        return `<li class="${className}"><span class="step-name">${step.name}</span><span class="step-type">${step.type}</span></li>`;
    }).join('');
}

async function fetchCurrentStepInfo() {
    try {
        const res = await fetch(`${API_BASE_URL}/workflow/${currentWorkflow.id}/current_step_info`);
        if (!res.ok) throw new Error((await res.json()).detail);
        currentStepInfoCache = await res.json(); // Cache the step info
        const stepInfo = currentStepInfoCache;

        dom.currentStepName.innerHTML = stepInfo.name;
        
        // Show the correct main action button
        if (currentWorkflow.status === 'WAITING_HUMAN') {
            dom.resumeButton.style.display = 'block';
        } else {
            dom.nextStepButton.style.display = 'block';
        }

        // Check if input is required and render form
        if (stepInfo.input_schema && Object.keys(stepInfo.input_schema.properties || {}).length > 0) {
            dom.requiredInputsViewTabButton.style.display = 'inline-block'; // Show the tab button
            renderFormFromSchema(stepInfo.input_schema);
            showTab('required-inputs-view'); // Auto-switch to this tab
        } else {
            dom.requiredInputsViewTabButton.style.display = 'none'; // Hide the tab button
            dom.dynamicFormInputs.innerHTML = '<p>No input required for this step.</p>'; // Clear form area
            // If currently on the input tab and no input is required, switch to log view
            if (document.querySelector('.tab-button[data-tab="required-inputs-view"]').classList.contains('active')) {
                showTab('log-view');
            }
        }

    } catch (error) {
        log('Error fetching step info:', error, 'error');
    }
}

async function getCurrentStepInfo() {
    // If not cached or workflow/step changed, fetch fresh
    if (!currentStepInfoCache || currentStepInfoCache.workflowId !== currentWorkflow.id || currentStepInfoCache.stepName !== dom.currentStepName.innerHTML) {
        try {
            const res = await fetch(`${API_BASE_URL}/workflow/${currentWorkflow.id}/current_step_info`);
            if (!res.ok) throw new Error((await res.json()).detail);
            currentStepInfoCache = await res.json();
            currentStepInfoCache.workflowId = currentWorkflow.id; // Add for cache invalidation
            currentStepInfoCache.stepName = dom.currentStepName.innerHTML;
        } catch (error) {
            log('Error fetching current step info for cache:', error, 'error');
            return null;
        }
    }
    return currentStepInfoCache;
}


function renderFormFromSchema(schema) {
    let formHtml = '';
    const properties = schema.properties || {};
    const requiredFields = schema.required || [];

    for (const [key, prop] of Object.entries(properties)) {
        const isRequired = requiredFields.includes(key);
        const label = prop.title || key.replace(/_/g, ' ');
        const desc = prop.description ? `<small>${prop.description}</small>` : '';

        formHtml += '<div class="form-group">';
        formHtml += `<label for="input-${key}">${label}</label>`;

        if (prop.enum) {
            formHtml += `<select id="input-${key}" name="${key}" ${isRequired ? 'required' : ''}>`;
            prop.enum.forEach(val => {
                formHtml += `<option value="${val}">${val}</option>`;
            });
            formHtml += `</select>`;
        } else if (prop.type === 'boolean') {
            formHtml += `<input type="checkbox" id="input-${key}" name="${key}">`;
        } else if (prop.type === 'integer' || prop.type === 'number') {
            const step = prop.type === 'number' ? 'any' : '1';
            formHtml += `<input type="number" id="input-${key}" name="${key}" step="${step}" placeholder="${prop.title || key}" ${isRequired ? 'required' : ''}>`;
        } else { // string and others
            formHtml += `<input type="text" id="input-${key}" name="${key}" placeholder="${prop.title || key}" ${isRequired ? 'required' : ''}>`;
        }
        
        formHtml += desc;
        formHtml += '</div>';
    }

    dom.dynamicFormInputs.innerHTML = formHtml;
}


// --- Debug View Logic ---

async function fetchDebugWorkflows() {
    const container = document.getElementById('debug-content');
    if (!container) return;
    
    container.innerHTML = '<p>Loading...</p>';

    try {
        // Exclude COMPLETED workflows by default to focus on active debugging
        const response = await fetch(`${API_BASE_URL}/workflows/executions?limit=50&exclude_status=COMPLETED`);
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to fetch workflows');
        }
        const workflows = await response.json();
        
        if (workflows.length === 0) {
            container.innerHTML = '<p>No active or recent workflows found.</p>';
            return;
        }

        let html = `
            <table class="metrics-table">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Type</th>
                        <th>Status</th>
                        <th>Step</th>
                        <th>Last Updated</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
        `;

        workflows.forEach(wf => {
            html += `
                <tr>
                    <td><small>${wf.id}</small></td>
                    <td>${wf.workflow_type}</td>
                    <td><span class="status-badge status-${wf.status}">${wf.status}</span></td>
                    <td>${wf.current_step}</td>
                    <td>${new Date(wf.updated_at).toLocaleString()}</td>
                    <td>
                        <div class="action-buttons-row">
                            <button class="button-secondary small" onclick="loadWorkflow('${wf.id}')">View</button>
                            ${wf.status === 'FAILED' || wf.status === 'FAILED_ROLLED_BACK' ? `<button class="button-warn small" onclick="retryWorkflowFromDebug('${wf.id}')">Retry</button>` : ''}
                            ${wf.current_step > 0 ? `<button class="button-warn small" onclick="rewindWorkflow('${wf.id}')">Rewind</button>` : ''}
                        </div>
                    </td>
                </tr>
            `;
        });

        html += '</tbody></table>';
        container.innerHTML = html;

    } catch (error) {
        container.innerHTML = `<p class="error">Error: ${error.message}</p>`;
        log('Error fetching debug workflows', error, 'error');
    }
}

// Make it global so index.html can call it
window.fetchDebugWorkflows = fetchDebugWorkflows;

async function retryWorkflowFromDebug(workflowId) {
    if (!confirm('Are you sure you want to retry this workflow? It will be set to ACTIVE.')) return;
    
    try {
        const response = await fetch(`${API_BASE_URL}/workflow/${workflowId}/retry`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        if (!response.ok) throw new Error((await response.json()).detail);
        
        log(`Workflow ${workflowId} retried.`, null, 'success');
        fetchDebugWorkflows(); // Refresh list
    } catch (error) {
        log(`Error retrying workflow ${workflowId}`, error, 'error');
    }
}
window.retryWorkflowFromDebug = retryWorkflowFromDebug;

async function rewindWorkflow(workflowId) {
    if (!confirm('Are you sure you want to rewind this workflow to the previous step? This might have side effects.')) return;

    try {
        const response = await fetch(`${API_BASE_URL}/workflow/${workflowId}/rewind`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        if (!response.ok) throw new Error((await response.json()).detail);
        
        log(`Workflow ${workflowId} rewound.`, null, 'success');
        fetchDebugWorkflows(); // Refresh list
    } catch (error) {
        log(`Error rewinding workflow ${workflowId}`, error, 'error');
    }
}
window.rewindWorkflow = rewindWorkflow;

async function loadWorkflow(workflowId) {
    log(`Loading workflow ${workflowId} from debug list...`, null, 'info');
    
    // Hide debug view, show workflow view
    const initialView = document.getElementById('initial-view');
    const workflowView = document.getElementById('workflow-view');
    const debugView = document.getElementById('debug-view');
    
    initialView.style.display = 'none';
    debugView.style.display = 'none';
    workflowView.style.display = 'flex';
    
    // Connect WebSocket
    connectWebSocket(workflowId);
    
    // Fetch full status to populate UI immediately
    try {
        const response = await fetch(`${API_BASE_URL}/workflow/${workflowId}/status`);
        if (!response.ok) throw new Error('Failed to load workflow');
        const data = await response.json();
        
        // Transform status response to match updateUI expectation if needed
        // The status endpoint returns almost exactly what updateUI needs
        // We might need to manually construct the object if fields differ slightly
        // status endpoint: { workflow_id, status, current_step_name, state, ... }
        // updateUI expects: { id, status, state, steps_config, current_step }
        // Wait, status endpoint doesn't return steps_config! 
        // We need the full initial state payload which the WebSocket sends on connect.
        // Connecting the socket above should trigger the initial state send.
        
        // Let's rely on the WebSocket's initial message to populate the UI.
        // But we should ensure the "Back/Restart" button is visible
        document.getElementById('restart-button-header').style.display = 'inline-block';
        
        // Trigger log fetch manually since we might be on log-view already
        // Set currentWorkflow tentatively so fetchServerLogs has an ID to work with
        currentWorkflow = { id: workflowId }; 
        fetchServerLogs();

    } catch (error) {
        log('Error loading workflow details', error, 'error');
    }
}
window.loadWorkflow = loadWorkflow;

// --- WebSocket Communication ---

let reconnectInterval = 1000;
let maxReconnectInterval = 30000;
let reconnectTimer = null;

function connectWebSocket(workflowId) {
    if (workflowSocket) {
        // If already connected to the same ID, do nothing
        if (workflowSocket.url.includes(workflowId) && workflowSocket.readyState === WebSocket.OPEN) return;
        workflowSocket.close();
    }

    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}${API_BASE_URL}/workflow/${workflowId}/subscribe`;
    
    log(`Connecting to WebSocket: ${wsUrl}`, null, 'info');
    workflowSocket = new WebSocket(wsUrl);

    workflowSocket.onopen = () => {
        log('WebSocket connection established.', null, 'success');
        reconnectInterval = 1000; // Reset retry interval on success
        if (reconnectTimer) clearTimeout(reconnectTimer);
    };

    workflowSocket.onerror = (error) => {
        // log('WebSocket error.', error, 'error'); 
        // Dont log error object directly as it usually contains no info in JS
        console.error("WebSocket Error:", error);
    };

    workflowSocket.onclose = (event) => {
        if (event.wasClean) {
            log(`WebSocket connection closed cleanly. Code=${event.code} Reason=${event.reason}`);
        } else {
            log('WebSocket connection died. Reconnecting...', null, 'warn');
            
            // Retry logic
            reconnectTimer = setTimeout(() => {
                log(`Attempting to reconnect (Interval: ${reconnectInterval}ms)...`, null, 'info');
                connectWebSocket(workflowId);
                
                // Exponential backoff
                reconnectInterval = Math.min(reconnectInterval * 2, maxReconnectInterval);
            }, reconnectInterval);
        }
    };

    workflowSocket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            log('Real-time update received', data, 'info');
            updateUI(data);
        } catch (e) {
            log('Error processing WebSocket message', e, 'error');
        }
    };
}

function disconnectWebSocket() {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (workflowSocket) {
        workflowSocket.onclose = null; // Disable reconnect logic
        workflowSocket.close();
        workflowSocket = null;
    }
}

// --- Utility Functions ---

async function fetchServerLogs() {
    if (!currentWorkflow) return;
    
    const logOutputElement = document.getElementById('log-output');
    if (!logOutputElement) return;

    logOutputElement.innerHTML = '<div class="log-entry log-info"><span class="timestamp">...</span> - Fetching server logs...</div>';

    try {
        const response = await fetch(`${API_BASE_URL}/workflow/${currentWorkflow.id}/logs?limit=100`);
        if (!response.ok) throw new Error((await response.json()).detail || 'Failed to fetch logs');
        
        const logs = await response.json();
        
        // Clear and render
        logOutputElement.innerHTML = '';
        
        if (logs.length === 0) {
            logOutputElement.innerHTML = '<div class="log-entry log-info">No logs found on server.</div>';
            return;
        }

        // Logs come in reverse chronological order (newest first), usually we want to display oldest first?
        // Or newest at top?
        // The SQL query says: ORDER BY logged_at DESC
        // So logs[0] is the newest.
        // Usually logs are read top-down (oldest to newest).
        // Let's reverse them for display.
        logs.reverse().forEach(logItem => {
            const entry = document.createElement('div');
            // logItem: { log_level, message, logged_at, step_name, ... }
            const levelClass = `log-${logItem.log_level.toLowerCase()}`;
            entry.classList.add('log-entry', levelClass);
            
            const timeStr = new Date(logItem.logged_at).toLocaleTimeString();
            const stepStr = logItem.step_name ? `[${logItem.step_name}] ` : '';
            
            entry.innerHTML = `<span class="timestamp">${timeStr}</span> - ${stepStr}${logItem.message}`;
            
            // Add metadata if present (e.g. error details)
            if (logItem.metadata && Object.keys(logItem.metadata).length > 0) {
                 const metaDiv = document.createElement('div');
                 metaDiv.style.fontSize = '0.85em';
                 metaDiv.style.marginLeft = '20px';
                 metaDiv.style.color = '#aaa';
                 metaDiv.innerText = JSON.stringify(logItem.metadata);
                 entry.appendChild(metaDiv);
            }

            logOutputElement.appendChild(entry);
        });
        
        // Scroll to bottom
        logOutputElement.scrollTop = logOutputElement.scrollHeight;

    } catch (error) {
        console.error(error);
        logOutputElement.innerHTML += `<div class="log-entry log-error">Failed to fetch server logs: ${error.message}</div>`;
    }
}
window.fetchServerLogs = fetchServerLogs;

function log(message, data, level = 'info') {
    const logOutputElement = document.getElementById('log-output'); // Corrected ID to match index.html
    if (!logOutputElement) {
        console.warn('log-output element not found. Logging to console instead.');
        console.log(`[${new Date().toLocaleTimeString()}] ${message}`); // Fallback
        return;
    }

    const entry = document.createElement('div');
    entry.classList.add('log-entry', `log-${level}`);
    entry.innerHTML = `<span class="timestamp">${new Date().toLocaleTimeString()}</span> - ${message}`;
    logOutputElement.appendChild(entry);
    logOutputElement.scrollTop = logOutputElement.scrollHeight;
}