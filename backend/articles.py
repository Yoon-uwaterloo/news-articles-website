from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain.tools import tool
from firecrawl import Firecrawl
from langgraph.graph.state import TASKS
from api_key import firecrawl_api
from pathlib import Path
from dotenv import load_dotenv


load_dotenv()
firecrawl = Firecrawl(api_key=firecrawl_api)

@tool
def scraping_tech():
    """Search for recent, credible technology news articles (2025-2026) for every industries"""
    results = firecrawl.search(query="latest technology news 2026 breakthroughs", limit=2, sources=["news"])
    tasks = []
    for i in results["data"]["news"]:
        doc = firecrawl.scrape(i["rul"], formats=["html"])
        tasks.append(doc)
    return tasks

def tech_extractor():
    model = ChatOpenAI(model="gpt-4.1")
    agent = create_agent(model, tools=scraping_tech)
    result = agent.invoke({"messages": """
You are a tech-news analyst.

Use the available scraping tool to find recent technology news about new tech in 2026.
Create a concise HTML report.

Requirements:
- Output ONLY valid HTML.
- The entire response must be wrapped in exactly one:
<div class="prose">...</div>
- Do not include Markdown, code fences, explanations, or comments.
- Include 2-4 news items if available.
- For each item, include:
- <h2> headline
- <p> 2-4 sentence summary
- <p><strong>Why it matters:</strong> ...</p>
- <a href="SOURCE_URL">Read source</a> when a source URL is available
- Do not invent facts, dates, companies, quotes, or URLs.
- If the tool returns incomplete or unusable content, write:
<p>No reliable recent tech news could be extracted.</p>
- Keep the tone clear, neutral, and factual.
- Avoid duplicate stories.
- Prefer concrete technologies, products, research breakthroughs, standards, chips, AI systems, robotics, energy tech, or consumer devices.

Return only the HTML.
"""})
    html = result["structured_response"]

    html = html.strip()
    output_dir = Path("../articles/tech")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "report.html"
    output_file.write_text(html, encoding="utf-8")

@tool
def scraping_politics():
    """Search for recent, credible political news articles (2025-2026) across major regions and policy areas."""
    results = firecrawl.search(
        query="latest politics news 2026 elections policy government international relations",
        limit=2,
        sources=["news"]
    )

    tasks = []
    for i in results["data"]["news"]:
        doc = firecrawl.scrape(i["url"], formats=["html"])
        tasks.append(doc)

    return tasks


def politics_extractor():
    model = ChatOpenAI(model="gpt-4.1")
    agent = create_agent(model, tools=[scraping_politics])

    result = agent.invoke({"messages": """
You are a political-news analyst.

Use the available scraping tool to find recent, credible political news from 2026.
Create a concise HTML report.

Requirements:
- Output ONLY valid HTML.
- The entire response must be wrapped in exactly one:
  <div class="prose">...</div>
- Do not include Markdown, code fences, explanations, or comments.
- Include 2-4 news items if available.
- For each item, include:
  - <h2> headline
  - <p> 2-4 sentence neutral summary
  - <p><strong>Why it matters:</strong> ...</p>
  - <a href="SOURCE_URL">Read source</a> when a source URL is available
- Do not invent facts, dates, people, quotes, results, policies, or URLs.
- Avoid partisan language or unsupported claims.
- Clearly distinguish confirmed facts from claims or proposals.
- Avoid duplicate stories.
- Prefer elections, legislation, court rulings, government policy, diplomacy, conflicts, public institutions, or major political developments.
- If the tool returns incomplete or unusable content, write:
  <p>No reliable recent political news could be extracted.</p>

Return only the HTML.
"""})

    html = result["structured_response"].strip()

    output_dir = Path("../articles/politics")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "report.html"
    output_file.write_text(html, encoding="utf-8")

@tool
def scraping_economics():
    """Search for recent, credible economic news articles (2025-2026) covering markets, inflation, jobs, trade, growth, and policy."""
    results = firecrawl.search(
        query="latest economic news 2026 inflation jobs markets trade GDP central banks",
        limit=2,
        sources=["news"]
    )

    tasks = []
    for i in results["data"]["news"]:
        doc = firecrawl.scrape(i["url"], formats=["html"])
        tasks.append(doc)

    return tasks


def economics_extractor():
    model = ChatOpenAI(model="gpt-4.1")
    agent = create_agent(model, tools=[scraping_economics])

    result = agent.invoke({"messages": """
You are an economics-news analyst.

Use the available scraping tool to find recent, credible economic news from 2026.
Create a concise HTML report.

Requirements:
- Output ONLY valid HTML.
- The entire response must be wrapped in exactly one:
  <div class="prose">...</div>
- Do not include Markdown, code fences, explanations, or comments.
- Include 2-4 news items if available.
- For each item, include:
  - <h2> headline
  - <p> 2-4 sentence summary
  - <p><strong>Why it matters:</strong> ...</p>
  - <a href="SOURCE_URL">Read source</a> when a source URL is available
- Do not invent facts, dates, numbers, forecasts, quotes, companies, agencies, or URLs.
- Mention economic data only if it appears in the source.
- Clearly distinguish reported data from predictions or analyst opinions.
- Avoid duplicate stories.
- Prefer inflation, interest rates, jobs, GDP, markets, trade, business investment, central banks, fiscal policy, supply chains, or consumer spending.
- If the tool returns incomplete or unusable content, write:
  <p>No reliable recent economic news could be extracted.</p>

Return only the HTML.
"""})

    html = result["structured_response"].strip()

    output_dir = Path("../articles/economics")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "report.html"
    output_file.write_text(html, encoding="utf-8")