from pymongo import MongoClient
from daytona import Daytona, DaytonaConfig, FileDownloadRequest
from langchain_daytona import DaytonaSandbox
from deepagents import create_deep_agent
from api_key import fred_api
from api_key import daytona_api
from datetime import datetime
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain.tools import tool
from pydantic import BaseModel
import requests
import asyncio
import json
import time
from pathlib import Path


class FredSeriesMetadata(BaseModel):
    id: str
    title: str
    frequency: str
    units: str
    seasonal_adjustment: str
    notes: str | None

class Reason(BaseModel):
    metadata: FredSeriesMetadata
    reason: str

class ListFredSeriesMetadata(BaseModel):
    list_metadata: list[Reason]


# Global
load_dotenv()
CONNECTION_STRING = "mongodb://127.0.0.1:27017/?directConnection=true"
client = MongoClient(CONNECTION_STRING)
config = DaytonaConfig(api_key=daytona_api)
daytona = Daytona(config)
cpi_id = 9
ppi_id = 31
interest_rate_id = 22
unemployment_rate_id = 32447
gdp_id = 106
shared_gdp_id = 33020

base_url = "https://api.stlouisfed.org/fred/"
series_endpoint = "category/series"
children_endpoint = "category/children"
observation_endpoint = 'series/observations'
past_date = datetime.today().replace(year=datetime.today().year - 5, month=1, day=1)
base_params = {
    "api_key": fred_api,
    "file_type": "json"}
obs_params = {
    "api_key": fred_api,
    "file_type": "json",
    "observation_start": past_date.strftime('%Y-%m-%d')}

async def cpi():
    db = client["cpi"]
    cpi = requests.get(base_url + series_endpoint, params={**base_params, "category_id": cpi_id})
    for i in cpi.json()["seriess"]:
        doc = {
            "id": i["id"],
            "title": i["title"],
            "frequency": i["frequency"],
            "units": i["units"],
            "seasonal_adjustment": i["seasonal_adjustment"]}
        notes = i.get("notes")
        if notes is not None:
            doc["notes"] = notes
        db["cpi"].insert_one(doc)

@tool
def search_indicators_cpi():
    """Pull CPI indicators"""
    db = client["cpi"]
    docs = list(db["cpi"].find({}, {"_id": 0}))
    return docs

async def selector_cpi():
    await cpi()
    model = ChatOpenAI(model="gpt-5-mini-2025-08-07")
    agent = create_agent(model, response_format=ListFredSeriesMetadata, tools=[search_indicators_cpi])
    db = client["cpi"]
    result = agent.invoke({"messages": [{"role": "user", "content": (
                        "Select the best 3 indicators to represent the CPI. "
                        "and only use those indicators. "
                        "Explain why each indicator is chosen in the reason object.")}]})
    docs = [item.model_dump() for item in result["structured_response"].list_metadata]
    db["selected_cpi"].insert_many(docs)

async def observation_cpi():
    await selector_cpi()
    db = client["cpi"]
    for obj in db["selected_cpi"].find():
        response = requests.get(base_url + observation_endpoint, params={**obs_params, "series_id": obj["metadata"]["id"]})
        json_data = response.json()
        observations = json_data["observations"]
        data = [{"date": i["date"], "value": i["value"]} for i in observations]
        db["selected_cpi"].update_one({"_id": obj["_id"]},{"$set": {"data": data}})

async def ppi():
    db = client["ppi"]
    ppi = requests.get(base_url + series_endpoint, params={**base_params, "category_id": ppi_id})
    for i in ppi.json()["seriess"]:
        doc = {
            "id": i["id"],
            "title": i["title"],
            "frequency": i["frequency"],
            "units": i["units"],
            "seasonal_adjustment": i["seasonal_adjustment"]}
        notes = i.get("notes")
        if notes is not None:
            doc["notes"] = notes
        db["ppi"].insert_one(doc)

async def observation_ppi():
    db = client["ppi"]
    for obj in db["ppi"].find({}, {"_id": 0}):
        time.sleep(0.25)
        response = requests.get(base_url + observation_endpoint, params={**obs_params, "series_id": obj["id"]})
        observations = response.json()["observations"]
        data = [{"date": i["date"], "value": i["value"]} for i in observations]
        db["selected_ppi"].insert_one({"metadata": obj, "data": data})

async def interest_rate():
    db = client["interest_rate"]
    parent = requests.get(base_url + children_endpoint, params={**base_params, "category_id": interest_rate_id})
    category = parent.json()["categories"]
    for i in category:
        id = i["id"]
        name = i["name"].replace(" ", "_")
        children = requests.get(base_url + series_endpoint, params={**base_params, "category_id": id})
        for i in children.json()["seriess"]:
            doc = {
                "id": i["id"],
                "title": i["title"],
                "frequency": i["frequency"],
                "units": i["units"],
                "seasonal_adjustment": i["seasonal_adjustment"]}
            notes = i.get("notes")
            if notes is not None:
                doc["notes"] = notes
            db[name].insert_one(doc)

