import os
from pathlib import Path

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIStatusError,
    OpenAI,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class ModelUnavailableError(Exception):
    pass


def ask_model(messages, *, json_mode=False):
    api_key = os.getenv("GROQ_API_KEY")
    models = [
        name.strip()
        for name in os.getenv("MODELS", "").split(",")
        if name.strip()
    ]

    if not api_key or not models:
        raise ModelUnavailableError("Model service is not configured.")

    client = OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=api_key,
        timeout=30.0,
        max_retries=0,
    )

    try:
        for model in models:
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.2,
                    max_tokens=3500 if json_mode else 1800,
                    **({"response_format": {"type": "json_object"}} if json_mode else {}),
                )
            except APIConnectionError:
                # Includes SDK timeout errors.
                continue
            except APIStatusError as error:
                if (
                    error.status_code in {404, 408, 429}
                    or error.status_code >= 500
                ):
                    continue

                raise ModelUnavailableError(
                    "Model request was rejected. "
                    "Check the server's provider configuration."
                ) from None

            if not response.choices:
                continue

            text = response.choices[0].message.content

            if response.choices[0].finish_reason == "length" or not text or not text.strip():
                continue

            if response.usage:
                print(
                    f"Model: {model} | "
                    f"Input tokens: {response.usage.prompt_tokens} | "
                    f"Output tokens: {response.usage.completion_tokens}"
                )

            return {
                "message": text,
                "model": model,
            }
    finally:
        client.close()

    raise ModelUnavailableError(
        "No configured model succeeded. Please try again later."
    )

class StructuredOutputError(Exception):
    """Provider answered, but no model produced a validated breakdown."""


def ask_model_tools(messages, tools):
    """One tool-capable completion, same fallback chain as ask_model.

    Returns {message, model, tool_calls:[{id,name,arguments}], finish_reason}.
    Mid-conversation failure raises: replaying another model's tool_call ids is
    not safe, so the caller retries the WHOLE turn instead.
    """
    api_key = os.getenv("GROQ_API_KEY")
    models = [
        name.strip()
        for name in os.getenv("MODELS", "").split(",")
        if name.strip()
    ]
    if not api_key or not models:
        raise ModelUnavailableError("Model service is not configured.")

    client = OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=api_key,
        timeout=30.0,
        max_retries=0,
    )
    try:
        for model in models:
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=tools,
                    temperature=0.2,
                    max_tokens=1500,
                )
            except APIConnectionError:
                continue
            except APIStatusError as error:
                if (
                    error.status_code in {404, 408, 429}
                    or error.status_code >= 500
                ):
                    continue
                raise ModelUnavailableError(
                    "Model request was rejected. "
                    "Check the server's provider configuration."
                ) from None

            if not response.choices:
                continue
            choice = response.choices[0]
            if choice.finish_reason == "length":
                continue
            calls = []
            for call in (choice.message.tool_calls or []):
                calls.append({"id": call.id, "name": call.function.name,
                              "arguments": call.function.arguments})
            if response.usage:
                print(
                    f"Model: {model} | Input tokens: {response.usage.prompt_tokens} | "
                    f"Output tokens: {response.usage.completion_tokens} | "
                    f"tool_calls: {len(calls)}"
                )
            return {
                "message": choice.message.content or "",
                "model": model,
                "tool_calls": calls,
                "finish_reason": choice.finish_reason or "stop",
            }
    finally:
        client.close()

    raise ModelUnavailableError(
        "No configured model succeeded. Please try again later."
    )


def ask_structured(messages, response_model):
    """Instructor validates/reasks (2 attempts/model), then the second model.

    At most two configured models are used for this bounded operation. All calls
    use this shared provider module; Instructor wraps the same OpenAI SDK.
    """
    import instructor
    from instructor.core.exceptions import InstructorRetryException
    from pydantic import ValidationError

    key = os.getenv("GROQ_API_KEY")
    models = [m.strip() for m in os.getenv("MODELS", "").split(",") if m.strip()][:2]
    if not key or not models:
        raise ModelUnavailableError("Model service is not configured.")
    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=key,
                    timeout=20.0, max_retries=0)
    typed = instructor.from_openai(client, mode=instructor.Mode.JSON)
    saw_invalid = False

    def log_usage(response):
        if getattr(response, "usage", None):
            print(f"Model: {response.model} | Input tokens: {response.usage.prompt_tokens} | Output tokens: {response.usage.completion_tokens}")
    typed.on("completion:response", log_usage)
    try:
        for model in models:
            try:
                result, completion = typed.chat.completions.create_with_completion(
                    model=model, messages=messages, response_model=response_model,
                    max_retries=1, temperature=0, max_tokens=3500,
                )
                if not completion.choices or completion.choices[0].finish_reason == "length":
                    saw_invalid = True
                    continue
                return {"parsed":result, "model":model}
            except InstructorRetryException as error:
                cause = error.__cause__
                if isinstance(cause, APIConnectionError):
                    continue
                if isinstance(cause, APIStatusError):
                    if cause.status_code in {404,408,429} or cause.status_code >= 500:
                        continue
                    raise ModelUnavailableError("Model request was rejected. Check the server's provider configuration.") from None
                saw_invalid = True
                continue
            except (ValidationError, ValueError, IndexError):
                saw_invalid = True
                continue
            except APIConnectionError:
                continue
            except APIStatusError as error:
                if error.status_code in {404,408,429} or error.status_code >= 500:
                    continue
                raise ModelUnavailableError("Model request was rejected. Check the server's provider configuration.") from None
    finally:
        client.close()
    if saw_invalid:
        raise StructuredOutputError("The models did not produce a valid breakdown after bounded retries. No cards were created. Clarify the brief or try a smaller first release.")
    raise ModelUnavailableError("No configured model succeeded. Please try again later.")
