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

#
# initialise NSI communications
#
from os import getcwd, path

from aura.nsi_comm import nsi_comm_init

# TODO: replace with Settings.STATIC_DIRECTORY, but need to fix import order first
nsi_comm_init(path.join(getcwd(), "static"))
