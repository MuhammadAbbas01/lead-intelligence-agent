import os
import config
from langchain_community.tools.tavily_search import TavilySearchResults

# This creates the real search engine tool that your agent.py is looking for
tavily_tool = TavilySearchResults(
    max_results=3,
    tavily_api_key = config.TAVILY_API_KEY)