@tool
def search_indicators_interest_rate(sector_name: str):
    """Pull interest rate indicators for a given sector/category name."""
    db = client["interest_rate"]
    docs = list(db[sector_name].find({}, {"_id": 0}))
    return docs

async def selector_interest_rate():
    model = ChatOpenAI(model="gpt-5-mini-2025-08-07")
    agent = create_agent(model, response_format=ListFredSeriesMetadata, tools=[search_indicators_interest_rate])
    source_db = client["interest_rate"]
    target_db = client["selected_interest_rate"]    
    tasks = []
    async with asyncio.TaskGroup() as tg:
        for rate in source_db.list_collection_names():
            task = tg.create_task(agent.ainvoke({"messages": [{"role": "user", "content": (
                        f"Select the best 2 indicators to represent the '{rate}' rate. "
                        f"You MUST call search_indicators with rate_name='{rate}' "
                        f"and only use those indicators. "
                        f"If '{rate}' is not an important rate to analysis economy pick 0 or 1 indicator"
                        f"Explain why each indicator is chosen in the reason object.")}]}))
            tasks.append((rate, task))
    
    for rate, task in tasks:
        result = task.result()
        structured = result["structured_response"]
        docs = [item.model_dump() for item in structured.list_metadata]
        if docs:
            target_db[rate].insert_many(docs)

async def observation_interest_rate():

    db = client["selected_interest_rate"]

    for collection in db.list_collection_names():
        for obj in db[collection].find({}):
            response = requests.get(base_url + observation_endpoint, params={**obs_params, "series_id": obj["metadata"]["id"]})
            json_data = response.json()
            if response.status_code != 200 or "observations" not in json_data:
                print("Bad response for:", obj["id"])
                print("Status:", response.status_code)
                print(json_data)
                continue
            data = [{"date": i["date"], "value": i["value"]} for i in json_data["observations"]]
            db[collection].update_one({"_id": obj["_id"]}, {"$set": {"data": data}})

async def unemployment_rate():
    db = client["unemployment_rate"]
    series = requests.get(base_url + series_endpoint, params={**base_params, "category_id": unemployment_rate_id})

    for i in series.json()["seriess"]:
        if i["id"].startswith("UNRATE"):
            db["unemployment_rate"].insert_one({
                "id": i["id"],
                "title": i["title"],
                "frequency": i["frequency"],
                "units": i["units"],
                "seasonal_adjustment": i["seasonal_adjustment"],
                "notes": i["notes"]})

async def observation_unemployment_rate():
    await unemployment_rate()
    db = client["unemployment_rate"]
    for obj in db["unemployment_rate"].find({}, {"_id": 0}):
        response = requests.get(base_url + observation_endpoint, params={**obs_params, "series_id": obj["id"]})
        observations = response.json()["observations"]
        data = [{"date": i["date"], "value": i["value"]} for i in observations]
        db["selected_unemployment_rate"].insert_one({"metadata": obj, "data": data})

async def gdp():
    db = client["gdp"]
    series = requests.get(base_url + series_endpoint, params={**base_params, "category_id": gdp_id})
    for i in series.json()["seriess"]:
        doc = {
            "id": i["id"],
            "title": i["title"],
            "frequency": i["frequency"],
            "units": i["units"],
            "seasonal_adjustment": i["seasonal_adjustment"]}
        notes = i.get("notes")
        if notes is not None:
            doc["notes"] = notes
        db["gdp"].insert_one(doc)

async def observation_gdp():
    # await gdp()
    db = client["gdp"]
    for obj in db["gdp"].find({}, {"_id": 0}):
        time.sleep(0.25)
        response = requests.get(base_url + observation_endpoint, params={**obs_params, "series_id": obj["id"]})
        json_data = response.json()
        if response.status_code != 200 or "observations" not in json_data:
            print("Bad response for:", obj["id"])
            print("Status:", response.status_code)
            print(json_data)
            continue
        data = [{"date": i["date"], "value": i["value"]} for i in json_data["observations"]]
        db["selected_gdp"].update_one({"metadata.id": obj["id"]}, {"$set": {"metadata": obj, "data": data}}, upsert=True)

