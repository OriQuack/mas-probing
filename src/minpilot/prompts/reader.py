"""Page-reader messages; only source text and the question are substituted."""

PROMPT = """Please read the source content and answer the following question:
---begin of source content---
{source}
---end of source content---

If the provided source contains no relevant information, say that you did not find it in this source. If it answers only part of the question, report that information and what remains unanswered. Now answer the question based on the above content:
{question}"""

PART_PROMPT = """Please read the source content and answer the following question:
--- begin of source content ---
{source}
--- end of source content ---

If the provided source part contains no relevant information, say that you did not find it in this part. If it answers only part of the question, report that information and what remains unanswered. Now answer the question based on the above content:
{question}"""
