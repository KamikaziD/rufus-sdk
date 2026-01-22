from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from rufus.models import AsyncWorkflowStep, StepContext
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import os

class SlackNotificationStepInput(BaseModel):
    """Input model for the SlackNotificationStep."""
    channel: str = Field(..., description="The Slack channel ID or name (e.g., #general, @username).")
    message: str = Field(..., description="The text of the message to send.")
    slack_token: Optional[str] = Field(None, description="The Slack Bot User OAuth Token. Defaults to SLACK_BOT_TOKEN environment variable.")

class SlackNotificationStep(AsyncWorkflowStep):
    """
    A workflow step to send notifications to Slack.
    This step demonstrates integration with an external API (Slack) and
    the use of asynchronous steps within Rufus.
    """
    # This attribute registers the step type name for auto-discovery
    STEP_TYPE_NAME = "slack.send_message"

    # Define func_path to point to the async function that executes the Slack API call
    func_path: str = "rufus_slack.steps.send_slack_message_async"

async def send_slack_message_async(state: BaseModel, context: StepContext, input_data: SlackNotificationStepInput) -> Dict[str, Any]:
    """
    Asynchronous function that sends a Slack message.
    This function is executed by the Rufus ExecutionProvider (e.g., Celery, ThreadPool).
    """
    try:
        token = input_data.slack_token or os.getenv("SLACK_BOT_TOKEN")
        if not token:
            raise ValueError("Slack Bot Token not provided and SLACK_BOT_TOKEN environment variable not set.")
            
        client = WebClient(token=token)
        
        # Call the Slack Web API to post a message
        response = await client.chat_postMessage(
            channel=input_data.channel,
            text=input_data.message
        )
        
        if response["ok"]:
            print(f"Slack message sent to {input_data.channel}: {input_data.message}")
            return {"slack_message_sent": True, "ts": response["ts"], "channel": response["channel"]}
        else:
            raise SlackApiError(f"Slack API error: {response['error']}", response=response)

    except SlackApiError as e:
        print(f"Error sending Slack message: {e.response['error']}")
        raise
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        raise
