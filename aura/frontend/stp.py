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
from fastui.components.display import DisplayLookup
from fastui.events import GoToEvent

from aura.db import Session
from aura.frontend.util import app_page, stp_table
from aura.model import STP

router = APIRouter()


@router.get("", response_model=FastUI, response_model_exclude_none=True)
async def stp() -> list[AnyComponent]:
    """Redirect to active tab of stp page."""
    return [c.FireEvent(event=GoToEvent(url="/stp/active"))]


@router.get("/active", response_model=FastUI, response_model_exclude_none=True)
def stp_active() -> list[AnyComponent]:
    """Display all active STP in a table."""
    with Session() as session:
        stps = session.query(STP).filter(STP.active).all()
    return app_page(
        *tabs(),
        stp_table(stps),
        title="Active Service Termination Points",
    )


@router.get("/inactive", response_model=FastUI, response_model_exclude_none=True)
def stp_inactive() -> list[AnyComponent]:
    """Display all inactive STP in a table."""
    with Session() as session:
        stps = session.query(STP).filter(not STP.active).all()
    return app_page(
        *tabs(),
        stp_table(stps),
        title="Inctive Service Termination Points",
    )


@router.get("/all", response_model=FastUI, response_model_exclude_none=True)
def stp_all() -> list[AnyComponent]:
    """Display all STP in a table."""
    with Session() as session:
        stps = session.query(STP).all()
    return app_page(
        *tabs(),
        stp_table(stps),
        title="All Service Termination Points",
    )


@router.get("/{id}/", response_model=FastUI, response_model_exclude_none=True)
def stp_detail(id: int) -> list[AnyComponent]:
    """Display stp details and action buttons."""
    with Session() as session:
        stp = session.query(STP).filter(STP.id == id).one_or_none()  # type: ignore[arg-type]
    if stp is None:
        return app_page(title=f"No STP with id {id}.")
    return app_page(
        c.Details(
            data=stp,
            fields=[
                DisplayLookup(field="id"),
                DisplayLookup(field="stpId"),
                DisplayLookup(field="vlanRange"),
                DisplayLookup(field="description"),
                DisplayLookup(field="inboundPort"),
                DisplayLookup(field="outboundPort"),
                DisplayLookup(field="inboundAlias"),
                DisplayLookup(field="outboundAlias"),
                DisplayLookup(field="active"),
            ],
        ),
        c.Button(
            text="Back",
            on_click=GoToEvent(url="/stp"),
            class_name="+ ms-2",
        ),
        title=f"STP with id {id}",
    )


def tabs() -> list[AnyComponent]:
    return [
        c.LinkList(
            links=[
                c.Link(
                    components=[c.Text(text="Active")],
                    on_click=GoToEvent(url="/stp/active"),
                    active="startswith:/stp/active",
                ),
                c.Link(
                    components=[c.Text(text="Inactive")],
                    on_click=GoToEvent(url="/stp/inactive"),
                    active="startswith:/stp/inactive",
                ),
                c.Link(
                    components=[c.Text(text="All")],
                    on_click=GoToEvent(url="/stp/all"),
                    active="startswith:/stp/all",
                ),
            ],
            mode="tabs",
            class_name="+ mb-4",
        ),
    ]
