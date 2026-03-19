---
title: VeriDeepResearch
emoji: "\U0001F9E0"
colorFrom: blue
colorTo: purple
sdk: gradio
sdk_version: 6.5.1
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
- Qwen 3.5 on TokenFactory to formalize in lean (reasonbly capable, fast)
- Aristotle to formalize in Lean (powerful, slow)
- Lean Explore and loogle to search mathlib
- Axle to check Lean correctness (on Lean v4.28)
- chatbot interface on the web (single query only)
- HuggingFace for hosting
