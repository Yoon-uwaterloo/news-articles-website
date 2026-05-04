# 1) Install packages
pip install -U langchain "langchain[openai]" deepagents langchain-openai langchain-daytona "pymongo[srv]" firecrawl-py

# 2) Create backend directory and files
touch .env
touch api_key.py

# 3) api_key.py
daytona_api = "YOUR_DAYTONA_API_KEY"
fred_api = "YOUR_FRED_API_KEY"
firecrawl_api="YOUR_FIRECRAWL_API_KEY"

# 4) .env
OPENAI_API_KEY="YOUR_OPENAI_API_KEY"
LANGSMITH_TRACING="true"
LANGSMITH_API_KEY="YOUR_LANGSMITH_API_KEY"

Important:
- Do not name any file langchain.py
- Correct import is: from api_key import daytona_api, fred_api
- Not: from api_key.py import daytona_api

# 5) Execute
## start database
connect docker
atlas local setup myDeployment --mdbVersion 8.0 --port 27017 --connectWith connectionString

## start website
python3 -m http.server 8000

# 6) Monitor:
- MongoDB Compass
- Docker Dashboard
- Daytona API Dashboard
- OpenAI API Platform
- Langsmith

# 7) Sources
parent id : https://api.stlouisfed.org/fred/category?category_id=22&api_key={fred_api}&file_type=json
## 1) cpi_id = 9
https://api.stlouisfed.org/fred/category/children?category_id=9&api_key={fred_api}&file_type=json
Summary 1: https://api.stlouisfed.org/fred/category/series?category_id=9&api_key={fred_api}&file_type=json
Summary 2: Whole
## 2) ppi_id = 31
https://api.stlouisfed.org/fred/category/children?category_id=33583&api_key={fred_api}&file_type=json
https://api.stlouisfed.org/fred/category/children?category_id=33584&api_key={fred_api}&file_type=json
Summary 1: https://api.stlouisfed.org/fred/category/series?category_id=31&api_key={fred_api}&file_type=json
Summary 2: Whole
## 3) interest_rate_id = 22
https://api.stlouisfed.org/fred/category/children?category_id=22&api_key={fred_api}&file_type=json
Summary: Whole
## 4) unemployment_rate_id = 32447
unrate: https://api.stlouisfed.org/fred/category/series?category_id=32447&api_key={fred_api}&file_type=json
Summary: Whole
## 5) gdp_id = 106
## 6) shared_gdp_id = 33020
https://api.stlouisfed.org/fred/category/series?category_id=106&api_key={fred_api}&file_type=json
https://api.stlouisfed.org/fred/category/series?category_id=33020&api_key={fred_api}&file_type=json
Summary: Whole
