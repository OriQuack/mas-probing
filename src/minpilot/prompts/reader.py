"""Page-reader messages; only source text and the question are substituted."""

PROMPT = """Please read the source content and answer a following question:
---begin of source content---
{source}
---end of source content---

If there is no relevant information, please clearly refuse to answer. Now answer the question based on the above content:
{question}"""

PART_PROMPT = """Please read the source content and answer a following question:
--- begin of source content ---
{source}
--- end of source content ---

If there is no relevant information, please clearly refuse to answer. Now answer the question based on the above content:
{question}"""
