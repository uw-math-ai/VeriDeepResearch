---
title: VeriDeepResearch
emoji: "\U0001F9E0"
colorFrom: blue
colorTo: purple
sdk: docker
app_file: app.py
pinned: false
license: apache-2.0
short_description: Verified Deep Research powered by Lean 4
---

# VeriDeepResearch

Verified Deep Research is an agentic system capable of performing Deep Research in a verified way: all math used in the research is formalized in Lean, completely eliminating mathematical mistakes.

Implementation (all tools are web-based):
- Kimi K2.5 on TokenFactory to orchestrate
- TheoremSearch API to find mathematical theorems on arXiv
- Aristotle to formalize in Lean (powerful, handles hard lemmas)
- Lean Explore and Loogle to search Mathlib
- Axle to check Lean correctness (on Lean v4.28)
- Background job system with status page and email notification
- HuggingFace for hosting (Docker SDK)
