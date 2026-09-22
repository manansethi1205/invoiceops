EXTRACTOR_NAME = "deterministic-baseline"
EXTRACTOR_VERSION = "0.2.0"
SCHEMA_VERSION = "invoice-v1"

HYBRID_EXTRACTOR_NAME = "hybrid-routed"
HYBRID_EXTRACTOR_VERSION = "0.3.0"
VLM_PROMPT_VERSION = "invoice-vision-v1"

# Preference order for read paths. Historical rows remain immutable and retain their own version.
CURRENT_EXTRACTION_STRATEGIES = (
    (HYBRID_EXTRACTOR_NAME, HYBRID_EXTRACTOR_VERSION),
    (EXTRACTOR_NAME, EXTRACTOR_VERSION),
)
