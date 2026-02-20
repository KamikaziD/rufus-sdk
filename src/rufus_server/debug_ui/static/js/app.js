// --- Global State ---
let currentWorkflow = null;
let availableWorkflows = [];
let workflowSocket = null;
let subscribedWorkflows = new Set(); // Track which workflows we're subscribed to
let currentStepInfoCache = null; // Cache for step info to avoid redundant fetches
let cachedStepsConfig = null; // Cache steps_config from initial_state (rich format with correct type names)
let cachedSkippedSteps = []; // Cache skipped_steps across Redis snapshots
let currentChildWorkflow = null; // Track active child/sub-workflow subscription
let previousState = null; // Track previous state for diff visualization
let stateChangeHistory = []; // History of state changes
let previousStep = null; // Track previous step index

// Declare dom globally, but initialize its properties in init()
let dom = {};

const API_BASE_URL = '/api/v1'; // This remains global

// Reconnection state
let reconnectInterval = 1000;
let reconnectTimer = null;
const maxReconnectInterval = 30000;
let reconnectAttempts = 0;
const maxReconnectAttempts = 5;

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
        newWorkflowButton: document.getElementById('new-workflow-button'),
        checkStatusButton: document.getElementById('check-status-button'),
        resumeButton: document.getElementById('resume-button'),
        retryButton: document.getElementById('retry-button'),
        // Required Inputs Tab elements
        requiredInputsViewTabButton: document.querySelector('.tab-button[data-tab="required-inputs-view"]'),
        requiredInputsViewTabPane: document.getElementById('required-inputs-view'),
        dynamicFormInputs: document.getElementById('dynamic-form-inputs'),
        // Log and State elements
        logOutput: document.getElementById('log-output'),
        fullStatePre: document.getElementById('full-state-pre'),
        stateChangesList: document.getElementById('state-changes-list'),
    };

    log('Initializing frontend...'); // Now log is called after dom is initialized
    setupEventListeners();
    applyInitialTheme();
    loadAvailableWorkflows();
    showTab('log-view'); // Default to showing the log view

    // Connect to WebSocket on page load (single persistent connection)
    initWebSocket();
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
    if (dom.newWorkflowButton) dom.newWorkflowButton.onclick = resetUI;
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
    // Unsubscribe from current workflow (but keep WebSocket connection alive)
    if (currentWorkflow) {
        unsubscribeFromWorkflow(currentWorkflow.id);
    }

    // Unsubscribe from child workflow if active
    if (currentChildWorkflow) {
        unsubscribeFromWorkflow(currentChildWorkflow.id);
        currentChildWorkflow = null;
    }

    currentWorkflow = null;
    currentStepInfoCache = null; // Clear cache on reset
    cachedStepsConfig = null; // Clear steps config cache on reset
    cachedSkippedSteps = []; // Clear skipped steps cache on reset

    // Show initial view, hide workflow view
    dom.initialView.style.display = 'flex';
    dom.workflowView.style.display = 'none';
    dom.restartButtonHeader.style.display = 'none';

    // Clear dynamic content
    dom.logOutput.innerHTML = '';
    dom.fullStatePre.textContent = '';
    dom.visualizerList.innerHTML = '';
    dom.dynamicFormInputs.innerHTML = ''; // Clear form inputs in the tab
    clearChildSteps();

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

        console.log('=== Workflow Start Response ===');
        console.log('response.ok:', response.ok);
        console.log('response.status:', response.status);
        console.log('data:', data);
        console.log('data.workflow_id:', data.workflow_id);
        console.log('===============================');

        if (!response.ok) throw new Error(data.detail || 'Failed to start workflow');

        log('Workflow started successfully', data, 'success');

        // Hide initial view, show workflow view
        dom.initialView.style.display = 'none';
        dom.workflowView.style.display = 'flex';
        dom.restartButtonHeader.style.display = 'inline-block';

        // Set currentWorkflow so incoming WS messages are accepted for this workflow
        currentWorkflow = { id: data.workflow_id };

        // Subscribe to workflow for real-time updates
        console.log('Subscribing to workflow:', data.workflow_id);
        subscribeToWorkflow(data.workflow_id);
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
            body: JSON.stringify({ user_input: inputData }),
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

    // Track state changes
    const hasStateChanged = previousState && JSON.stringify(previousState) !== JSON.stringify(workflowData.state);
    const hasStepChanged = previousStep !== null && previousStep !== workflowData.current_step;

    if (hasStateChanged) {
        recordStateChange(previousState, workflowData.state);
    }

    previousState = workflowData.state ? JSON.parse(JSON.stringify(workflowData.state)) : null;
    previousStep = workflowData.current_step;

    currentWorkflow = workflowData;
    const { id, status, state, current_step } = currentWorkflow;

    // If parent is no longer waiting for a child, unsubscribe from the child
    if (currentChildWorkflow && status !== 'PENDING_SUB_WORKFLOW') {
        unsubscribeFromWorkflow(currentChildWorkflow.id);
        currentChildWorkflow = null;
        clearChildSteps();
    }

    // Prefer live steps_config but fall back to cached initial_state version.
    // The initial_state message uses Python class names (e.g. "CompensatableStep")
    // while subsequent Redis snapshots use YAML type strings (e.g. "STANDARD").
    // Caching the initial_state copy avoids badge text flickering and ensures
    // correct step-name-to-index lookup in renderStepVisualizer.
    const steps_config = (currentWorkflow.steps_config && currentWorkflow.steps_config.length > 0)
        ? currentWorkflow.steps_config
        : (cachedStepsConfig || []);

    // Merge skipped_steps from live data and cache (deduplicated)
    const liveSk = currentWorkflow.skipped_steps || [];
    const skipped_steps = [...new Set([...liveSk, ...cachedSkippedSteps])];

    // 1. Update Status Display & Full State View with animation
    const stateString = JSON.stringify(state, null, 2);
    let statusHTML = `<div><span>ID:</span> ${id}</div><div><span>Status:</span> <span class="status-badge status-${status.replace(/\s+/g, '_')} ${hasStepChanged ? 'status-pulse' : ''}">${status}</span></div>`;

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
    renderStepVisualizer(steps_config, current_step, status, skipped_steps);

    // 3. Reset and show/hide buttons based on status
    dom.nextStepButton.style.display = 'none';
    if (dom.newWorkflowButton) dom.newWorkflowButton.style.display = 'none';
    dom.checkStatusButton.style.display = 'none';
    dom.resumeButton.style.display = 'none';
    dom.retryButton.style.display = 'none';
    // dom.openFormButton.style.display = 'none'; // No longer needed
    dom.currentStepName.innerHTML = '...';

    // 4. Update UI based on status
    if (status === 'COMPLETED') {
        dom.currentStepName.innerHTML = `Workflow COMPLETED`;
        if (dom.newWorkflowButton) dom.newWorkflowButton.style.display = 'block';
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
        // Auto-subscribe to child workflow if not already doing so
        if (childId && childId !== 'unknown' &&
            (!currentChildWorkflow || currentChildWorkflow.id !== childId)) {
            currentChildWorkflow = { id: childId };
            subscribeToWorkflow(childId);
            log(`Auto-subscribing to child workflow: ${childId}`, null, 'info');
        }
        return;
    }

    // 5. Determine whether to show "Next Step" or "Submit Review"
    // and if input is needed (which might auto-switch tab)
    await fetchCurrentStepInfo(); // AWAIT this call
}

