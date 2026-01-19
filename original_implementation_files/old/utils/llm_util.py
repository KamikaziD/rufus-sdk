import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

# Assuming parlant.sdk has an exception for API errors
# If not, we can define a custom exception
try:
    from parlant.sdk.errors import APIStatusError
except ImportError:
    APIStatusError = Exception  # Fallback to a generic exception

import parlant.sdk as p


class EmptyResponseError(Exception):
    """Custom exception for empty responses from the model."""
    pass


def is_empty_response(event: p.Event) -> bool:
    """Check if the event contains an empty response."""
    if not event or not event.content or not event.content.parts:
        return True
    merged_text = '\n'.join(p.text for p in event.content.parts if p.text)
    return not merged_text.strip()


# Retry if the API call fails or if the response is empty
def should_retry(exception):
    """Return True if the exception is an API error or an empty response error."""
    return isinstance(exception, (APIStatusError, EmptyResponseError))


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception(should_retry)
)
async def run_agent_with_retry(agent, invocation_context):
    """
    Run the agent with a retry mechanism for empty responses.
    """
    last_event = None
    async for event in agent.run_async(invocation_context):
        last_event = event

    if is_empty_response(last_event):
        raise EmptyResponseError("Received an empty response from the model.")

    return last_event
