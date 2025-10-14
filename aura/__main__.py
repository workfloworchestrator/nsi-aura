# Copyright 2024-2025 SURF.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import importlib
import platform

import structlog
import uvicorn

from aura import app
from aura.settings import settings

logger = structlog.get_logger()


def main() -> None:
    logger.info(
        (
            f"Starting NSI-AuRA {importlib.metadata.version("nsi-aura")} "
            f"using Python {platform.python_version()} ({platform.python_implementation()}) "
            f"on {platform.node()}"
        )
    )
    uvicorn.run(app, host=settings.NSI_AURA_HOST, port=settings.NSI_AURA_PORT)


main()
