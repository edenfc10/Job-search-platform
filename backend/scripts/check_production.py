"""Validate AIJAA production configuration.

Exits 0 only when production mode is ready. Does not call external APIs.
"""

import json
import sys

from aijaa.core.config import get_settings
from aijaa.core.production import production_status


def main() -> int:
    settings = get_settings()
    status = production_status(settings)
    data = status.model_dump()
    if not settings.production_mode:
        data["production_ready"] = False
        data["missing_requirements"] = [
            *data["missing_requirements"],
            "AIJAA_PRODUCTION_MODE=true",
        ]
    print(json.dumps(data, indent=2))
    return 0 if data["production_ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
