"""Current prompts. Complete message bodies: role modules. JSON contracts: schemas.py.

Version identifiers are provenance, independent of experiment names.
v10 clarifies delegation boundaries and context evidence; r12 simplifies probe and refiner guidance.
"""

PROMPTS_VERSION = "v10"
REFINER_PROMPTS_VERSION = "r12"

from .task import (
    original_task_text,
)

from .orchestrator import (
    orchestrator_system,
    orchestrator_action_schema,
    orchestrator_task_message,
    report_message,
    invalid_action_message,
    FORCE_FINISH,
)

from .worker import (
    worker_system,
    context_block,
    context_with_additions,
    worker_request,
    CONTEXT_ADDITIONS_HEAD,
    TOOL_LIMIT_REACHED,
    IMAGES_FOLLOW,
)

from .probe import (
    probe_system,
    PROBE_TOOL_LIMIT_REACHED,
    PROBE_LABELS,
    probe_tool_policy,
    probe_instruction,
    parse_probe,
    followup_message,
)

from .refiner import (
    simulate_request,
    analyze_request,
    verify_instruction,
    rewrite_request,
    REVIEW_HEAD,
    DECISIONS,
)

from .schemas import ORCHESTRATOR_ACTION_SCHEMA, ANALYZE_SCHEMA, REWRITE_SCHEMA

from .tools import TOOL_LINES