function renderStepVisualizer(steps = [], currentStep, status, skippedSteps = []) {
    // currentStep may be a string step name (from server) or a legacy integer index.
    // Convert to an integer index so comparisons work correctly.
    const currentStepIndex = typeof currentStep === 'number'
        ? currentStep
        : steps.findIndex(s => s.name === currentStep);

    dom.visualizerList.innerHTML = steps.map((step, index) => {
        let className = '';
        let icon = '';
        let statusText = '';

        if (status === 'COMPLETED' || index < currentStepIndex) {
            className = 'completed';
            icon = '<i class="fas fa-check-circle step-icon"></i>';
            statusText = '<span class="step-status">Completed</span>';
        } else if (index === currentStepIndex) {
            className = 'current';
            if (status === 'PENDING_ASYNC') {
                icon = '<i class="fas fa-spinner fa-spin step-icon"></i>';
                statusText = '<span class="step-status">Running...</span>';
            } else if (status === 'WAITING_HUMAN') {
                icon = '<i class="fas fa-user-clock step-icon"></i>';
                statusText = '<span class="step-status">Waiting</span>';
            } else if (status === 'FAILED') {
                icon = '<i class="fas fa-exclamation-circle step-icon error"></i>';
                statusText = '<span class="step-status error">Failed</span>';
            } else {
                icon = '<i class="fas fa-play-circle step-icon"></i>';
                statusText = '<span class="step-status">Active</span>';
            }
        } else if (skippedSteps.includes(step.name)) {
            className = 'skipped';
            icon = '<i class="fas fa-forward step-icon"></i>';
            statusText = '<span class="step-status">Skipped</span>';
        } else {
            className = 'pending';
            icon = '<i class="far fa-circle step-icon"></i>';
            statusText = '<span class="step-status">Pending</span>';
        }

        return `<li class="${className}" data-step-index="${index}">
            ${icon}
            <div class="step-content">
                <div class="step-header">
                    <span class="step-name">${step.name}</span>
                    <span class="step-type">${step.type}</span>
                </div>
                ${statusText}
            </div>
        </li>`;
    }).join('');
}

