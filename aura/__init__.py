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
# FastAPI
#
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from aura.form import router as form_router
from aura.frontend import router as frontend_router
from aura.route import router as route_router

app = FastAPI()

# make sure the folder named 'static' exists in the project,
# and put the css and js files inside a subfolder called 'assets'
app.mount("/static", StaticFiles(directory="static"), name="static")

# include routes
app.include_router(form_router)
app.include_router(frontend_router)
app.include_router(route_router)

#
# initialise NSI communications
#
from os import getcwd, path

from aura.nsi_comm import nsi_comm_init

# TODO: replace with Settings.STATIC_DIRECTORY, but need to fix import order first
nsi_comm_init(path.join(getcwd(), "static"))
