import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")
BRAINTRUST_API_KEY = os.environ.get("BRAINTRUST_API_KEY")
MAX_ATTEMPTS = 3
