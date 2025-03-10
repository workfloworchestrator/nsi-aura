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

import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Annotated, AsyncIterable
from uuid import uuid4

import structlog
from fastapi import APIRouter, HTTPException
from fastui import AnyComponent, FastUI
from fastui import components as c
from fastui.components.display import DisplayLookup
from fastui.events import GoToEvent, PageEvent
from fastui.forms import SelectSearchResponse, fastui_form
from pydantic import Field
from starlette.responses import StreamingResponse
from statemachine.exceptions import TransitionNotAllowed

from aura.db import Session
from aura.frontend.util import app_page, button_with_modal
from aura.fsm import ConnectionStateMachine
from aura.job import (
    gui_release_connection_job,
    gui_terminate_connection_job,
    nsi_send_provision_job,
    nsi_send_reserve_job,
    scheduler,
)
from aura.model import STP, Bandwidth, Log, Reservation, Vlan
from aura.settings import settings

router = APIRouter()
from fastui.base import BaseModel

logger = structlog.get_logger()


class ReservationInputForm(BaseModel):
    """Input form with all connection input fields with validation, where possible."""

    description: str = Field(
        title="connection description",
    )
    sourceSTP: str = Field(
        title="source endpoint",
        json_schema_extra={"search_url": "/api/reservations/search_endpoints"},
    )
    sourceVlan: Vlan = Field(
        title="source VLAN ID",
        description="value between 2 and 4094",
    )
    destSTP: str = Field(
        title="destination endpoint",
        json_schema_extra={"search_url": "/api/reservations/search_endpoints"},
    )
    destVlan: Vlan = Field(
        title="destination VLAN ID",
        description="value between 2 and 4094",
    )
    bandwidth: Bandwidth = Field(
        title="connection bandwidth",
        description="in Mbits/s",
    )
    startTime: datetime | None = Field(
        default=None,
        title="start time",
        description="optional start time of connection, leave empty to start now",
    )
    endTime: datetime | None = Field(
        default=None,
        title="end time",
        description="optional end time of connection, leave empty for indefinite",
    )


@router.get("/search_endpoints", response_model=SelectSearchResponse)
def search_view() -> SelectSearchResponse:
    """Get list of endpoints from database suitable for input form drop down."""
    with Session() as session:
        stps = session.query(STP).all()
    endpoints = defaultdict(list)
    for stp in stps:
        endpoints[stp.description].append({"value": str(stp.id), "label": stp.localId})
    options = [{"label": k, "options": v} for k, v in endpoints.items()]
    return SelectSearchResponse(options=options)


@router.get("/new", response_model=FastUI, response_model_exclude_none=True)
def input_form() -> list[AnyComponent]:
    """Render input form."""
    submit_url = "/api/reservations/new"
    return app_page(
        *tabs(),
        c.ModelForm(model=ReservationInputForm, submit_url=submit_url, display_mode="page"),
        title="New reservation",
    )


@router.post("/new", response_model=FastUI, response_model_exclude_none=True)
def reservation_post(form: Annotated[ReservationInputForm, fastui_form(ReservationInputForm)]):
    """Store values from input form in reservation database and start NSI reserve job."""
    reservation = Reservation(
        globalReservationId=uuid4(),
        description=form.description,
        sourceStpId=int(form.sourceSTP),
        destStpId=int(form.destSTP),
        sourceVlan=Vlan(form.sourceVlan),
        destVlan=Vlan(form.destVlan),
        bandwidth=form.bandwidth,
        startTime=form.startTime,
        endTime=form.endTime,
        state=ConnectionStateMachine.ConnectionNew.value,
    )
    with Session.begin() as session:
        session.add(reservation)
        session.flush()
        reservation_id = reservation.id
        csm = ConnectionStateMachine(reservation)
        csm.nsi_send_reserve()  # TODO: move this action behind a button on the reservation overview page
    scheduler.add_job(nsi_send_reserve_job, args=[reservation_id])

    return [c.FireEvent(event=GoToEvent(url=f"/reservations/{reservation_id}/log"))]


@router.get("", response_model=FastUI, response_model_exclude_none=True)
async def reservations() -> list[AnyComponent]:
    """Redirect to active tab of reservations page."""
    return [c.FireEvent(event=GoToEvent(url="/reservations/active"))]


