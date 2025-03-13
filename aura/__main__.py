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

import uvicorn
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastui import prebuilt_html
from starlette.responses import HTMLResponse, PlainTextResponse

from aura.frontend.database import router as database_router
from aura.frontend.home import router as home_router
from aura.frontend.nsi import router as nsi_router
from aura.frontend.reservations import router as reservations_router
from aura.job import nsi_poll_dds_job, scheduler
from aura.log import init as log_init

#
# logging
#
log_init()

#
# scheduler
#
scheduler.start()
# TODO: remove replace_existing after fixing running __init__ twice
scheduler.add_job(nsi_poll_dds_job, trigger=IntervalTrigger(minutes=1), coalesce=True)

#
# application
#
app = FastAPI()

# make sure the folder named 'static' exists in the project,
# and put the css and js files inside a subfolder called 'assets'
app.mount("/static", StaticFiles(directory="static"), name="static")

# include routes
app.include_router(reservations_router, prefix="/api/reservations")
app.include_router(database_router, prefix="/api/database")
app.include_router(nsi_router, prefix="/api/nsi")
app.include_router(home_router, prefix="/api")


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt() -> str:
    return "User-agent: *\nAllow: /"


@app.get("/favicon.ico", status_code=404, response_class=PlainTextResponse)
async def favicon_ico() -> str:
    return "page not found"


@app.get("/{path:path}")
async def html_landing() -> HTMLResponse:
    return HTMLResponse(prebuilt_html(title="AURA PoC"))


uvicorn.run(app, port=8000)  # TODO: make parameters configurable