async def shared_gdp():
    db = client["gdp"]
    series = requests.get(base_url + series_endpoint, params={**base_params, "category_id": shared_gdp_id})
    for i in series.json()["seriess"]:
        doc = {
            "id": i["id"],
            "title": i["title"],
            "frequency": i["frequency"],
            "units": i["units"],
            "seasonal_adjustment": i["seasonal_adjustment"]}
        notes = i.get("notes")
        if notes is not None:
            doc["notes"] = notes
        db["shared_gdp"].insert_one(doc)

async def observation_shared_gdp():
    # await shared_gdp()
    db = client["gdp"]
    for obj in db["shared_gdp"].find({}, {"_id": 0}):
        time.sleep(0.25)
        response = requests.get(base_url + observation_endpoint, params={**obs_params, "series_id": obj["id"]})
        json_data = response.json()
        if response.status_code != 200 or "observations" not in json_data:
            print("Bad response for:", obj["id"])
            print("Status:", response.status_code)
            print(json_data)
            continue
        data = [{"date": i["date"], "value": i["value"]} for i in json_data["observations"]]
        db["selected_shared_gdp"].update_one({"metadata.id": obj["id"]}, {"$set": {"metadata": obj, "data": data}}, upsert=True)

async def sandbox_cpi():
    sandbox = daytona.create()
    backend = DaytonaSandbox(sandbox=sandbox)
    agent = create_deep_agent(model="gpt-5.4",backend=backend)
    
    db = client["cpi"]
    data = list(db["selected_cpi"].find({}, {"_id": 0}))
    backend.upload_files([("/home/daytona/data/data.json", json.dumps(data).encode("utf-8"))])

    input_message = {
        "role": "user",
        "content": ("""Analyze the dataset located at: '/home/daytona/data/data.json' and produce 
                    a professional economic research report in the style of the Federal Reserve Bank of New York's 
                    Liberty Street Economics blog (specifically modeled after "Monitoring Real Activity in Real Time: 
                    The Weekly Economic Index").

                    ## Analysis Requirements

                    Conduct a thorough economic analysis of the dataset including:
                    1. Identify the key economic indicators present in the data and their time coverage
                    2. Compute summary statistics (mean, median, std deviation, min/max, recent vs. historical values)
                    3. Calculate period-over-period changes (week-over-week, month-over-month, year-over-year as applicable)
                    4. Identify significant turning points, recessions, recoveries, or anomalies
                    5. Compute correlations between indicators if multiple series exist
                    6. If the data contains a composite index, decompose it into contributing components
                    7. Compare current readings to historical benchmarks (e.g., pre-pandemic, prior recessions)

                    ## File Output Requirements

                    - Create directory: /home/daytona/output/
                    - Create chart files: /home/daytona/output/chart_1.png, chart_2.png, chart_3.png, etc.
                    Charts should include (as supported by the data):
                        * A headline time-series chart of the main index/indicator
                        * A chart highlighting recession periods (shaded regions) vs. the indicator
                        * Component contribution chart (stacked bar or area chart)
                        * Recent-period zoomed-in view (last 12-24 months)
                        * Cross-indicator comparison or correlation visualization
                        * Distribution or histogram of changes/returns
                    - Save the final report as a SINGLE HTML file: /home/daytona/output/report.html

                    ## Report Content & Structure

                    The report should read like a Liberty Street Economics post — analytical, data-driven, and 
                    written for an informed-but-general audience. Include:

                    1. **Title** — informative and specific (e.g., "Tracking [Indicator]: What the Latest Data Reveal")
                    2. **Lead paragraph** — state the motivation: why this measurement matters, what question it answers
                    3. **Background section** — explain the indicator(s), methodology, and economic context
                    4. **Findings section** — walk through each chart with interpretation; reference what the data show
                    5. **Historical comparison** — situate current readings against past episodes
                    6. **Caveats / limitations** — note data constraints, revision risk, or interpretive cautions
                    7. **Conclusion** — synthesize the takeaway and policy or forecasting implications

                    Write in clear, measured prose. Use specific numbers from the data. Reference each chart inline 
                    in the narrative (e.g., "As shown in the chart below..."). Avoid hype; mirror the sober analytical 
                    tone of Federal Reserve research blogs.

                    ## HTML Format Requirements (strict)

                    - NO CSS, NO JavaScript — pure HTML only
                    - The count of <img> tags in report.html MUST equal the count of chart_*.png files produced
                    - Insert each PNG using a relative path, formatted as: <img src="../../../indicators/cpi/chart_N.png" alt="...">
                    - The entire report body MUST be wrapped exactly as follows:

                    <div class="prose">
                        (all report content goes here — headings, paragraphs, images, etc.)
                    </div>

                    Use semantic HTML inside the wrapper: <h1>, <h2>, <h3> for hierarchy, <p> for paragraphs, 
                    <ul>/<ol> for lists, <table> for tabular data, and <img> for charts. Place each <img> tag 
                    immediately after the paragraph that introduces or discusses it.

                    ## Final Verification

                    Before finishing, verify:
                    - All chart_*.png files exist in /home/daytona/output/ 
                    - report.html exists, opens with <div class="prose"> and closes with </div>
                    - The number of <img> tags equals the number of chart_*.png files
                    - Every chart referenced in the HTML actually exists on disk
                    - The narrative references specific values from the data, not generic statements
                    """)}
    
    for step in agent.stream({"messages": [input_message]},):
        for _, update in step.items():
            if update and (messages := update.get("messages")) and isinstance(messages, list):
                for message in messages:
                    message.pretty_print()

    files = sandbox.fs.list_files("/home/daytona/output")
    files_to_download = [
        FileDownloadRequest(source=f"/home/daytona/output/{f.name}", destination=f"./indicators/cpi/{f.name}")
        for f in files if f.name.endswith(".html") or f.name.endswith(".png")]
    results = sandbox.fs.download_files(files_to_download)
    for result in results:
        if result.error:
            print(f"Error downloading {result.source}: {result.error}")
        else:
            print(f"Downloaded {result.source} to {result.result}")

    sandbox.delete()