@router.get("/{id}/", response_model=FastUI, response_model_exclude_none=True)
def reservation_details(id: int) -> list[AnyComponent]:
    """Display reservation details and action buttons."""
    root_url = str(settings.SERVER_URL_PREFIX) + ""  # back to landing
    with Session() as session:
        reservation = session.query(Reservation).filter(Reservation.id == id).one_or_none()
    heading = reservation.description
    return app_page(
        c.Heading(level=3, text=heading),
        c.Details(
            data=reservation,
            fields=[
                DisplayLookup(field="id"),
                DisplayLookup(field="description"),
                DisplayLookup(field="startTime"),
                DisplayLookup(field="endTime"),
                DisplayLookup(field="sourceStp"),
                DisplayLookup(field="sourceVlan"),
                DisplayLookup(field="destStp"),
                DisplayLookup(field="destVlan"),
                DisplayLookup(field="bandwidth"),
                DisplayLookup(field="connectionId"),
                DisplayLookup(field="globalReservationId"),
                DisplayLookup(field="correlationId"),
                DisplayLookup(field="state"),
            ],
        ),
        *button_with_modal(
            name="modal-release-reservation",
            button="Release",
            title=f"Release reservation {reservation.description}?",
            modal="Are you sure you want to release this reservation?",
            url=f"/api/reservations/{reservation.id}/release",
        ),
        *button_with_modal(
            name="modal-provision-reservation",
            button="Provision",
            title=f"Provision reservation {reservation.description}?",
            modal="Are you sure you want to Provision this reservation?",
            url=f"/api/reservations/{reservation.id}/provision",
        ),
        *button_with_modal(
            name="modal-terminate-reservation",
            button="Terminate",
            title=f"Terminate reservation {reservation.description}?",
            modal="Are you sure you want to terminate this reservation?",
            url=f"/api/reservations/{reservation.id}/terminate",
        ),
        *button_with_modal(
            name="modal-reserve-again-reservation",
            button="Reserve Again",
            title=f"Reserve reservation {reservation.description} again?",
            modal="Are you sure you want to reserve this reservation again?",
            url=f"/api/reservations/{reservation.id}/reserve-again",
        ),
        # *button_with_modal(
        #     name="modal-re-provision-reservation",
        #     button="Re-provision",
        #     title=f"Re-provision reservation {reservation.description}?",
        #     modal="Are you sure you want to re-provision this reservation?",
        #     url=f"/api/reservations/{reservation.id}/re-provision",
        # ),
        title="Reservation details",
    )


async def reservation_log_stream(id: int) -> AsyncIterable[str]:
    lines = []
    last_timestamp = datetime.fromtimestamp(0)
    while True:
        await asyncio.sleep(0.5)
        with Session() as session:
            messages = (
                session.query(Log.message, Log.timestamp)
                .filter(Log.reservation_id == id)
                .filter(Log.timestamp > last_timestamp)
                .all()
            )
        for message, timestamp in messages:
            lines.append(c.Div(components=[c.Text(text=f"{timestamp.isoformat()} - {message}")]))
            last_timestamp = timestamp
        m = FastUI(root=lines)
        yield f"data: {m.model_dump_json(by_alias=True, exclude_none=True)}\n\n"


@router.get("/{id}/log/sse")
async def reservation_log_sse(id: int) -> StreamingResponse:
    return StreamingResponse(reservation_log_stream(id), media_type="text/event-stream")


@router.get("/{id}/log", response_model=FastUI, response_model_exclude_none=True)
async def reservation_log(id: int) -> list[AnyComponent]:
    """Show streaming log for reservation with given id."""
    return app_page(
        *tabs(),
        c.Div(
            components=[
                c.ServerLoad(
                    path=f"/reservations/{id}/log/sse",
                    sse=True,
                    sse_retry=500,
                ),
            ],
            class_name="my-2 p-2 border rounded",
        ),
        title="Streaming log",
    )


@router.post("/{id}/reserve-again", response_model=FastUI, response_model_exclude_none=True)
async def reservation_retry_reserve(id: int) -> list[AnyComponent]:
    """Reserve reservation with given id again."""
    try:
        with Session.begin() as session:
            reservation = session.query(Reservation).filter(Reservation.id == id).one()
            csm = ConnectionStateMachine(reservation)
            csm.gui_reserve_again()
            csm.nsi_send_reserve()
        scheduler.add_job(nsi_send_reserve_job, args=[id])
        return [
            c.FireEvent(event=PageEvent(name="modal-reserve-again-reservation", clear=True)),
            c.FireEvent(event=GoToEvent(url=f"/reservations/{id}/log")),
        ]
    except TransitionNotAllowed as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{id}/terminate", response_model=FastUI, response_model_exclude_none=True)
async def reservation_terminate(id: int) -> list[AnyComponent]:
    """Terminate reservation with given id."""
    try:
        with Session.begin() as session:
            reservation = session.query(Reservation).filter(Reservation.id == id).one()
            csm = ConnectionStateMachine(reservation)
            csm.gui_terminate_connection()
        scheduler.add_job(gui_terminate_connection_job, args=[id])
        return [
            c.FireEvent(event=PageEvent(name="modal-terminate-reservation", clear=True)),
            c.FireEvent(event=GoToEvent(url=f"/reservations/{id}/log")),
        ]
    except TransitionNotAllowed as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{id}/release", response_model=FastUI, response_model_exclude_none=True)
