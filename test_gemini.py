
import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai

# Load the .env file from this project's folder
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)
from dotenv import dotenv_values

print("ENV file exists:", env_path.exists())
print("Model entries in ENV file:")

for line_number, line in enumerate(
    env_path.read_text(encoding="utf-8-sig").splitlines(), 1
):
    if line.strip().startswith("GEMINI_MODEL"):
        print(f"Line {line_number}: {line}")

print(
    "Model parsed directly:",
    repr(dotenv_values(env_path).get("GEMINI_MODEL"))
)

api_key = os.getenv("GEMINI_API_KEY", "").strip()
model = os.getenv("GEMINI_MODEL", "").strip()

print("Environment file:", env_path)
print("Model being tested:", model)

if not api_key:
    raise ValueError("GEMINI_API_KEY is missing.")

if not model:
    raise ValueError("GEMINI_MODEL is missing.")

client = genai.Client(api_key=api_key)

try:
    response = client.models.generate_content(
        model=model,
        contents="Give me three beginner Python exercises.",
    )

    print("\nSUCCESS!")
    print(response.text)

except Exception as error:
    print("\nERROR:")
    print(error)