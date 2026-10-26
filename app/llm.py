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