async def reservation_release(id: int) -> list[AnyComponent]:
    """Release reservation with given id."""
    try:
        with Session.begin() as session:
            reservation = session.query(Reservation).filter(Reservation.id == id).one()
            csm = ConnectionStateMachine(reservation)
            csm.gui_release_connection()
        scheduler.add_job(gui_release_connection_job, args=[id])
        return [
            c.FireEvent(event=PageEvent(name="modal-release-reservation", clear=True)),
            c.FireEvent(event=GoToEvent(url=f"/reservations/{id}/log")),
        ]
    except TransitionNotAllowed as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{id}/provision", response_model=FastUI, response_model_exclude_none=True)
async def reservation_provision(id: int) -> list[AnyComponent]:
    """Provision reservation with given id."""
    try:
        with Session.begin() as session:
            reservation = session.query(Reservation).filter(Reservation.id == id).one()
            ConnectionStateMachine(reservation).gui_provision_connection()
        scheduler.add_job(nsi_send_provision_job, args=[id])
        return [
            c.FireEvent(event=PageEvent(name="modal-provision-reservation", clear=True)),
            c.FireEvent(event=GoToEvent(url=f"/reservations/{id}/log")),
        ]
    except TransitionNotAllowed as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


# @router.post("/{id}/re-provision", response_model=FastUI, response_model_exclude_none=True)
# async def reservation_re_provision(id: int) -> list[AnyComponent]:
#     """Reprovision reservation with given id."""
#     try:
#         with Session.begin() as session:
#             reservation = session.query(Reservation).filter(Reservation.id == id).one()
#             ConnectionStateMachine(reservation).nsi_send_reserve()
#         scheduler.add_job(nsi_send_reserve_job, args=[id])
#         return [
#             c.FireEvent(event=PageEvent(name="modal-re-provision-reservation", clear=True)),
#             c.FireEvent(event=GoToEvent(url=f"/reservations/{id}/log")),
#         ]
#     except TransitionNotAllowed as e:
#         raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/all", response_model=FastUI, response_model_exclude_none=True)
def reservations_all() -> list[AnyComponent]:
    """Display overview of all reservations."""
    with Session() as session:
        reservations = session.query(Reservation).all()
    return app_page(
        *tabs(),
        reservation_table(reservations),
        title="All reservations",
    )


@router.get("/active", response_model=FastUI, response_model_exclude_none=True)
def reservations_active() -> list[AnyComponent]:
    """Display overview of active reservations."""
    with Session() as session:
        reservations = (
            session.query(Reservation).filter(Reservation.state == ConnectionStateMachine.ConnectionActive.value).all()
        )
    return app_page(
        *tabs(),
        reservation_table(reservations),
        title="All reservations",
    )


@router.get("/attention", response_model=FastUI, response_model_exclude_none=True)
def reservations_attention() -> list[AnyComponent]:
    """Display overview of reservations that need attention."""
    with Session() as session:
        reservations = (
            session.query(Reservation)
            .filter(
                (Reservation.state != ConnectionStateMachine.ConnectionActive.value)
                & (Reservation.state != ConnectionStateMachine.ConnectionTerminating.value)
                & (Reservation.state != ConnectionStateMachine.ConnectionTerminated.value)
            )
            .all()
        )
    return app_page(
        *tabs(),
        reservation_table(reservations),
        title="Reservations that need attention",
    )


def reservation_table(reservations: list[Reservation]) -> c.Table:
    return c.Table(
        data_model=Reservation,
        data=reservations,
        columns=[
            DisplayLookup(field="id", on_click=GoToEvent(url="/reservations/{id}/")),
            DisplayLookup(field="description"),
            DisplayLookup(field="startTime"),
            DisplayLookup(field="endTime"),
            DisplayLookup(field="sourceStp"),
            DisplayLookup(field="sourceVlan"),
            DisplayLookup(field="destStp"),
            DisplayLookup(field="destVlan"),
            DisplayLookup(field="bandwidth"),
            DisplayLookup(field="state"),
        ],
    )


def tabs() -> list[AnyComponent]:
    return [
        c.LinkList(
            links=[
                c.Link(
                    components=[c.Text(text="Active")],
                    on_click=GoToEvent(url="/reservations/active"),
                    active="startswith:/reservations/active",
                ),
                c.Link(
                    components=[c.Text(text="Attention")],
                    on_click=GoToEvent(url="/reservations/attention"),
                    active="startswith:/reservations/attention",
                ),
                c.Link(
                    components=[c.Text(text="All")],
                    on_click=GoToEvent(url="/reservations/all"),
                    active="startswith:/reservations/all",
                ),
                c.Link(
                    components=[c.Text(text="New")],
                    on_click=GoToEvent(url="/reservations/new"),
                    active="startswith:/reservations/new",
                ),
            ],
            mode="tabs",
            class_name="+ mb-4",
        ),
    ]