async def sandbox_ppi():
    sandbox = daytona.create()
    backend = DaytonaSandbox(sandbox=sandbox)
    agent = create_deep_agent(model="gpt-5.4",backend=backend)
    
    db = client["ppi"]
    data = list(db["selected_ppi"].find({}, {"_id": 0}))
    backend.upload_files([("/home/daytona/data/data.json", json.dumps(data).encode("utf-8"))])

    input_message = {
        "role": "user",
        "content": ("""Analyze the dataset located at: '/home/daytona/data/data.json' and produce 
                    a professional economic research report in the style of the Federal Reserve Bank of New York's 
                    Liberty Street Economics blog (specifically modeled after "Monitoring Real Activity in Real Time: 
                    The Weekly Economic Index").

                    ## Analysis Requirements

                    Conduct a thorough economic analysis of the dataset including:
                    1. Identify the key economic indicators present in the data and their time coverage
                    2. Compute summary statistics (mean, median, std deviation, min/max, recent vs. historical values)
                    3. Calculate period-over-period changes (week-over-week, month-over-month, year-over-year as applicable)
                    4. Identify significant turning points, recessions, recoveries, or anomalies
                    5. Compute correlations between indicators if multiple series exist
                    6. If the data contains a composite index, decompose it into contributing components
                    7. Compare current readings to historical benchmarks (e.g., pre-pandemic, prior recessions)

                    ## File Output Requirements

                    - Create directory: /home/daytona/output/
                    - Create chart files: /home/daytona/output/chart_1.png, chart_2.png, chart_3.png, etc.
                    Charts should include (as supported by the data):
                        * A headline time-series chart of the main index/indicator
                        * A chart highlighting recession periods (shaded regions) vs. the indicator
                        * Component contribution chart (stacked bar or area chart)
                        * Recent-period zoomed-in view (last 12-24 months)
                        * Cross-indicator comparison or correlation visualization
                        * Distribution or histogram of changes/returns
                    - Save the final report as a SINGLE HTML file: /home/daytona/output/report.html

                    ## Report Content & Structure

                    The report should read like a Liberty Street Economics post — analytical, data-driven, and 
                    written for an informed-but-general audience. Include:

                    1. **Title** — informative and specific (e.g., "Tracking [Indicator]: What the Latest Data Reveal")
                    2. **Lead paragraph** — state the motivation: why this measurement matters, what question it answers
                    3. **Background section** — explain the indicator(s), methodology, and economic context
                    4. **Findings section** — walk through each chart with interpretation; reference what the data show
                    5. **Historical comparison** — situate current readings against past episodes
                    6. **Caveats / limitations** — note data constraints, revision risk, or interpretive cautions
                    7. **Conclusion** — synthesize the takeaway and policy or forecasting implications

                    Write in clear, measured prose. Use specific numbers from the data. Reference each chart inline 
                    in the narrative (e.g., "As shown in the chart below..."). Avoid hype; mirror the sober analytical 
                    tone of Federal Reserve research blogs.

                    ## HTML Format Requirements (strict)

                    - NO CSS, NO JavaScript — pure HTML only
                    - The count of <img> tags in report.html MUST equal the count of chart_*.png files produced
                    - Insert each PNG using a relative path, formatted as: <img src="../../../indicators/ppi/chart_N.png" alt="...">
                    - The entire report body MUST be wrapped exactly as follows:

                    <div class="prose">
                        (all report content goes here — headings, paragraphs, images, etc.)
                    </div>

                    Use semantic HTML inside the wrapper: <h1>, <h2>, <h3> for hierarchy, <p> for paragraphs, 
                    <ul>/<ol> for lists, <table> for tabular data, and <img> for charts. Place each <img> tag 
                    immediately after the paragraph that introduces or discusses it.

                    ## Final Verification

                    Before finishing, verify:
                    - All chart_*.png files exist in /home/daytona/output/
                    - report.html exists, opens with <div class="prose"> and closes with </div>
                    - The number of <img> tags equals the number of chart_*.png files
                    - Every chart referenced in the HTML actually exists on disk
                    - The narrative references specific values from the data, not generic statements
                    """)}
    
    for step in agent.stream({"messages": [input_message]},):
        for _, update in step.items():
            if update and (messages := update.get("messages")) and isinstance(messages, list):
                for message in messages:
                    message.pretty_print()

    files = sandbox.fs.list_files("/home/daytona/output")
    files_to_download = [
        FileDownloadRequest(source=f"/home/daytona/output/{f.name}", destination=f"./indicators/ppi/{f.name}")
        for f in files if f.name.endswith(".html") or f.name.endswith(".png")]
    results = sandbox.fs.download_files(files_to_download)
    for result in results:
        if result.error:
            print(f"Error downloading {result.source}: {result.error}")
        else:
            print(f"Downloaded {result.source} to {result.result}")

    sandbox.delete()

