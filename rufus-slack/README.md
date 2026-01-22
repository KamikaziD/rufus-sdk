# rufus-slack

This is a Rufus marketplace package providing custom workflow steps for integrating with Slack.

## Installation

```bash
pip install rufus-slack
```

## Usage

Once installed, Rufus will automatically discover the steps provided by this package. You can then use them directly in your workflow YAML:

```yaml
workflow_type: SendSlackNotification

steps:
  - name: "SendNotificationToChannel"
    type: slack.send_message
    inputs:
      channel: "#general"
      message: "Hello from Rufus! Workflow {{ workflow.id }} completed."
      # You can also use environment variables for sensitive info like API tokens
      slack_token: "${SLACK_BOT_TOKEN}"
```

### `slack.send_message` Step

**Description**: Sends a message to a specified Slack channel or user.

**Inputs**:
- `channel` (string, required): The Slack channel ID or name (e.g., `#general`, `@username`).
- `message` (string, required): The text of the message to send.
- `slack_token` (string, optional): The Slack Bot User OAuth Token. If not provided, the `SLACK_BOT_TOKEN` environment variable will be used.

## Development

To develop on this package, clone the repository and install in editable mode:

```bash
git clone https://github.com/rufus-ai/rufus-slack.git # Assuming a repo exists
cd rufus-slack
pip install -e .
```

## License

MIT License. See the `LICENSE` file for more details.
