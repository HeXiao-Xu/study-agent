"""S4-4 变式题生成门面：业务层只 import 这里。"""
from app.ai.gen.compare import REL_TOL, match_answers, normalize_answer, parse_number
from app.ai.gen.variant_generator import (
    MAX_VARIANTS,
    PROMPT_VERSION,
    GenerationContext,
    GeneratedVariant,
    VariantGenerationError,
    generate_variants,
    render_prompt,
)

__all__ = [
    "MAX_VARIANTS",
    "PROMPT_VERSION",
    "REL_TOL",
    "GenerationContext",
    "GeneratedVariant",
    "VariantGenerationError",
    "generate_variants",
    "match_answers",
    "normalize_answer",
    "parse_number",
    "render_prompt",
]