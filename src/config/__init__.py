"""config — plan §16.

Not a stub: this package holds real configuration data (models.yaml,
budget.yaml, ...) plus a tiny path helper. Business logic that *reads*
this config lives in the packages that use it (llm/, planning/, ...), not
here — config stays data, per the plan's "put change where it's cheap"
rule (system design guide §20).
"""
from pathlib import Path

CONFIG_DIR = Path(__file__).parent