function renderChildStepItems(steps = [], currentStep, status) {
    const currentStepIndex = typeof currentStep === 'number'
        ? currentStep
        : steps.findIndex(s => s.name === currentStep);

    return steps.map((step, index) => {
        let className = '';
        let icon = '';
        let statusText = '';

        if (status === 'COMPLETED' || index < currentStepIndex) {
            className = 'completed';
            icon = '<i class="fas fa-check-circle step-icon"></i>';
            statusText = '<span class="step-status">Completed</span>';
        } else if (index === currentStepIndex) {
            className = 'current';
            if (status === 'PENDING_ASYNC') {
                icon = '<i class="fas fa-spinner fa-spin step-icon"></i>';
                statusText = '<span class="step-status">Running...</span>';
            } else if (status === 'FAILED') {
                icon = '<i class="fas fa-exclamation-circle step-icon error"></i>';
                statusText = '<span class="step-status error">Failed</span>';
            } else {
                icon = '<i class="fas fa-play-circle step-icon"></i>';
                statusText = '<span class="step-status">Active</span>';
            }
        } else {
            className = 'pending';
            icon = '<i class="far fa-circle step-icon"></i>';
            statusText = '<span class="step-status">Pending</span>';
        }

        return `<li class="${className}" data-step-index="${index}">
            ${icon}
            <div class="step-content">
                <div class="step-header">
                    <span class="step-name">${step.name}</span>
                    <span class="step-type">${step.type || ''}</span>
                </div>
                ${statusText}
            </div>
        </li>`;
    }).join('');
}

function renderChildSteps(childData) {
    const childSteps = childData.steps_config || [];
    const childCurrentStep = childData.current_step;
    const childStatus = childData.status || 'ACTIVE';
    const childType = childData.workflow_type || 'Child';

    let container = document.getElementById('child-workflow-section');
    if (!container) {
        container = document.createElement('div');
        container.id = 'child-workflow-section';
        container.className = 'child-workflow-section';
        dom.visualizerList.parentElement.appendChild(container);
    }

    container.innerHTML = `
        <div class="child-workflow-header">
            <i class="fas fa-code-branch"></i> Sub-workflow: ${childType}
            <span class="status-badge status-${childStatus.replace(/\s+/g, '_')}">${childStatus}</span>
        </div>
        <ul class="child-step-list">
            ${renderChildStepItems(childSteps, childCurrentStep, childStatus)}
        </ul>
    `;
}

function clearChildSteps() {
    const el = document.getElementById('child-workflow-section');
    if (el) el.remove();
}

