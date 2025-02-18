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

from fastapi import APIRouter
from fastui import AnyComponent, FastUI
from fastui import components as c
from fastui.events import BackEvent, GoToEvent

from aura.db import Session
from aura.models import STP, Reservation
from aura.nsi_aura import create_footer
from aura.settings import settings

router = APIRouter()


@router.get("/api/database/", response_model=FastUI, response_model_exclude_none=True)
def fastapi_database_tables() -> list[AnyComponent]:
    """Display all database tables and their contents."""
    root_url = str(settings.SERVER_URL_PREFIX) + ""  # back to landing
    heading = "Database tables"
    with Session() as session:
        stps = session.query(STP).all()
        reservations = session.query(Reservation).all()
    return [
        c.Page(  # Page provides a basic container for components
            components=[
                c.Heading(text=heading, level=2, class_name="+ text-danger"),
                c.Link(components=[c.Paragraph(text="Back")], on_click=BackEvent()),
                c.Link(components=[c.Paragraph(text="To Landing Page")], on_click=GoToEvent(url=root_url)),
                c.Heading(level=3, text="ServiceTerminationPoint"),
                c.Table(
                    data_model=STP,
                    data=stps,
                ),
                c.Heading(level=3, text="Reservation"),
                c.Table(
                    data_model=Reservation,
                    data=reservations,
                ),
                create_footer(),
            ]
        ),
    ]