async def sandbox_interest_rate():
    sandbox = daytona.create()
    backend = DaytonaSandbox(sandbox=sandbox)
    agent = create_deep_agent(model="gpt-5.4",backend=backend)
    
    db = client["selected_interest_rate"]
    data1 = list(db["FRB_Rates_-_discount,_fed_funds,_primary_credit"].find({}, {"_id": 0}))
    backend.upload_files([("/home/daytona/data/data.json1", json.dumps(data1).encode("utf-8"))])

    data2 = list(db["Monetary_Policy"].find({}, {"_id": 0}))
    backend.upload_files([("/home/daytona/data/data.json2", json.dumps(data2).encode("utf-8"))])

    data3 = list(db["Treasury_Bills"].find({}, {"_id": 0}))
    backend.upload_files([("/home/daytona/data/data.json3", json.dumps(data3).encode("utf-8"))])

    data4 = list(db["Treasury_Inflation-Indexed_Securities"].find({}, {"_id": 0}))
    backend.upload_files([("/home/daytona/data/data.json4", json.dumps(data4).encode("utf-8"))])


    input_message = {
        "role": "user",
        "content": ("""Analyze the dataset located at: '/home/daytona/data/data.json1', '/home/daytona/data/data.json2', '/home/daytona/data/data.json3'
                    '/home/daytona/data/data.json4' and produce  a professional economic research report in the style of the Federal Reserve Bank of New York's 
                    Liberty Street Economics blog (specifically modeled after "Monitoring Real Activity in Real Time: 
                    The Weekly Economic Index").

                    ## Analysis Requirements

                    Conduct a thorough economic analysis of the dataset including:
                    1. Identify the key economic indicators present in the data and their time coverage
                    2. Compute summary statistics (mean, median, std deviation, min/max, recent vs. historical values)
                    3. Calculate period-over-period changes (week-over-week, month-over-month, year-over-year as applicable)
                    4. Identify significant turning points, recessions, recoveries, or anomalies
                    5. Compute correlations between indicators if multiple series exist
                    6. If the data contains a composite index, decompose it into contributing components
                    7. Compare current readings to historical benchmarks (e.g., pre-pandemic, prior recessions)

                    ## File Output Requirements

                    - Create directory: /home/daytona/output/
                    - Create chart files: /home/daytona/output/chart_1.png, chart_2.png, chart_3.png, etc.
                    Charts should include (as supported by the data):
                        * A headline time-series chart of the main index/indicator
                        * A chart highlighting recession periods (shaded regions) vs. the indicator
                        * Component contribution chart (stacked bar or area chart)
                        * Recent-period zoomed-in view (last 12-24 months)
                        * Cross-indicator comparison or correlation visualization
                        * Distribution or histogram of changes/returns
                    - Save the final report as a SINGLE HTML file: /home/daytona/output/report.html

                    ## Report Content & Structure

                    The report should read like a Liberty Street Economics post — analytical, data-driven, and 
                    written for an informed-but-general audience. Include:

                    1. **Title** — informative and specific (e.g., "Tracking [Indicator]: What the Latest Data Reveal")
                    2. **Lead paragraph** — state the motivation: why this measurement matters, what question it answers
                    3. **Background section** — explain the indicator(s), methodology, and economic context
                    4. **Findings section** — walk through each chart with interpretation; reference what the data show
                    5. **Historical comparison** — situate current readings against past episodes
                    6. **Caveats / limitations** — note data constraints, revision risk, or interpretive cautions
                    7. **Conclusion** — synthesize the takeaway and policy or forecasting implications

                    Write in clear, measured prose. Use specific numbers from the data. Reference each chart inline 
                    in the narrative (e.g., "As shown in the chart below..."). Avoid hype; mirror the sober analytical 
                    tone of Federal Reserve research blogs.

                    ## HTML Format Requirements (strict)

                    - NO CSS, NO JavaScript — pure HTML only
                    - The count of <img> tags in report.html MUST equal the count of chart_*.png files produced
                    - Insert each PNG using a relative path, formatted as: <img src="../../../indicators/rate/chart_N.png" alt="...">
                    - The entire report body MUST be wrapped exactly as follows:

                    <div class="prose">
                        (all report content goes here — headings, paragraphs, images, etc.)
                    </div>

                    Use semantic HTML inside the wrapper: <h1>, <h2>, <h3> for hierarchy, <p> for paragraphs, 
                    <ul>/<ol> for lists, <table> for tabular data, and <img> for charts. Place each <img> tag 
                    immediately after the paragraph that introduces or discusses it.

                    ## Final Verification

                    Before finishing, verify:
                    - All chart_*.png files exist in /home/daytona/output/
                    - report.html exists, opens with <div class="prose"> and closes with </div>
                    - The number of <img> tags equals the number of chart_*.png files
                    - Every chart referenced in the HTML actually exists on disk
                    - The narrative references specific values from the data, not generic statements
                    """)}
    
    for step in agent.stream({"messages": [input_message]},):
        for _, update in step.items():
            if update and (messages := update.get("messages")) and isinstance(messages, list):
                for message in messages:
                    message.pretty_print()

    files = sandbox.fs.list_files("/home/daytona/output")
    files_to_download = [
        FileDownloadRequest(source=f"/home/daytona/output/{f.name}", destination=f"./indicators/rate/{f.name}")
        for f in files if f.name.endswith(".html") or f.name.endswith(".png")]
    results = sandbox.fs.download_files(files_to_download)
    for result in results:
        if result.error:
            print(f"Error downloading {result.source}: {result.error}")
        else:
            print(f"Downloaded {result.source} to {result.result}")

    sandbox.delete()

