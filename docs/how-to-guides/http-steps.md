# How to use HTTP steps

This guide covers implementing polyglot workflows using HTTP steps to call external services.

## Overview

HTTP steps enable Ruvon workflows to orchestrate services written in any programming language. The Python-based workflow engine makes HTTP/REST calls to external services (Go, Rust, Node.js, Java, etc.).

## Architecture

```
Ruvon Engine (Python) → HTTP/REST → External Services (Go/Rust/Node.js/Java)
```

## Basic HTTP step

### Define in YAML

```yaml
workflow_type: "PolyglotPipeline"
initial_state_model: "my_app.state_models.PipelineState"

steps:
  - name: "Call_External_Service"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://external-service:8080/api/process"
      headers:
        Content-Type: "application/json"
        Authorization: "Bearer secret-token"
      body:
        user_id: "{{state.user_id}}"
        data: "{{state.input_data}}"
      timeout: 30
    output_key: "service_response"
    automate_next: true
```

**Key configuration:**
- `method` - HTTP method (GET, POST, PUT, DELETE, PATCH)
- `url` - Service endpoint (supports Jinja2 templating)
- `headers` - Request headers (supports templating)
- `body` - Request body (supports templating)
- `timeout` - Request timeout in seconds
- `output_key` - State key for storing response

### No step function needed

HTTP steps don't require Python functions - configuration is declarative.

## Jinja2 templating

Use workflow state in HTTP configuration:

```yaml
http_config:
  method: "POST"
  url: "http://api.example.com/users/{{state.user_id}}/orders"
  headers:
    Authorization: "Bearer {{state.auth_token}}"
    X-Request-ID: "{{state.request_id}}"
  body:
    order_id: "{{state.order_id}}"
    amount: "{{state.amount}}"
    customer:
      name: "{{state.customer_name}}"
      email: "{{state.customer_email}}"
```

**Available variables:**
- `state.*` - Any field from workflow state
- Standard Jinja2 filters and expressions

## Multi-language pipeline

Orchestrate services in different languages:

```yaml
workflow_type: "MLPipeline"
initial_state_model: "my_app.state_models.MLState"

steps:
  # Step 1: Python validation
  - name: "Validate_Input"
    type: "STANDARD"
    function: "my_app.steps.validate"
    automate_next: true

  # Step 2: Go service (high-performance data processing)
  - name: "Process_Data_Go"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://go-processor:8080/process"
      headers:
        Content-Type: "application/json"
      body:
        data: "{{state.validated_data}}"
        config: "{{state.processing_config}}"
      timeout: 60
    output_key: "processed_data"
    automate_next: true

  # Step 3: Rust service (ML inference)
  - name: "Run_Inference_Rust"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://rust-ml:8080/predict"
      headers:
        Content-Type: "application/json"
      body:
        features: "{{state.processed_data.features}}"
        model_id: "{{state.model_id}}"
      timeout: 30
    output_key: "predictions"
    automate_next: true

  # Step 4: Node.js service (notifications)
  - name: "Send_Notifications_Node"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://notification-service:3000/send"
      headers:
        Content-Type: "application/json"
      body:
        user_id: "{{state.user_id}}"
        result: "{{state.predictions.result}}"
        channels: ["email", "sms"]
      timeout: 10
    output_key: "notification_status"
```

## HTTP methods

### GET request

```yaml
- name: "Fetch_User_Data"
  type: "HTTP"
  http_config:
    method: "GET"
    url: "http://user-service:8080/users/{{state.user_id}}"
    headers:
      Authorization: "Bearer {{state.token}}"
    timeout: 10
  output_key: "user_data"
```

### POST request

```yaml
- name: "Create_Order"
  type: "HTTP"
  http_config:
    method: "POST"
    url: "http://order-service:8080/orders"
    headers:
      Content-Type: "application/json"
    body:
      customer_id: "{{state.customer_id}}"
      items: "{{state.cart_items}}"
    timeout: 30
  output_key: "order_result"
```

### PUT request

```yaml
- name: "Update_Status"
  type: "HTTP"
  http_config:
    method: "PUT"
    url: "http://status-service:8080/orders/{{state.order_id}}"
    headers:
      Content-Type: "application/json"
    body:
      status: "completed"
      updated_by: "{{state.user_id}}"
    timeout: 10
  output_key: "update_result"
```

### DELETE request

```yaml
- name: "Cancel_Order"
  type: "HTTP"
  http_config:
    method: "DELETE"
    url: "http://order-service:8080/orders/{{state.order_id}}"
    headers:
      Authorization: "Bearer {{state.token}}"
    timeout: 10
  output_key: "cancel_result"
```

## Response handling

HTTP step responses are automatically parsed and merged into state:

```python
# Before HTTP step
state.user_id = "123"

# HTTP step returns: {"name": "John", "email": "john@example.com"}

# After HTTP step (with output_key: "user_data")
state.user_data = {
    "name": "John",
    "email": "john@example.com"
}
```

## Error handling

Handle HTTP errors with decision steps:

```yaml
steps:
  - name: "Call_External_API"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://external-api:8080/process"
      body:
        data: "{{state.input}}"
      timeout: 30
    output_key: "api_response"

  # Check for errors
  - name: "Check_API_Response"
    type: "DECISION"
    function: "my_app.steps.check_api_response"
    routes:
      - condition: "state.api_response.status == 'success'"
        target: "Process_Success"
      - condition: "state.api_response.status == 'error'"
        target: "Handle_Error"
```

