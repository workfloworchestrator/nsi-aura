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
from fastui.events import GoToEvent

from aura.db import Session
from aura.frontend.util import app_page
from aura.model import SDP, Reservation

router = APIRouter()


@router.get("/reservation", response_model=FastUI, response_model_exclude_none=True)
def database_table_reservation() -> list[AnyComponent]:
    """Display all database tables and their contents."""
    with Session() as session:
        reservations = session.query(Reservation).all()
    return app_page(
        *tabs(),
        c.Table(
            data_model=Reservation,
            data=reservations,
            class_name="+ table-sm small",
        ),
        title="Reservation",
    )


@router.get("/sdp", response_model=FastUI, response_model_exclude_none=True)
def database_table_sdp() -> list[AnyComponent]:
    """Display SDP table content."""
    with Session() as session:
        sdps = session.query(SDP).all()
    return app_page(
        *tabs(),
        c.Table(
            data_model=SDP,
            data=sdps,
            class_name="+ table-sm small",
        ),
        title="SDP",
    )


def tabs() -> list[AnyComponent]:
    return [
        c.LinkList(
            links=[
                c.Link(
                    components=[c.Text(text="Reservation")],
                    on_click=GoToEvent(url="/database/reservation"),
                    active="startswith:/database/reservation",
                ),
                c.Link(
                    components=[c.Text(text="SDP")],
                    on_click=GoToEvent(url="/database/sdp"),
                    active="startswith:/database/sdp",
                ),
            ],
            mode="tabs",
            class_name="+ mb-4",
        ),
    ]
