"""
Ollama LLM Inference Tasks for Rufus GPU Workers

Supports all Ollama models:
- Llama 2 (7B, 13B, 70B)
- Llama 3 (8B, 70B)
- Mistral (7B)
- Mixtral (8x7B)
- CodeLlama (7B, 13B, 34B)
- Gemma (2B, 7B)
- And many more...

See: https://ollama.com/library
"""
from rufus.celery_app import celery_app
import logging
import time

logger = logging.getLogger(__name__)


@celery_app.task(
    name="examples.ollama_llm.tasks.generate_text",
    bind=True,
    queue="llm-inference",  # Route to Ollama-enabled workers
    time_limit=300,  # 5 minutes for large models
    soft_time_limit=270,
)
def generate_text(
    self,
    state: dict,
    workflow_id: str,
    prompt: str,
    model: str = "llama2",
    max_tokens: int = 200,
    temperature: float = 0.7,
    **kwargs
):
    """
    Generate text using Ollama LLM on GPU.

    Args:
        state: Workflow state dict
        workflow_id: Workflow UUID
        prompt: Input prompt for the model
        model: Ollama model name (e.g., "llama2", "mistral", "codellama")
        max_tokens: Maximum tokens to generate
        temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative)
        **kwargs: Additional Ollama parameters

    Returns:
        Dict with generated_text and metadata

    Example:
        result = generate_text.apply_async(
            kwargs={
                "state": {...},
                "workflow_id": "123",
                "prompt": "Write a haiku about workflow automation",
                "model": "llama2",
                "temperature": 0.8,
            },
            queue="llm-inference"
        )
    """
    import ollama

    logger.info(
        f"Ollama LLM inference: workflow={workflow_id}, "
        f"model={model}, prompt_length={len(prompt)}"
    )

    try:
        start_time = time.perf_counter()

        # Generate text with Ollama
        response = ollama.generate(
            model=model,
            prompt=prompt,
            options={
                "num_predict": max_tokens,
                "temperature": temperature,
                "top_p": kwargs.get("top_p", 0.9),
                "top_k": kwargs.get("top_k", 40),
                "repeat_penalty": kwargs.get("repeat_penalty", 1.1),
            },
        )

        inference_time = (time.perf_counter() - start_time) * 1000

        generated_text = response["response"]
        total_tokens = response.get("eval_count", 0) + response.get("prompt_eval_count", 0)

        logger.info(
            f"Ollama generation complete: "
            f"model={model}, "
            f"tokens={total_tokens}, "
            f"time={inference_time:.2f}ms, "
            f"speed={total_tokens/(inference_time/1000):.2f} tokens/sec"
        )

        return {
            "generated_text": generated_text,
            "model": model,
            "inference_time_ms": inference_time,
            "total_tokens": total_tokens,
            "prompt_tokens": response.get("prompt_eval_count", 0),
            "completion_tokens": response.get("eval_count", 0),
        }

    except Exception as e:
        logger.exception(f"Ollama inference failed: {e}")
        raise


@celery_app.task(
    name="examples.ollama_llm.tasks.chat_completion",
    bind=True,
    queue="llm-inference",
    time_limit=300,
)
def chat_completion(
    self,
    state: dict,
    workflow_id: str,
    messages: list,
    model: str = "llama2",
    **kwargs
):
    """
    Chat completion using Ollama (multi-turn conversation).

    Args:
        state: Workflow state
        workflow_id: Workflow UUID
        messages: List of chat messages [{"role": "user", "content": "..."}]
        model: Ollama model name
        **kwargs: Additional parameters

    Returns:
        Dict with assistant response

    Example:
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is a workflow engine?"},
        ]
        result = chat_completion.apply_async(
            kwargs={
                "state": {...},
                "workflow_id": "123",
                "messages": messages,
                "model": "llama2",
            },
            queue="llm-inference"
        )
    """
    import ollama

    logger.info(
        f"Ollama chat: workflow={workflow_id}, "
        f"model={model}, messages={len(messages)}"
    )

    try:
        start_time = time.perf_counter()

        # Chat API
        response = ollama.chat(
            model=model,
            messages=messages,
            options={
                "temperature": kwargs.get("temperature", 0.7),
                "top_p": kwargs.get("top_p", 0.9),
            },
        )

        inference_time = (time.perf_counter() - start_time) * 1000

        assistant_message = response["message"]["content"]

        logger.info(
            f"Ollama chat complete: time={inference_time:.2f}ms, "
            f"response_length={len(assistant_message)}"
        )

        return {
            "assistant_message": assistant_message,
            "model": model,
            "inference_time_ms": inference_time,
            "conversation_history": messages + [
                {"role": "assistant", "content": assistant_message}
            ],
        }

    except Exception as e:
        logger.exception(f"Ollama chat failed: {e}")
        raise


