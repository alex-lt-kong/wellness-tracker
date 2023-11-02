from typing import Any, Dict

import os

settings: Dict[str, Any] = {}
# app_dir: the app's real address on the filesystem
app_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
app_name = 'health-manager'
