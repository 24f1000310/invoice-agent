
import os
from dotenv import load_dotenv

load_dotenv()

APP_NAME = "Invoice Action Agent"
APP_VERSION = "1.0.0"

# Exact A2A base URL will be configured after deployment.
BASE_URL = os.getenv(
    "BASE_URL",
    "http://localhost:8000/a2a"
)

# The assignment grader will provide its own Bearer token.
# Configure the expected token through an environment variable.
API_TOKEN = os.getenv("API_TOKEN", "")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    "tasks.db"
)
AI_MODEL = os.getenv(
    "AI_MODEL",
    "gpt-4.1-mini"
)