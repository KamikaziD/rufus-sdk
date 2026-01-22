# User Guide: Image Compliance AI Workflow

This document provides instructions on how to use the "Image Compliance Workflow" in the Confucius application. This workflow uses an AI agent to analyze marketing materials for compliance issues.

## Overview

The workflow is powered by an AI agent that uses a multimodal Large Language Model (LLM) through Ollama to analyze images and text. It is designed to help marketing and compliance teams quickly check materials for potential issues.

## Features

- **Image Analysis**: The agent can "see" and analyze the content of an image provided via a URL.
- **Text Analysis**: It can understand and process accompanying text, such as disclaimers or marketing copy.
- **AI-Powered Compliance Check**: The agent uses its understanding of compliance to flag potential issues in the provided materials.

## How it Works

The agent is used within the `ImageComplianceWorkflow`, which is defined in `config/image_compliance_workflow.yaml`. The workflow consists of two steps:

1.  **`Collect_Compliance_Assets`**: This is the first step where you provide the initial data for the workflow. It requires:
    *   `image_url`: A publicly accessible URL to the image you want to analyze.
    *   `compliance_text`: The marketing copy or legal text associated with the image.

2.  **`Run_Image_Compliance_Agent`**: This is an asynchronous step that sends the data to the AI agent (`OCRAgent`).
    *   The agent fetches the image from the URL.
    *   It combines the image with the compliance text and sends them to the LLM with a specific prompt asking it to act as a compliance officer.
    *   The agent's analysis is received and stored in the workflow's state.

## Setup

To use this workflow, your environment must be set up correctly.

1.  **Install Dependencies**: Make sure you have all the required Python packages installed.
    ```bash
    pip install -r requirements.txt
    ```

2.  **Run Ollama**: Ensure your local Ollama instance is running and has the required model. The OCR Agent uses `qwen3-vl:4b`.
    ```bash
    # Pull the model if you don't have it
    ollama pull qwen3-vl:4b
    ```

3.  **Run Redis & Celery**: The workflow uses asynchronous tasks, so you need Redis and a Celery worker running.
    ```bash
    # Start Redis (using Docker is recommended)
    docker run -d --name redis-server -p 6379:6379 redis

    # Start the Celery Worker
    celery -A celery_app.celery_app worker --loglevel=info
    ```
    
4.  **Run the Application**: Start the FastAPI application.
    ```bash
    uvicorn main:app --reload
    ```

## Usage

You can run the workflow using the redesigned demo web interface.

1.  **Open the UI**: Navigate to `http://127.0.0.1:8000` in your browser.

2.  **Select the Workflow**:
    *   In the "Select Workflow" card on the left, choose the **`ImageComplianceWorkflow`** from the dropdown.
    *   The "Initial Data" text area will be pre-filled with an example.

3.  **Provide Inputs and Start**:
    *   Replace the placeholder `image_url` with a direct URL to a real image (e.g., a link to a JPG or PNG file).
    *   Modify the `compliance_text` if desired.
    *   Click **"Start Workflow"**.

4.  **Advance the Workflow**:
    *   The workflow will start, and the UI will switch to the interaction view. The first step, `Collect_Compliance_Assets`, runs instantly.
    *   In the right pane, on the "Current Step" tab, you will see the current step is now `Run_Image_Compliance_Agent`.
    *   Since this step requires no user input, simply click **"Next Step"**.

5.  **Monitor Progress**:
    *   The workflow status will change to `PENDING_ASYASYNC` as the AI agent runs in the background.
    *   You can watch the "Real-time Log" tab to see when the task completes and the workflow state updates automatically via WebSockets. There is no need to manually check the status.

6.  **View the Results**:
    *   Once the agent is finished, the workflow will complete.
    *   Navigate to the "Full State" tab to see the final workflow state. The `analysis_result` field will be populated with the AI's compliance analysis of your image and text.