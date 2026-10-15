"""Current role prompts; historical prompts live in experiment snapshots."""
PROMPTS_VERSION = "v24"
PROBE_PROMPTS_VERSION = "r24"
from .task import original_task_text
from .worker import worker_system, worker_request, continuation_request, context_block, TOOL_LIMIT_REACHED, IMAGES_FOLLOW
from .probe import probe_system, probe_instruction, parse_probe, PROBE_LABELS, PROBE_TOOL_LIMIT_REACHED
from .orchestrator import ORCHESTRATOR, CHOOSE_ACTION, NO_EXECUTIONS_LEFT, report_block, orchestrator_start