async def sandbox_unemployment_rate():
    sandbox = daytona.create()
    backend = DaytonaSandbox(sandbox=sandbox)
    agent = create_deep_agent(model="gpt-5.4",backend=backend)
    
    db = client["unemployment_rate"]
    data = list(db["selected_unemployment_rate"].find({}, {"_id": 0}))
    backend.upload_files([("/home/daytona/data/data.json", json.dumps(data).encode("utf-8"))])

    input_message = {
        "role": "user",
        "content": ("""Analyze the dataset located at: '/home/daytona/data/data.json' and produce 
                    a professional economic research report in the style of the Federal Reserve Bank of New York's 
                    Liberty Street Economics blog (specifically modeled after "Monitoring Real Activity in Real Time: 
                    The Weekly Economic Index").

                    ## Analysis Requirements

                    Conduct a thorough economic analysis of the dataset including:
                    1. Identify the key economic indicators present in the data and their time coverage
                    2. Compute summary statistics (mean, median, std deviation, min/max, recent vs. historical values)
                    3. Calculate period-over-period changes (week-over-week, month-over-month, year-over-year as applicable)
                    4. Identify significant turning points, recessions, recoveries, or anomalies
                    5. Compute correlations between indicators if multiple series exist
                    6. If the data contains a composite index, decompose it into contributing components
                    7. Compare current readings to historical benchmarks (e.g., pre-pandemic, prior recessions)

                    ## File Output Requirements

                    - Create directory: /home/daytona/output/
                    - Create chart files: /home/daytona/output/chart_1.png, chart_2.png, chart_3.png, etc.
                    Charts should include (as supported by the data):
                        * A headline time-series chart of the main index/indicator
                        * A chart highlighting recession periods (shaded regions) vs. the indicator
                        * Component contribution chart (stacked bar or area chart)
                        * Recent-period zoomed-in view (last 12-24 months)
                        * Cross-indicator comparison or correlation visualization
                        * Distribution or histogram of changes/returns
                    - Save the final report as a SINGLE HTML file: /home/daytona/output/report.html

                    ## Report Content & Structure

                    The report should read like a Liberty Street Economics post — analytical, data-driven, and 
                    written for an informed-but-general audience. Include:

                    1. **Title** — informative and specific (e.g., "Tracking [Indicator]: What the Latest Data Reveal")
                    2. **Lead paragraph** — state the motivation: why this measurement matters, what question it answers
                    3. **Background section** — explain the indicator(s), methodology, and economic context
                    4. **Findings section** — walk through each chart with interpretation; reference what the data show
                    5. **Historical comparison** — situate current readings against past episodes
                    6. **Caveats / limitations** — note data constraints, revision risk, or interpretive cautions
                    7. **Conclusion** — synthesize the takeaway and policy or forecasting implications

                    Write in clear, measured prose. Use specific numbers from the data. Reference each chart inline 
                    in the narrative (e.g., "As shown in the chart below..."). Avoid hype; mirror the sober analytical 
                    tone of Federal Reserve research blogs.

                    ## HTML Format Requirements (strict)

                    - NO CSS, NO JavaScript — pure HTML only
                    - The count of <img> tags in report.html MUST equal the count of chart_*.png files produced
                    - Insert each PNG using a relative path, formatted as: <img src="../../../indicators/unemployment_rate/chart_N.png" alt="...">
                    - The entire report body MUST be wrapped exactly as follows:

                    <div class="prose">
                        (all report content goes here — headings, paragraphs, images, etc.)
                    </div>

                    Use semantic HTML inside the wrapper: <h1>, <h2>, <h3> for hierarchy, <p> for paragraphs, 
                    <ul>/<ol> for lists, <table> for tabular data, and <img> for charts. Place each <img> tag 
                    immediately after the paragraph that introduces or discusses it.

                    ## Final Verification

                    Before finishing, verify:
                    - All chart_*.png files exist in /home/daytona/output/
                    - report.html exists, opens with <div class="prose"> and closes with </div>
                    - The number of <img> tags equals the number of chart_*.png files
                    - Every chart referenced in the HTML actually exists on disk
                    - The narrative references specific values from the data, not generic statements
                    """)}
    
    for step in agent.stream({"messages": [input_message]},):
        for _, update in step.items():
            if update and (messages := update.get("messages")) and isinstance(messages, list):
                for message in messages:
                    message.pretty_print()

    files = sandbox.fs.list_files("/home/daytona/output")
    files_to_download = [
        FileDownloadRequest(source=f"/home/daytona/output/{f.name}", destination=f"./indicators/unemployment_rate/{f.name}")
        for f in files if f.name.endswith(".html") or f.name.endswith(".png")]
    results = sandbox.fs.download_files(files_to_download)
    for result in results:
        if result.error:
            print(f"Error downloading {result.source}: {result.error}")
        else:
            print(f"Downloaded {result.source} to {result.result}")

    sandbox.delete()

