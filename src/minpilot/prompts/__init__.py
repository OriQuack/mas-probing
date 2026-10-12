"""Current role prompts; historical prompts live in experiment snapshots."""
PROMPTS_VERSION = "v18"
REFINER_PROMPTS_VERSION = "r21"
from .task import original_task_text
from .worker import worker_system, worker_request, context_block, TOOL_LIMIT_REACHED, IMAGES_FOLLOW
from .probe import probe_system, probe_instruction, parse_probe, PROBE_LABELS, PROBE_TOOL_LIMIT_REACHED
from .evaluator import EVALUATOR_VERSION
