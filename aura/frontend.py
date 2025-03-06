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
from datetime import datetime
from typing import AsyncIterable

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastui import AnyComponent, FastUI
from fastui import components as c
from fastui.components.display import DisplayLookup
from fastui.events import BackEvent, GoToEvent, PageEvent
from starlette.responses import StreamingResponse
from statemachine.exceptions import TransitionNotAllowed

from aura.db import Session
from aura.fsm import ConnectionStateMachine
from aura.job import (
    gui_release_connection_job,
    gui_terminate_connection_job,
    nsi_send_provision_job,
    nsi_send_reserve_commit_job,
    nsi_send_reserve_job,
    scheduler,
)
from aura.model import STP, Log, Reservation
from aura.nsi_aura import create_footer
from aura.nsi_comm import nsi_util_xml_to_dict
from aura.settings import settings

router = APIRouter()

logger = structlog.get_logger()


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


@router.get("/api/reservations/", response_model=FastUI, response_model_exclude_none=True)
def reservations_view() -> list[AnyComponent]:
    """Display overview of all reservations."""
    root_url = str(settings.SERVER_URL_PREFIX) + ""  # back to landing
    heading = "Reservations"
    with Session() as session:
        reservations = session.query(Reservation).all()
    return [
        c.Page(  # Page provides a basic container for components
            components=[
                c.Heading(text=heading, level=2, class_name="+ text-danger"),
                c.Link(components=[c.Paragraph(text="Back")], on_click=BackEvent()),
                c.Link(components=[c.Paragraph(text="To Landing Page")], on_click=GoToEvent(url=root_url)),
                c.Heading(level=3, text="Reservations"),
                c.Table(
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
                ),
                create_footer(),
            ]
        ),
    ]


def button_with_modal(name: str, button: str, title: str, modal: str, url: str) -> list[AnyComponent]:
    """Create a button and modal with Cancel and Submit buttons."""
    return [
        c.Button(
            text=button,
            on_click=PageEvent(name=name),
            class_name="+ ms-2",
        ),
        c.Modal(
            title=title,
            body=[
                c.Paragraph(text=modal),
                c.Form(
                    form_fields=[],
                    submit_url=url,
                    footer=[],
                    submit_trigger=PageEvent(name=f"{name}-submit"),
                ),
            ],
            footer=[
                c.Button(
                    text="Cancel",
                    named_style="secondary",
                    on_click=PageEvent(name=name, clear=True),
                ),
                c.Button(
                    text="Submit",
                    on_click=PageEvent(name=f"{name}-submit"),
                ),
            ],
            open_trigger=PageEvent(name=name),
        ),
    ]


@router.get("/api/reservations/{id}/", response_model=FastUI, response_model_exclude_none=True)
def reservation_details(id: int) -> list[AnyComponent]:
    """Display reservation details and action buttons."""
    root_url = str(settings.SERVER_URL_PREFIX) + ""  # back to landing
    with Session() as session:
        reservation = session.query(Reservation).filter(Reservation.id == id).one_or_none()
    heading = reservation.description
    return [
        # c.PageTitle(text=reservation.description),
        c.Page(  # Page provides a basic container for components
            components=[
                c.Link(components=[c.Paragraph(text="Back")], on_click=BackEvent()),
                c.Link(components=[c.Paragraph(text="To Landing Page")], on_click=GoToEvent(url=root_url)),
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
                    name="modal-terminate-reservation",
                    button="Terminate Reservation",
                    title=f"Terminate reservation {reservation.description}?",
                    modal="Are you sure you want to terminate this reservation?",
                    url=f"/api/reservations/{reservation.id}/terminate",
                ),
                *button_with_modal(
                    name="modal-release-reservation",
                    button="Release Reservation",
                    title=f"Release reservation {reservation.description}?",
                    modal="Are you sure you want to release this reservation?",
                    url=f"/api/reservations/{reservation.id}/release",
                ),
                c.Button(
                    text="Reprovision Reservation",
                    on_click=PageEvent(name="modal-reprovision-reservation"),
                    class_name="+ ms-2",
                ),
                c.Modal(
                    title=f"Reprovision reservation {reservation.description}?",
                    body=[
                        c.Paragraph(text="Are you sure you want to reprovision this reservation?"),
                        c.Form(
                            form_fields=[],
                            submit_url=f"/api/reservations/{reservation.id}/reprovision",
                            footer=[],
                            submit_trigger=PageEvent(name="modal-reprovision-reservation-submit"),
                        ),
                    ],
                    footer=[
                        c.Button(
                            text="Cancel",
                            named_style="secondary",
                            on_click=PageEvent(name="modal-reprovision-reservation", clear=True),
                        ),
                        c.Button(
                            text="Submit",
                            on_click=PageEvent(name="modal-reprovision-reservation-submit"),
                        ),
                    ],
                    open_trigger=PageEvent(name="modal-reprovision-reservation"),
                ),
                create_footer(),
            ]
        ),
    ]


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
            lines.append(c.Div(components=[c.Text(text=message)]))
            last_timestamp = timestamp
        m = FastUI(root=lines)
        yield f"data: {m.model_dump_json(by_alias=True, exclude_none=True)}\n\n"


@router.get("/api/reservations/{id}/log/sse")
async def reservation_log_sse(id: int) -> StreamingResponse:
    return StreamingResponse(reservation_log_stream(id), media_type="text/event-stream")