async def sandbox_gdp():
    sandbox = daytona.create()
    backend = DaytonaSandbox(sandbox=sandbox)
    agent = create_deep_agent(model="gpt-5.4",backend=backend)
    
    db = client["gdp"]
    data1 = list(db["selected_gdp"].find({}, {"_id": 0}))
    backend.upload_files([("/home/daytona/data/data.json1", json.dumps(data1).encode("utf-8"))])

    data2 = list(db["selected_shared_gdp"].find({}, {"_id": 0}))
    backend.upload_files([("/home/daytona/data/data.json2", json.dumps(data2).encode("utf-8"))])

    input_message = {
        "role": "user",
        "content": ("""Analyze the dataset located at: '/home/daytona/data/data.json1' and '/home/daytona/data/data.json2' and produce 
                    a professional economic research report in the style of the Federal Reserve Bank of New York's 
                    Liberty Street Economics blog (specifically modeled after "Monitoring Real Activity in Real Time: 
                    The Weekly Economic Index").

                    ## Analysis Requirements

                    Conduct a thorough economic analysis of the dataset including:
                    1. Identify the key economic indicators present in the data and their time coverage
                    2. Compute summary statistics (mean, median, std deviation, min/max, recent vs. historical values)
                    3. Calculate period-over-period changes (week-over-week, month-over-month, year-over-year as applicable)
                    4. Identify significant turning points, recessions, recoveries, or anomalies
                    5. Compute correlations between indicators if multiple series exist
                    6. If the data contains a composite index, decompose it into contributing components
                    7. Compare current readings to historical benchmarks (e.g., pre-pandemic, prior recessions)

                    ## File Output Requirements

                    - Create directory: /home/daytona/output/
                    - Create chart files: /home/daytona/output/chart_1.png, chart_2.png, chart_3.png, etc.
                    Charts should include (as supported by the data):
                        * A headline time-series chart of the main index/indicator
                        * A chart highlighting recession periods (shaded regions) vs. the indicator
                        * Component contribution chart (stacked bar or area chart)
                        * Recent-period zoomed-in view (last 12-24 months)
                        * Cross-indicator comparison or correlation visualization
                        * Distribution or histogram of changes/returns
                    - Save the final report as a SINGLE HTML file: /home/daytona/output/report.html

                    ## Report Content & Structure

                    The report should read like a Liberty Street Economics post — analytical, data-driven, and 
                    written for an informed-but-general audience. Include:

                    1. **Title** — informative and specific (e.g., "Tracking [Indicator]: What the Latest Data Reveal")
                    2. **Lead paragraph** — state the motivation: why this measurement matters, what question it answers
                    3. **Background section** — explain the indicator(s), methodology, and economic context
                    4. **Findings section** — walk through each chart with interpretation; reference what the data show
                    5. **Historical comparison** — situate current readings against past episodes
                    6. **Caveats / limitations** — note data constraints, revision risk, or interpretive cautions
                    7. **Conclusion** — synthesize the takeaway and policy or forecasting implications

                    Write in clear, measured prose. Use specific numbers from the data. Reference each chart inline 
                    in the narrative (e.g., "As shown in the chart below..."). Avoid hype; mirror the sober analytical 
                    tone of Federal Reserve research blogs.

                    ## HTML Format Requirements (strict)

                    - NO CSS, NO JavaScript — pure HTML only
                    - The count of <img> tags in report.html MUST equal the count of chart_*.png files produced
                    - Insert each PNG using a relative path, formatted as: <img src="../../../indicators/gdp/chart_N.png" alt="...">
                    - The entire report body MUST be wrapped exactly as follows:

                    <div class="prose">
                        (all report content goes here — headings, paragraphs, images, etc.)
                    </div>

                    Use semantic HTML inside the wrapper: <h1>, <h2>, <h3> for hierarchy, <p> for paragraphs, 
                    <ul>/<ol> for lists, <table> for tabular data, and <img> for charts. Place each <img> tag 
                    immediately after the paragraph that introduces or discusses it.

                    ## Final Verification

                    Before finishing, verify:
                    - All chart_*.png files exist in /home/daytona/output/
                    - report.html exists, opens with <div class="prose"> and closes with </div>
                    - The number of <img> tags equals the number of chart_*.png files
                    - Every chart referenced in the HTML actually exists on disk
                    - The narrative references specific values from the data, not generic statements
                    """)}
    
    for step in agent.stream({"messages": [input_message]},):
        for _, update in step.items():
            if update and (messages := update.get("messages")) and isinstance(messages, list):
                for message in messages:
                    message.pretty_print()

    files = sandbox.fs.list_files("/home/daytona/output")
    files_to_download = [
        FileDownloadRequest(source=f"/home/daytona/output/{f.name}", destination=f"./indicators/gdp/{f.name}")
        for f in files if f.name.endswith(".html") or f.name.endswith(".png")]
    results = sandbox.fs.download_files(files_to_download)
    for result in results:
        if result.error:
            print(f"Error downloading {result.source}: {result.error}")
        else:
            print(f"Downloaded {result.source} to {result.result}")

    sandbox.delete()