@celery_app.task(
    name="examples.ollama_llm.tasks.code_generation",
    bind=True,
    queue="llm-inference",
    time_limit=300,
)
def code_generation(
    self,
    state: dict,
    workflow_id: str,
    instruction: str,
    language: str = "python",
    **kwargs
):
    """
    Generate code using CodeLlama or other code-specialized models.

    Args:
        state: Workflow state
        workflow_id: Workflow UUID
        instruction: What code to generate
        language: Programming language
        **kwargs: Additional parameters

    Returns:
        Dict with generated code

    Example:
        result = code_generation.apply_async(
            kwargs={
                "state": {...},
                "workflow_id": "123",
                "instruction": "Write a function to calculate Fibonacci numbers",
                "language": "python",
            },
            queue="llm-inference"
        )
    """
    import ollama

    model = kwargs.get("model", "codellama")

    prompt = f"""Write {language} code for the following task:

{instruction}

Only output the code, no explanations.
"""

    logger.info(
        f"Code generation: workflow={workflow_id}, "
        f"model={model}, language={language}"
    )

    try:
        start_time = time.perf_counter()

        response = ollama.generate(
            model=model,
            prompt=prompt,
            options={
                "num_predict": kwargs.get("max_tokens", 500),
                "temperature": kwargs.get("temperature", 0.2),  # Lower temp for code
            },
        )

        inference_time = (time.perf_counter() - start_time) * 1000

        code = response["response"].strip()

        # Extract code from markdown blocks if present
        if "```" in code:
            lines = code.split("\n")
            code_lines = []
            in_code_block = False
            for line in lines:
                if line.startswith("```"):
                    in_code_block = not in_code_block
                    continue
                if in_code_block:
                    code_lines.append(line)
            code = "\n".join(code_lines).strip()

        logger.info(
            f"Code generation complete: time={inference_time:.2f}ms, "
            f"code_length={len(code)}"
        )

        return {
            "generated_code": code,
            "language": language,
            "model": model,
            "inference_time_ms": inference_time,
        }

    except Exception as e:
        logger.exception(f"Code generation failed: {e}")
        raise


@celery_app.task(
    name="examples.ollama_llm.tasks.embeddings",
    bind=True,
    queue="llm-inference",
    time_limit=60,
)
def embeddings(
    self,
    state: dict,
    workflow_id: str,
    text: str,
    model: str = "llama2",
):
    """
    Generate embeddings for semantic search/similarity.

    Args:
        state: Workflow state
        workflow_id: Workflow UUID
        text: Text to embed
        model: Ollama model name

    Returns:
        Dict with embedding vector
    """
    import ollama

    logger.info(f"Embedding generation: workflow={workflow_id}, text_length={len(text)}")

    try:
        start_time = time.perf_counter()

        response = ollama.embeddings(
            model=model,
            prompt=text,
        )

        inference_time = (time.perf_counter() - start_time) * 1000

        embedding = response["embedding"]

        logger.info(
            f"Embedding complete: time={inference_time:.2f}ms, "
            f"dimensions={len(embedding)}"
        )

        return {
            "embedding": embedding,
            "dimensions": len(embedding),
            "model": model,
            "inference_time_ms": inference_time,
        }

    except Exception as e:
        logger.exception(f"Embedding generation failed: {e}")
        raise
