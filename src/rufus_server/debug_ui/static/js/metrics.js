// metrics.js - Logic for the Metrics Dashboard

const METRICS_API_URL = '/api/v1/metrics';

// Function to fetch metrics summary
async function fetchMetricsSummary() {
    try {
        const response = await fetch(`${METRICS_API_URL}/summary?hours=24`);
        if (!response.ok) throw new Error('Failed to fetch metrics summary');
        const data = await response.json();
        renderMetricsSummary(data);
    } catch (error) {
        log('Error fetching metrics summary', error, 'error');
    }
}

// Function to render the metrics summary table/cards
function renderMetricsSummary(data) {
    const container = document.getElementById('metrics-content');
    if (!container) return;

    if (data.length === 0) {
        container.innerHTML = '<p>No workflow execution data found for the last 24 hours.</p>';
        return;
    }

    // Calculate totals
    let totalExecutions = 0;
    let totalCompleted = 0;
    let totalFailed = 0;
    let totalPending = 0;

    data.forEach(item => {
        totalExecutions += item.total_executions;
        totalCompleted += item.completed;
        totalFailed += item.failed;
        totalPending += item.pending;
    });

    // Create Summary Cards HTML
    const cardsHtml = `
        <div class="metrics-cards">
            <div class="card metric-card">
                <h3>Total Executions</h3>
                <div class="value">${totalExecutions}</div>
            </div>
            <div class="card metric-card status-COMPLETED">
                <h3>Completed</h3>
                <div class="value">${totalCompleted}</div>
            </div>
            <div class="card metric-card status-FAILED">
                <h3>Failed</h3>
                <div class="value">${totalFailed}</div>
            </div>
            <div class="card metric-card status-ACTIVE">
                <h3>Active/Pending</h3>
                <div class="value">${totalPending}</div>
            </div>
        </div>
    `;

    // Create Detailed Table HTML
    let tableHtml = `
        <div class="card">
            <div class="card-header">
                <h2>Workflow Type Breakdown</h2>
            </div>
            <div class="card-body">
                <table class="metrics-table">
                    <thead>
                        <tr>
                            <th>Type</th>
                            <th>Total</th>
                            <th>Completed</th>
                            <th>Failed</th>
                            <th>Pending</th>
                            <th>Last Activity</th>
                        </tr>
                    </thead>
                    <tbody>
    `;

    data.forEach(item => {
        tableHtml += `
            <tr>
                <td>${item.workflow_type}</td>
                <td>${item.total_executions}</td>
                <td>${item.completed}</td>
                <td>${item.failed}</td>
                <td>${item.pending}</td>
                <td>${new Date(item.last_execution).toLocaleString()}</td>
            </tr>
        `;
    });

    tableHtml += `
                    </tbody>
                </table>
            </div>
        </div>
    `;

    container.innerHTML = cardsHtml + tableHtml;
}

// Export functions to be used by app.js or index.html
// Since we aren't using modules in index.html yet, we attach to window or just let them be global.
window.fetchMetricsSummary = fetchMetricsSummary;
