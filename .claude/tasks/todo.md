# Air-Gap Triage Demo — Operation Air-Gap

## Branch: feature/air-gap-triage-demo

## Phase 1 — AI_INFERENCE dispatch in workflow.py
- [x] Import AIInferenceWorkflowStep in workflow.py
- [x] Add inference_provider optional param to Workflow.__init__
- [x] Add AIInferenceWorkflowStep to is_sync_step exclusion list
- [x] Add _execute_ai_inference_step() dispatch block
- [ ] Write tests/sdk/test_ai_inference_step.py

## Phase 2 — worker.js: NER model + JS globals
- [x] Add _nerPipeline variable
- [x] Extend _loadModel() with "ner" branch (unload + load)
- [x] Add globalThis.runNERInference callback
- [x] Add ner_model_loading / ner_model_ready postMessage types

## Phase 3 — worker.js: Workflow 5 Python code
- [x] FieldTechState Pydantic model
- [x] SEVERITY_KEYWORDS + INCIDENT_KEYWORDS dicts
- [x] Step functions: capture_report, run_ner_analysis, build_redacted_payload,
      route_by_severity, log_standard_incident, escalate_incident, store_for_forward
- [x] wf5_steps list
- [x] run_workflow "FieldTechTriage" branch
- [x] Timeout entry for FieldTechTriage

## Phase 4 — index.html: Card 5 + plumbing
- [x] Card 5 HTML (after card 4)
- [x] WORKFLOW_STEPS dict: add FieldTechTriage
- [x] WF_ID dict: add FieldTechTriage -> wf5
- [x] enableButtons(): add btn-wf5
- [x] runWorkflow() defaultData: add FieldTechTriage
- [x] buildResultRows(): add FieldTechTriage case
- [x] historyKeyResult(): add FieldTechTriage
- [x] handleWorkerMessage(): ner_model_loading, ner_model_ready cases

## Phase 5 — Tests & Commit
- [ ] Run pytest to ensure no regressions
- [ ] Commit and push

---

## Review
(to be filled after completion)