async function fetchCurrentStepInfo() {
    // Guard: don't show action buttons if the workflow has already completed
    if (!currentWorkflow || currentWorkflow.status === 'COMPLETED') return;
    try {
        const res = await fetch(`${API_BASE_URL}/workflow/${currentWorkflow.id}/current_step_info`);
        if (!res.ok) throw new Error((await res.json()).detail);
        currentStepInfoCache = await res.json(); // Cache the step info

        // Re-check after the async gap — workflow may have completed while we were fetching
        if (!currentWorkflow || currentWorkflow.status === 'COMPLETED') return;

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

    // 1. Unsubscribe from any previously viewed workflow
    if (currentWorkflow) {
        unsubscribeFromWorkflow(currentWorkflow.id);
    }
    if (currentChildWorkflow) {
        unsubscribeFromWorkflow(currentChildWorkflow.id);
        currentChildWorkflow = null;
        clearChildSteps();
    }

    // 2. Clear all stale caches so previous workflow data can't bleed through
    currentWorkflow = null;
    currentStepInfoCache = null;
    cachedStepsConfig = null;
    cachedSkippedSteps = [];
    previousState = null;
    previousStep = null;
    stateChangeHistory = [];

    // 3. Clear UI content
    dom.logOutput.innerHTML = '';
    dom.fullStatePre.textContent = '';
    dom.visualizerList.innerHTML = '';
    dom.dynamicFormInputs.innerHTML = '';
    dom.currentStepName.innerHTML = '...';
    dom.statusDisplay.innerHTML = '';

    // 4. Set currentWorkflow BEFORE subscribing so the WebSocket initial_state
    //    message passes the `data.workflow_id === currentWorkflow.id` guard in onmessage
    currentWorkflow = { id: workflowId };

    // 5. Switch views
    document.getElementById('initial-view').style.display = 'none';
    document.getElementById('debug-view').style.display = 'none';
    document.getElementById('workflow-view').style.display = 'flex';
    document.getElementById('restart-button-header').style.display = 'inline-block';

    showTab('log-view');

    // 6. Subscribe — the server will push initial_state which drives updateUI()
    subscribeToWorkflow(workflowId);

    // 7. Also fetch server logs immediately (initial_state doesn't include them)
    fetchServerLogs();
}
window.loadWorkflow = loadWorkflow;

// --- WebSocket Communication ---

/**
 * Initialize WebSocket connection on page load.
 * Single persistent connection for all workflow subscriptions.
 */
function initWebSocket() {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}${API_BASE_URL}/subscribe`;

    console.log('[WS-INIT] Connecting to WebSocket:', wsUrl);
    log(`Connecting to WebSocket: ${wsUrl}`, null, 'info');

    workflowSocket = new WebSocket(wsUrl);

    workflowSocket.onopen = () => {
        console.log('[WS-INIT] WebSocket connection established');
        log('WebSocket connection established.', null, 'success');
        reconnectInterval = 1000; // Reset retry interval on success
        reconnectAttempts = 0; // Reset attempt counter on success
        if (reconnectTimer) clearTimeout(reconnectTimer);

        // Resubscribe to any workflows we were watching
        subscribedWorkflows.forEach(workflowId => {
            subscribeToWorkflow(workflowId);
        });
    };

    workflowSocket.onerror = (error) => {
        console.error('[WS-ERROR] WebSocket error:', error);
    };

    workflowSocket.onclose = (event) => {
        console.log('[WS-CLOSE] WebSocket closed:', event.code, event.reason);

        if (event.wasClean) {
            log(`WebSocket connection closed cleanly. Code=${event.code} Reason=${event.reason}`);
        } else {
            reconnectAttempts++;

            if (reconnectAttempts >= maxReconnectAttempts) {
                log(`Max reconnection attempts (${maxReconnectAttempts}) reached. Please refresh the page.`, null, 'error');
                console.error('[WS-ERROR] Max reconnection attempts reached. Stopping reconnection loop.');
                return;
            }

            log(`WebSocket connection died. Reconnecting... (Attempt ${reconnectAttempts}/${maxReconnectAttempts})`, null, 'warn');

            // Retry logic with exponential backoff
            reconnectTimer = setTimeout(() => {
                log(`Attempting to reconnect (Interval: ${reconnectInterval}ms)...`, null, 'info');
                initWebSocket();

                reconnectInterval = Math.min(reconnectInterval * 2, maxReconnectInterval);
            }, reconnectInterval);
        }
    };

    workflowSocket.onmessage = (event) => {
        console.log('[WS-MESSAGE] Received:', event.data.substring(0, 200));

        try {
            const data = JSON.parse(event.data);
            console.log('[WS-MESSAGE] Type:', data.type, 'Workflow:', data.workflow_id);

            // Handle handshake messages
            if (data.type === 'handshake') {
                console.log('[WS-HANDSHAKE]', data.state);
                if (data.state === 'connecting') {
                    log('WebSocket handshake: connecting...', null, 'info');
                } else if (data.state === 'connected') {
                    log('WebSocket handshake: connected!', null, 'success');
                }
                return;
            }

            // Handle ping messages - respond with pong
            if (data.type === 'ping') {
                console.log('[WS-PING] Received, sending pong...');
                workflowSocket.send(JSON.stringify({
                    type: 'pong',
                    timestamp: data.timestamp
                }));
                return;
            }

            // Handle subscription confirmations
            if (data.type === 'subscribed') {
                console.log('[WS-SUB] Subscribed to workflow:', data.workflow_id);
                log(`Subscribed to workflow ${data.workflow_id}`, null, 'success');
                return;
            }

            if (data.type === 'unsubscribed') {
                console.log('[WS-UNSUB] Unsubscribed from workflow:', data.workflow_id);
                log(`Unsubscribed from workflow ${data.workflow_id}`, null, 'info');
                return;
            }

            // Handle initial_state messages
            if (data.type === 'initial_state') {
                console.log('[WS-INITIAL] Initial state for workflow:', data.workflow_id);
                // Cache the rich steps_config format (Python class names, full details)
                // before subsequent Redis snapshots overwrite it with YAML type strings
                if (currentWorkflow && data.workflow_id === currentWorkflow.id) {
                    if (data.steps_config && data.steps_config.length > 0) {
                        cachedStepsConfig = data.steps_config;
                    }
                    if (data.skipped_steps && data.skipped_steps.length > 0) {
                        cachedSkippedSteps = data.skipped_steps;
                    }
                    log('Received initial workflow state', data, 'info');
                    updateUI(data);
                } else if (currentChildWorkflow && data.workflow_id === currentChildWorkflow.id) {
                    // Initial state for child workflow
                    currentChildWorkflow = { ...currentChildWorkflow, ...data };
                    renderChildSteps(data);
                }
                return;
            }

            // Handle workflow updates
            const workflowId = data.workflow_id || data.id;

            // Skip raw observability events (event_type messages) — they carry step-level
            // status ("COMPLETED" = step done) not workflow status, and lack the state
            // shape that updateUI() requires. Log them for debugging only.
            if (data.event_type) {
                const evtStatus = data.new_status || data.status || '';
                console.log(`[WS-EVENT] ${data.event_type} workflow:${workflowId} status:${evtStatus}`);
                return;
            }

            // Full workflow state snapshots: {id, status, current_step, state, ...}
            console.log('[WS-UPDATE] Workflow update:', workflowId, 'Status:', data.status);

            // Route to parent or child handler
            if (currentWorkflow && workflowId === currentWorkflow.id) {
                log('Real-time update received', data, 'info');
                updateUI(data);
            } else if (currentChildWorkflow && workflowId === currentChildWorkflow.id) {
                currentChildWorkflow = { ...currentChildWorkflow, ...data };
                renderChildSteps(data);
            } else {
                console.log('[WS-UPDATE] Ignoring update for different workflow');
            }

        } catch (e) {
            console.error('[WS-ERROR] Failed to parse message:', e);
            log('Error processing WebSocket message', e, 'error');
        }
    };
}

/**
 * Subscribe to a specific workflow's updates.
 */
function subscribeToWorkflow(workflowId) {
    console.log('[WS-SUB] Subscribing to workflow:', workflowId);

    if (!workflowSocket || workflowSocket.readyState !== WebSocket.OPEN) {
        console.warn('[WS-SUB] WebSocket not ready, queueing subscription');
        subscribedWorkflows.add(workflowId);
        return;
    }

    subscribedWorkflows.add(workflowId);

    workflowSocket.send(JSON.stringify({
        action: 'subscribe',
        workflow_id: workflowId
    }));

    log(`Subscribing to workflow ${workflowId}...`, null, 'info');
}

/**
 * Unsubscribe from a specific workflow's updates.
 */
function unsubscribeFromWorkflow(workflowId) {
    console.log('[WS-UNSUB] Unsubscribing from workflow:', workflowId);

    subscribedWorkflows.delete(workflowId);

    if (workflowSocket && workflowSocket.readyState === WebSocket.OPEN) {
        workflowSocket.send(JSON.stringify({
            action: 'unsubscribe',
            workflow_id: workflowId
        }));
    }

    log(`Unsubscribed from workflow ${workflowId}`, null, 'info');
}

/**
 * Close WebSocket connection (for cleanup).
 */
function disconnectWebSocket() {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (workflowSocket) {
        workflowSocket.close();
        workflowSocket = null;
    }
    subscribedWorkflows.clear();
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
// --- State Change Tracking ---
function recordStateChange(oldState, newState) {
    const changes = findStateDifferences(oldState, newState);
    if (changes.length > 0) {
        const timestamp = new Date().toLocaleTimeString();
        stateChangeHistory.push({ timestamp, changes });

        // Show notification of state change
        showStateChangeNotification(changes);

        // Update state changes tab
        updateStateChangesTab();

        // Keep only last 50 changes
        if (stateChangeHistory.length > 50) {
            stateChangeHistory.shift();
        }
    }
}

function updateStateChangesTab() {
    if (!dom.stateChangesList) return;

    if (stateChangeHistory.length === 0) {
        dom.stateChangesList.innerHTML = '<p class="empty-state">No state changes yet. Changes will appear here as the workflow progresses.</p>';
        return;
    }

    const html = stateChangeHistory.slice().reverse().map(entry => `
        <div class="state-change-entry">
            <div class="state-change-header">
                <span class="timestamp"><i class="fas fa-clock"></i> ${entry.timestamp}</span>
                <span class="change-count">${entry.changes.length} change${entry.changes.length > 1 ? 's' : ''}</span>
            </div>
            <div class="state-change-details">
                ${entry.changes.map(change => `
                    <div class="state-change-item ${change.type}">
                        <i class="fas ${change.type === 'added' ? 'fa-plus-circle' : 'fa-edit'}"></i>
                        <span class="change-path">${change.path}</span>
                        ${change.type === 'added'
                            ? `<span class="change-value new">${formatValue(change.value)}</span>`
                            : `<span class="change-value old">${formatValue(change.oldValue)}</span>
                               <i class="fas fa-arrow-right"></i>
                               <span class="change-value new">${formatValue(change.newValue)}</span>`
                        }
                    </div>
                `).join('')}
            </div>
        </div>
    `).join('');

    dom.stateChangesList.innerHTML = html;
}

function formatValue(value) {
    if (value === null) return '<em>null</em>';
    if (value === undefined) return '<em>undefined</em>';
    if (typeof value === 'object') return JSON.stringify(value);
    if (typeof value === 'string') return `"${value}"`;
    return String(value);
}

function findStateDifferences(oldState, newState, path = '') {
    const changes = [];
    
    if (!oldState || !newState) return changes;
    
    // Check for new or changed keys in newState
    Object.keys(newState).forEach(key => {
        const currentPath = path ? `${path}.${key}` : key;
        const oldValue = oldState[key];
        const newValue = newState[key];
        
        if (oldValue === undefined) {
            changes.push({ path: currentPath, type: 'added', value: newValue });
        } else if (JSON.stringify(oldValue) !== JSON.stringify(newValue)) {
            if (typeof newValue === 'object' && newValue !== null && !Array.isArray(newValue)) {
                changes.push(...findStateDifferences(oldValue, newValue, currentPath));
            } else {
                changes.push({ path: currentPath, type: 'changed', oldValue, newValue });
            }
        }
    });
    
    return changes;
}

function showStateChangeNotification(changes) {
    // Create a notification element
    const notification = document.createElement('div');
    notification.className = 'state-change-notification';
    notification.innerHTML = `
        <i class="fas fa-sync-alt"></i>
        <span>State Updated: ${changes.length} change${changes.length > 1 ? 's' : ''}</span>
    `;
    
    dom.statusDisplay.appendChild(notification);
    
    // Animate in
    setTimeout(() => notification.classList.add('show'), 10);
    
    // Remove after 2 seconds
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => notification.remove(), 300);
    }, 2000);
}