async def summarizer():
    model = ChatOpenAI(model="gpt-5-mini-2025-08-07")
    agent = create_agent(model)

    input_files = [
        "./indicators/cpi/report.html",
        "./indicators/ppi/report.html",
        "./indicators/gdp/report.html",
        "./indicators/rate/report.html",
        "./indicators/unemployment_rate/report.html",
    ]

    reports = []
    for file_path in input_files:
        path = Path(file_path)
        if path.exists():
            reports.append(f"<h2>{path.parent.name}</h2>\n{path.read_text(encoding='utf-8')}")
        else:
            reports.append(f"<h2>{path.parent.name}</h2>\n<p>Missing file: {file_path}</p>")

    prompt = f"""
                You are given several HTML economic indicator reports.

                TASK:
                - Summarize all reports into ONE clean HTML document.
                - Output MUST be valid HTML only (no markdown, no explanations).

                STRICT FORMAT REQUIREMENT:
                - The ENTIRE output must be wrapped inside:
                <div class="prose">
                ...
                </div>

                - Do NOT output anything before or after this div.
                - Keep headings and structure clean and readable.

                Include sections for:
                - CPI
                - PPI
                - GDP
                - Interest Rate
                - Unemployment Rate Reports: {chr(10).join(reports)}"""

    result = await agent.ainvoke({
        "messages": [{"role": "user", "content": prompt}]
    })

    html = result.get("structured_response") or result["messages"][-1].content

    # ---- HARD ENFORCEMENT (guardrail) ----
    html = html.strip()
    if not html.startswith('<div class="prose">'):
        html = f'<div class="prose">\n{html}\n</div>'

    output_dir = Path("./indicators/index")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "report.html"
    output_file.write_text(html, encoding="utf-8")

    return str(output_file)

asyncio.run(summarizer())