@router.get("/api/reservations/{id}/log", response_model=FastUI, response_model_exclude_none=True)
async def reservation_log(id: int) -> list[AnyComponent]:
    """Show streaming log for reservation with given id."""
    heading = "streaming log"
    return [
        c.Page(  # Page provides a basic container for components
            components=[
                c.Heading(text=heading, level=2, class_name="+ text-danger"),
                c.Link(components=[c.Paragraph(text="Back")], on_click=BackEvent()),
                c.Heading(level=3, text="log ...."),
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
                create_footer(),
            ]
        ),
    ]


@router.post("/api/reservations/{id}/terminate", response_model=FastUI, response_model_exclude_none=True)
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


@router.post("/api/reservations/{id}/release", response_model=FastUI, response_model_exclude_none=True)
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


@router.post("/api/reservations/{id}/reprovision", response_model=FastUI, response_model_exclude_none=True)
async def reservation_reprovision(id: int) -> list[AnyComponent]:
    """Reprovision reservation with given id."""
    with Session.begin() as session:
        reservation = session.query(Reservation).filter(Reservation.id == id).one()
        ConnectionStateMachine(reservation).nsi_send_reserve()
    scheduler.add_job(nsi_send_reserve_job, args=[id])
    return [c.FireEvent(event=PageEvent(name="modal-reprovision-reservation", clear=True))]


@router.post("/api/nsi/callback/")
async def nsi_callback(request: Request):
    """Receive and process NSI async callback."""
    from aura.db import Session

    log = logger.bind(module=__name__, job=nsi_callback.__name__)
    body = await request.body()
    with Session.begin() as session:
        if request.headers["soapaction"] == '"http://schemas.ogf.org/nsi/2013/12/connection/service/errorEvent"':
            error_event_dict = nsi_util_xml_to_dict(body)
            connectionId = error_event_dict["Body"]["errorEvent"]["connectionId"]
            reservation = session.query(Reservation).filter(Reservation.connectionId == connectionId).one()
        elif (
            request.headers["soapaction"]
            == '"http://schemas.ogf.org/nsi/2013/12/connection/service/dataPlaneStateChange"'
        ):
            state_change_dict = nsi_util_xml_to_dict(body)
            connectionId = state_change_dict["Body"]["dataPlaneStateChange"]["connectionId"]
            reservation = session.query(Reservation).filter(Reservation.connectionId == connectionId).one()
        else:
            reply_dict = nsi_util_xml_to_dict(body)
            correlationId = reply_dict["Header"]["nsiHeader"]["correlationId"]
            reservation = session.query(Reservation).filter(Reservation.correlationId == correlationId).one()
        log = log.bind(
            reservationId=reservation.id,
            correlationId=str(reservation.correlationId),
            connectionId=str(reservation.connectionId),
        )
        # update connection state machine
        csm = ConnectionStateMachine(reservation)
        match request.headers["soapaction"]:
            case '"http://schemas.ogf.org/nsi/2013/12/connection/service/reserveFailed"':
                log.warning("reserve failed from aggregator")
                csm.nsi_receive_reserve_failed()
            case '"http://schemas.ogf.org/nsi/2013/12/connection/service/reserveConfirmed"':
                log.info("reserve confirmed from aggregator")
                csm.nsi_receive_reserve_confirmed()
                csm.nsi_send_reserve_commit()  # TODO: decide if we want to auto commit or not
            case '"http://schemas.ogf.org/nsi/2013/12/connection/service/reserveCommitConfirmed"':
                log.info("reserve commit confirmed from aggregator")
                csm.nsi_receive_reserve_commit_confirmed()
                csm.nsi_send_provision()  # TODO: decide if we want to auto provision or not
            case '"http://schemas.ogf.org/nsi/2013/12/connection/service/provisionConfirmed"':
                log.info("provision confirmed from aggregator")
                csm.nsi_receive_provision_confirmed()
            case '"http://schemas.ogf.org/nsi/2013/12/connection/service/releaseConfirmed"':
                log.info("release confirmed from aggregator")
                csm.nsi_receive_release_confirmed()
            case '"http://schemas.ogf.org/nsi/2013/12/connection/service/terminateConfirmed"':
                log.info("terminate confirmed from aggregator")
                csm.nsi_receive_terminate_confirmed()
            case '"http://schemas.ogf.org/nsi/2013/12/connection/service/dataPlaneStateChange"':
                active = state_change_dict["Body"]["dataPlaneStateChange"]["dataPlaneStatus"]["active"]
                if active == "true":
                    log.info("data plane state change up from aggregator", active=active)
                    csm.nsi_receive_data_plane_up()
                else:
                    log.info("data plane state change down from aggregator", active=active)
                    log.warning("data plane down not implemented yet")
            case '"http://schemas.ogf.org/nsi/2013/12/connection/service/errorEvent"':
                log.info(
                    "error event from aggregator",
                    text=error_event_dict["Body"]["errorEvent"]["serviceException"]["text"],
                )
                csm.nsi_receive_error_event()
            case _:
                log.error("no matching soap action in message from aggregator")
        reservation_id = reservation.id
    # start job that corresponds with above state transition # TODO decide if we want to auto commit/provision or not
    match request.headers["soapaction"]:
        case '"http://schemas.ogf.org/nsi/2013/12/connection/service/reserveConfirmed"':
            scheduler.add_job(nsi_send_reserve_commit_job, args=[reservation_id])
        case '"http://schemas.ogf.org/nsi/2013/12/connection/service/reserveCommitConfirmed"':
            scheduler.add_job(nsi_send_provision_job, args=[reservation_id])
