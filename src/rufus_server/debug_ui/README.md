# Rufus Debug UI

Visual workflow inspection and debugging interface, ported from Confucius.

## Overview

The Debug UI provides a web-based interface for:

- **Starting Workflows** - Interactive form to select workflow type and provide initial data
- **Workflow Execution** - Step-by-step visual execution with manual step control
- **State Inspection** - Real-time workflow state visualization (JSON view)
- **System Metrics** - Performance metrics and workflow statistics
- **Debug View** - List of active and failed workflows for troubleshooting
- **Dark/Light Theme** - User preference theme switching

## Access

Once the Rufus Server is running, the Debug UI is available at:

- **Main**: `http://localhost:8000/`
- **Alias**: `http://localhost:8000/debug`

## Features

### 1. Workflow Start Interface

- Dropdown list of all available workflows from registry
- JSON editor for initial workflow data
- Input validation with error messages
- One-click workflow start

### 2. Workflow Execution View

**Status Display:**
- Workflow ID and current status (ACTIVE, PAUSED, COMPLETED, FAILED)
- Current step name and type
- Visual status badges

**Interactive Controls:**
- **Next Step** - Execute the next workflow step
- **Submit Review** - Resume paused workflows (human-in-the-loop)
- **Retry Step** - Retry failed steps
- **Check Status** - Refresh workflow status

### 3. State Inspector

- Real-time JSON view of workflow state
- Syntax-highlighted JSON formatting
- Expandable/collapsible JSON tree
- State updates after each step execution

### 4. Execution Log

- Chronological list of executed steps
- Step name, type, and execution result
- Error messages for failed steps
- Timestamps for each step

### 5. Metrics Dashboard

**System-wide metrics:**
- Total workflows executed (last 24h)
- Success rate percentage
- Average execution time
- Active workflows count
- Failed workflows count

**Per-workflow metrics:**
- Execution time distribution
- Step-level performance
- Error rate by step type

### 6. Debug View

- List of workflows filtered by status
- Search by workflow ID or type
- One-click workflow inspection
- Quick access to failed workflows for debugging

## Architecture

The Debug UI is a **pure frontend application** that communicates with Rufus Server APIs:

```
┌─────────────────┐
│   Debug UI      │ (HTML + JS)
│   /debug        │
└────────┬────────┘
         │
         │ HTTP/REST
         │
    ┌────▼────────────────┐
    │  Rufus Server APIs  │
    │  /api/v1/workflow/* │
    └─────────────────────┘
```

**API Endpoints Used:**
- `GET /api/v1/workflows/registry` - List available workflows
- `POST /api/v1/workflows/start` - Start a new workflow
- `GET /api/v1/workflows/{id}/status` - Get workflow status
- `POST /api/v1/workflows/{id}/next` - Execute next step
- `POST /api/v1/workflows/{id}/resume` - Resume paused workflow
- `POST /api/v1/workflows/{id}/retry` - Retry failed step
- `GET /api/v1/metrics` - System metrics (TODO)

## Files Structure

```
debug_ui/
├── __init__.py          # Package exports
├── router.py            # FastAPI router (serves HTML)
├── README.md            # This file
├── templates/
│   └── index.html       # Main UI template (single-page app)
└── static/
    ├── css/
    │   └── style.css    # UI styling (dark/light themes)
    ├── js/
    │   └── app.js       # Frontend logic (API calls, DOM manipulation)
    └── images/
        └── *.svg        # Icons and graphics
```

## Usage Examples

### Starting a Workflow

1. Open `http://localhost:8000/`
2. Select workflow type from dropdown (e.g., "OrderProcessing")
3. Edit initial data JSON:
   ```json
   {
     "order_id": "ORD-12345",
     "customer_id": "CUST-789",
     "amount": 1299.99
   }
   ```
4. Click "Start Execution"
5. Watch workflow execute step-by-step

### Debugging a Failed Workflow

1. Click "Debug" button in header
2. Filter by status: "FAILED"
3. Click on workflow ID to inspect
4. Review execution log for error messages
5. Click "Retry Step" to re-execute failed step

### Inspecting Workflow State

1. After workflow starts, state is visible in right panel
2. Expand JSON tree to view nested fields
3. State updates automatically after each step
4. Use for debugging state mutations

## Development Notes

### Ported from Confucius

This Debug UI was originally developed for the Confucius workflow engine and has been ported to Rufus with minimal changes:

**Changes Made:**
- Updated branding: "Confucius" → "Rufus"
- Updated tagline to reflect fintech focus
- API endpoints remain compatible (Rufus preserved Confucius API structure)

**Not Changed:**
- Core functionality (workflow execution, state inspection)
- UI/UX design and layout
- Dark/light theme support
- API communication layer

### Future Enhancements

Potential improvements for Rufus-specific features:

- **WebSocket support** for real-time workflow updates (no polling)
- **Workflow graph visualization** (DAG rendering)
- **Sub-workflow inspector** (visualize parent-child relationships)
- **Saga pattern UI** (show compensation steps)
- **Loop step progress** (iteration counter)
- **Fire-and-forget status** (background task tracking)
- **Cron schedule calendar** (visualize scheduled executions)
- **Edge device status** (POS terminal health, offline status)
- **Store-and-Forward queue** (pending offline transactions)

### Customization

**Changing Theme:**
The UI supports dark/light themes via the toggle in the header. Theme preference is saved to localStorage.

**Modifying Styles:**
Edit `static/css/style.css` to customize colors, fonts, and layout.

**Adding Features:**
Edit `static/js/app.js` to add new API calls or UI interactions.

## Troubleshooting

**Debug UI not loading:**
- Check that `debug_ui/templates/` and `debug_ui/static/` exist
- Verify Rufus Server logs for mounting errors
- Ensure port 8000 is not blocked by firewall

**Workflows not appearing in dropdown:**
- Verify `config/workflow_registry.yaml` is valid
- Check Rufus Server logs for registration errors
- Ensure workflow YAML files are in `config/` directory

**"Start Execution" fails:**
- Validate initial data JSON format
- Check Rufus Server API response in browser console
- Verify workflow state model matches initial data schema

**State not updating:**
- Check browser console for JavaScript errors
- Verify API endpoints are responding (check Network tab)
- Try refreshing the page

## Credits

- **Original Design**: Confucius workflow engine (2025)
- **Ported by**: Claude Sonnet 4.5
- **Date**: 2026-02-13
- **License**: Same as Rufus SDK

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) - Main Rufus SDK documentation
- [USAGE_GUIDE.md](../../USAGE_GUIDE.md) - Workflow usage examples
- [CONFUCIUS_VS_RUFUS_ANALYSIS.md](../../CONFUCIUS_VS_RUFUS_ANALYSIS.md) - Feature comparison
