import os

# TokenFactory (Kimi K2.5)
TOKEN_FACTORY_API_KEY = os.getenv("TOKEN_FACTORY_API_KEY", "")
TOKEN_FACTORY_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
KIMI_MODEL = "moonshotai/Kimi-K2.5"

# Pricing per token (Kimi K2 pricing from TokenFactory)
INPUT_COST_PER_TOKEN = 0.50 / 1_000_000   # $0.50 per 1M input tokens
OUTPUT_COST_PER_TOKEN = 2.40 / 1_000_000   # $2.40 per 1M output tokens
MAX_COST_PER_QUERY = 20.0

# Axle (Lean verification)
AXLE_API_KEY = os.getenv("AXLE_API_KEY", "")
AXLE_BASE_URL = "https://axle.axiommath.ai/api/v1"
LEAN_ENVIRONMENT = "lean-4.28.0"

# Aristotle (Lean formalization & proving)
ARISTOTLE_API_KEY = os.getenv("ARISTOTLE_API_KEY", "")
ARISTOTLE_POLL_INTERVAL = 30   # seconds between status checks
ARISTOTLE_MAX_POLLS = 40       # 40 * 30s = 20 minutes max wait

# LeanExplore (Mathlib search)
LEAN_EXPLORE_API_KEY = os.getenv("LEAN_EXPLORE_API_KEY", "")
LEAN_EXPLORE_BASE_URL = "https://www.leanexplore.com/api"

# TheoremSearch (arXiv theorem search)
THEOREM_SEARCH_BASE_URL = "https://api.theoremsearch.com"

# Agent settings
MAX_AGENT_ITERATIONS = 50
