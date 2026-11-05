import os
from pathlib import Path

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

api_key = os.getenv("GROQ_API_KEY")
models = [
    model.strip()
    for model in os.getenv("MODELS", "").split(",")
    if model.strip()
]

if not api_key or api_key == "your_actual_groq_key":
    raise SystemExit("Set GROQ_API_KEY in your .env file.")

if not models:
    raise SystemExit("Set MODELS in your .env file.")

client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=api_key,
    timeout=30.0,
    max_retries=0,
)

messages = [
    {
        "role": "system",
        "content": "You are a concise programming tutor.",
    },
    {
        "role": "user",
        "content": "Explain what an API is in three short sentences.",
    },
]

response = None

for model in models:
    print(f"Calling {model}…")

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=300,
        )
    except (APITimeoutError, APIConnectionError):
        print("Connection failed or timed out. Trying the next model.")
        continue
    except APIStatusError as error:
        can_fallback = (
            error.status_code in {404, 408, 429}
            or error.status_code >= 500
        )

        if not can_fallback:
            raise SystemExit(
                f"Request rejected with HTTP {error.status_code}. "
                "Check your credentials, permissions, and request."
            ) from None

        print(
            f"Model request failed with HTTP {error.status_code}. "
            "Trying the next model."
        )
        continue

    print(f"\nAnswered by: {model}")
    print(response.choices[0].message.content)

    if response.usage:
        print("\nToken usage:")
        print(response.usage)

    break

# Include the first answer in the conversation history.
first_answer = response.choices[0].message.content

if not first_answer:
    raise SystemExit("The model returned no text to continue from.")

messages.append({
    "role": "assistant",
    "content": first_answer,
})

messages.append({
    "role": "user",
    "content": "Give me one example using my FastAPI card board.",
})

print("\nSending a follow-up with conversation history…")

follow_up = client.chat.completions.create(
    model=model,
    messages=messages,
    max_tokens=500,
)

print("\nFollow-up response:")
print(follow_up.choices[0].message.content)