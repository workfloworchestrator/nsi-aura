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
from aura.model import STP, Reservation

router = APIRouter()


@router.get("/reservation", response_model=FastUI, response_model_exclude_none=True)
def fastapi_database_tables() -> list[AnyComponent]:
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


@router.get("/stp", response_model=FastUI, response_model_exclude_none=True)
def fastapi_database_tables() -> list[AnyComponent]:
    """Display all database tables and their contents."""
    with Session() as session:
        stps = session.query(STP).all()
        reservations = session.query(Reservation).all()
    return app_page(
        *tabs(),
        c.Table(
            data_model=STP,
            data=stps,
            class_name="+ table-sm small",
        ),
        title="STP",
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
                    components=[c.Text(text="STP")],
                    on_click=GoToEvent(url="/database/stp"),
                    active="startswith:/database/stp",
                ),
            ],
            mode="tabs",
            class_name="+ mb-4",
        ),
    ]