```python
def check_api_response(state: PipelineState, context: StepContext) -> dict:
    """Check API response and handle errors."""

    if hasattr(state, 'api_response'):
        return {"response_checked": True}
    else:
        # HTTP step failed
        return {"response_checked": True, "had_error": True}
```

## Service discovery

Use environment variables for dynamic URLs:

```yaml
- name: "Call_Payment_Service"
  type: "HTTP"
  http_config:
    method: "POST"
    url: "{{env.PAYMENT_SERVICE_URL}}/charge"
    headers:
      Content-Type: "application/json"
    body:
      amount: "{{state.amount}}"
    timeout: 30
  output_key: "payment_result"
```

Set environment variable:

```bash
export PAYMENT_SERVICE_URL="http://payment-service:8080"
```

## Authentication patterns

### Bearer token

```yaml
http_config:
  headers:
    Authorization: "Bearer {{state.auth_token}}"
```

### API key

```yaml
http_config:
  headers:
    X-API-Key: "{{state.api_key}}"
```

### Basic auth

```yaml
http_config:
  headers:
    Authorization: "Basic {{state.basic_auth_token}}"
```

## Retry configuration

Implement retry logic in decision steps:

```yaml
steps:
  - name: "Call_API_With_Retry"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://flaky-service:8080/api"
      body:
        data: "{{state.input}}"
      timeout: 10
    output_key: "api_response"

  - name: "Check_Retry"
    type: "DECISION"
    function: "my_app.steps.check_retry"
    routes:
      - condition: "state.api_response is not None"
        target: "Process_Result"
      - condition: "state.retry_count < 3"
        target: "Call_API_With_Retry"
      - condition: "True"
        target: "Handle_Failure"
```

```python
def check_retry(state: PipelineState, context: StepContext) -> dict:
    """Check if retry is needed."""

    if not hasattr(state, 'retry_count'):
        state.retry_count = 0

    state.retry_count += 1

    return {"retry_checked": True}
```

## Complex request bodies

### Nested JSON

```yaml
http_config:
  body:
    user:
      id: "{{state.user_id}}"
      profile:
        name: "{{state.name}}"
        email: "{{state.email}}"
    order:
      items: "{{state.items}}"
      total: "{{state.total}}"
```

### Arrays

```yaml
http_config:
  body:
    user_ids: ["{{state.user_id}}", "{{state.admin_id}}"]
    tags: "{{state.tags}}"  # If state.tags is already a list
```

## Use cases

### Microservices orchestration

```yaml
# Orchestrate checkout across multiple services
steps:
  - name: "Validate_Cart"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://cart-service:8080/validate"
      body:
        cart_id: "{{state.cart_id}}"

  - name: "Reserve_Inventory"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://inventory-service:8080/reserve"
      body:
        items: "{{state.cart.items}}"

  - name: "Process_Payment"
    type: "HTTP"
    http_config:
      method: "POST"
      url: "http://payment-service:8080/charge"
      body:
        amount: "{{state.cart.total}}"
```

### Legacy system integration

```yaml
# Call legacy SOAP/REST services
- name: "Call_Legacy_System"
  type: "HTTP"
  http_config:
    method: "POST"
    url: "http://legacy-system:8080/api/v1/process"
    headers:
      Content-Type: "application/xml"
      SOAPAction: "ProcessOrder"
    body: |
      <soap:Envelope>
        <soap:Body>
          <ProcessOrder>
            <OrderID>{{state.order_id}}</OrderID>
          </ProcessOrder>
        </soap:Body>
      </soap:Envelope>
```

### Third-party API integration

```yaml
# Call external APIs (Stripe, Twilio, etc.)
- name: "Send_SMS"
  type: "HTTP"
  http_config:
    method: "POST"
    url: "https://api.twilio.com/2010-04-01/Accounts/{{state.twilio_account_id}}/Messages.json"
    headers:
      Authorization: "Basic {{state.twilio_auth_token}}"
    body:
      To: "{{state.phone_number}}"
      From: "{{state.twilio_from_number}}"
      Body: "Your order {{state.order_id}} has shipped!"
```

## Best practices

1. **Implement idempotency** - Ensure external services handle duplicate requests
2. **Set appropriate timeouts** - Match to expected service latency
3. **Use service discovery** - Don't hardcode URLs in production
4. **Handle errors** - Use DECISION steps to check responses
5. **Validate responses** - Check response structure before using data
6. **Log requests** - Include request/response in workflow logs
7. **Secure credentials** - Use environment variables or secrets management
8. **Test services** - Mock HTTP endpoints in tests

## Testing HTTP steps

Mock external services in tests:

```python
import pytest
from unittest.mock import Mock, patch
from ruvon.testing.harness import TestHarness

@pytest.mark.asyncio
async def test_http_step():
    """Test HTTP step with mocked service."""

    harness = TestHarness()

    # Mock HTTP response
    mock_response = {
        "status": "success",
        "result": "processed"
    }

    with patch('aiohttp.ClientSession.post') as mock_post:
        mock_post.return_value.__aenter__.return_value.json.return_value = mock_response

        workflow = await harness.start_workflow(
            workflow_type="PolyglotPipeline",
            initial_data={"user_id": "123"}
        )

        await harness.next_step(workflow.id)

        assert workflow.state.service_response == mock_response
```

## Next steps

- [Add decision steps](decision-steps.md)
- [Implement human-in-the-loop](human-in-loop.md)
- [Enable saga mode](saga-mode.md)

## See also

- [Create workflow guide](create-workflow.md)
- [Testing guide](testing.md)
- CLAUDE.md "Polyglot Support (HTTP Steps)" section
- USAGE_GUIDE.md section 8.1 for HTTP steps
