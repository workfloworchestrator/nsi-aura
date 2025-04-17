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
from pprint import pformat
from typing import Annotated, Any, AsyncIterable, Optional, Self
from uuid import uuid4

import structlog
from fastapi import APIRouter, HTTPException
from fastui import AnyComponent, FastUI
from fastui import components as c
from fastui.base import BaseModel
from fastui.components import FireEvent
from fastui.components.display import DisplayLookup
from fastui.events import GoToEvent, PageEvent
from fastui.forms import SelectSearchResponse, fastui_form
from pydantic import Field, model_validator
from requests import RequestException
from starlette.responses import StreamingResponse
from statemachine.exceptions import TransitionNotAllowed

from aura.db import Session
from aura.dds import has_alias
from aura.exception import AuraNsiError
from aura.frontend.util import (
    app_page,
    button_with_modal,
    reservation_header,
    reservation_table,
    reservation_tabs,
    to_aura_connection_state,
)
from aura.fsm import ConnectionStateMachine
from aura.job import (
    nsi_send_provision_job,
    nsi_send_release_job,
    nsi_send_reserve_job,
    nsi_send_terminate_job,
    scheduler,
)
from aura.model import SDP, STP, Bandwidth, Log, Reservation, Vlan
from aura.nsi import nsi_send_query_summary_sync
from aura.vlan import free_vlan_ranges

router = APIRouter()

logger = structlog.get_logger()

#
# input form type definitions
#
descriptionType = Annotated[str, Field(title="connection description")]
sourceVlanType = Annotated[Vlan, Field(title="source VLAN ID", description="value between 2 and 4094")]
destVlanType = Annotated[Vlan, Field(title="destination VLAN ID", description="value between 2 and 4094")]
bandwidthType = Annotated[Bandwidth, Field(title="connection bandwidth", description="in Mbits/s")]
startTimeType = Annotated[
    Optional[datetime],
    Field(default=None, title="start time", description="optional start time of connection, leave empty to start now"),
]
endTimeType = Annotated[
    Optional[datetime],
    Field(default=None, title="end time", description="optional end time of connection, leave empty for indefinite"),
]


class ValidatedBaseModel(BaseModel):
    @model_validator(mode="after")
    def free_vlan_on_stp(self) -> Self:
        """Check that the sourceVlan and destVlan are free on the chosen SourceSTP and destSTP."""
        form = []
        if self.sourceVlan not in (free_vlans := free_vlan_ranges(int(self.sourceSTP))):  # type: ignore[attr-defined]
            form.append({"type": "invalid_vlan", "loc": ["sourceVlan"], "msg": f"free VLANs: {free_vlans}"})
        if self.destVlan not in (free_vlans := free_vlan_ranges(int(self.destSTP))):  # type: ignore[attr-defined]
            form.append({"type": "invalid_vlan", "loc": ["destVlan"], "msg": f"free VLANs: {free_vlans}"})
        if form:
            raise HTTPException(status_code=422, detail={"form": form})
        return self


def generate_stp_field(title: str = "give me a title", value: str | None = None, label: str | None = None) -> Any:
    json_schema_extra = {"search_url": "/api/reservations/endpoints"}
    if value and label:
        json_schema_extra["initial"] = {"value": value, "label": label}  # type: ignore
    return Field(title=title, json_schema_extra=json_schema_extra)  # type: ignore


def generate_sdp_field(title: str = "give me a title", value: str | None = None, label: str | None = None) -> Any:
    json_schema_extra = {"search_url": "/api/reservations/demarcation_points"}
    if value and label:
        json_schema_extra["initial"] = {"value": value, "label": label}  # type: ignore
    return Field(title=title, json_schema_extra=json_schema_extra)  # type: ignore


class ReservationInputForm(ValidatedBaseModel):
    """Input form with all connection input fields with validation, where possible."""

    description: descriptionType
    sourceSTP: Annotated[str, generate_stp_field("source endpoint")]
    sourceVlan: destVlanType
    destSTP: Annotated[str, generate_stp_field("destination endpoint")]
    destVlan: destVlanType
    bandwidth: bandwidthType
    demarcationPoint: Annotated[str, generate_sdp_field("demarcation point")]
    startTime: startTimeType
    endTime: endTimeType


def generate_modify_form(reservation_id: int) -> ValidatedBaseModel:
    with Session() as session:
        reservation = session.query(Reservation).filter(Reservation.id == reservation_id).one()  # type: ignore[arg-type]
        sdp = session.query(SDP).filter(SDP.id == reservation.sdpId).one()  # type: ignore[arg-type]

    class ReservationModifyForm(ValidatedBaseModel):
        """Input form with all connection input fields with validation, where possible."""

        description: descriptionType = reservation.description
        # sourceSTP: sourceSTPType = str(reservation.sourceStp)
        sourceSTP: str = generate_stp_field("source endpoint", str(reservation.sourceStpId), reservation.sourceStp)
        sourceVlan: destVlanType = reservation.sourceVlan
        # destSTP: destSTPType = str(reservation.destStp)
        destSTP: str = generate_stp_field("destination endpoint", str(reservation.destStpId), reservation.destStp)
        # destSTP: Annotated[str, generate_dest_stp_field()]
        destVlan: destVlanType = reservation.destVlan
        bandwidth: bandwidthType = reservation.bandwidth
        demarcationPoint: str = generate_sdp_field("demarcation point", str(reservation.sdpId), sdp.description)
        startTime: startTimeType = reservation.startTime
        endTime: endTimeType = reservation.endTime

    return ReservationModifyForm  # type: ignore[return-value]


@router.get("/endpoints", response_model=SelectSearchResponse)
def endpoints() -> SelectSearchResponse:
    """Get list of endpoints from database suitable for input form drop down."""
    with Session() as session:
        stps = [stp for stp in session.query(STP).all() if not has_alias(stp)]  # do not include STP part of SDP
    endpoints = defaultdict(list)
    for stp in stps:
        endpoints[stp.description].append({"value": str(stp.id), "label": stp.stpId})
    options = [{"label": k, "options": v} for k, v in endpoints.items()]
    return SelectSearchResponse(options=options)


@router.get("/demarcation_points", response_model=SelectSearchResponse)
def demarcation_points() -> SelectSearchResponse:
    """Get list of sdp's from database suitable for input form drop down."""
    with Session() as session:
        sdps = session.query(SDP).all()
    demarcation_points = defaultdict(list)
    for sdp in sdps:
        demarcation_points[sdp.description].append({"value": str(sdp.id), "label": sdp.description})
    options = [{"label": k, "options": v} for k, v in demarcation_points.items()]
    return SelectSearchResponse(options=options)


@router.get("/new", response_model=FastUI, response_model_exclude_none=True)
def input_form() -> list[AnyComponent]:
    """Render new input form."""
    submit_url = "/api/reservations/create"
    return app_page(
        *reservation_tabs(),
        c.ModelForm(model=ReservationInputForm, submit_url=submit_url, display_mode="page"),
        title="New reservation",
    )


@router.post("/create", response_model=FastUI, response_model_exclude_none=True)
def reservation_post(form: Annotated[ReservationInputForm, fastui_form(ReservationInputForm)]) -> list[FireEvent]:
    """Store values from input form in reservation database and start NSI reserve job."""
    reservation = Reservation(
        connectionId=None,
        globalReservationId=uuid4(),
        correlationId=uuid4(),
        description=form.description,
        sourceStpId=int(form.sourceSTP),
        destStpId=int(form.destSTP),
        sdpId=int(form.demarcationPoint),
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
    with Session() as session:
        reservation = session.query(Reservation).filter(Reservation.id == id).one_or_none()  # type: ignore[arg-type]
    if reservation is None:
        return app_page(title=f"No reservation with id {id}.")
    csm = ConnectionStateMachine(reservation)
    return app_page(
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
        c.Button(
            text="Back",
            on_click=GoToEvent(url="/reservations"),
            class_name="+ ms-2",
        ),
        c.Button(
            text="Log",
            on_click=GoToEvent(url=f"/reservations/{id}/log"),
            class_name="+ ms-2",
        ),
        *(
            button_with_modal(
                name="modal-release-reservation",
                button="Release",
                title=f"Release reservation {reservation.description}?",
                modal="Are you sure you want to release this reservation?",
                url=f"/api/reservations/{reservation.id}/release",
            )
            if csm.current_state == ConnectionStateMachine.ConnectionActive
            else []
        ),
        *(
            button_with_modal(
                name="modal-provision-reservation",
                button="Provision",
                title=f"Provision reservation {reservation.description}?",
                modal="Are you sure you want to Provision this reservation?",
                url=f"/api/reservations/{reservation.id}/provision",
            )
            if csm.current_state == ConnectionStateMachine.ConnectionReserveCommitted
            else []
        ),
        *(
            button_with_modal(
                name="modal-reserve-again-reservation",
                button="Reserve Again",
                title=f"Reserve reservation {reservation.description} again?",
                modal="Are you sure you want to reserve this reservation again?",
                url=f"/api/reservations/{reservation.id}/reserve-again",
            )
            if csm.current_state == ConnectionStateMachine.ConnectionReserveFailed
            or csm.current_state == ConnectionStateMachine.ConnectionTerminated
            else []
        ),
        *(
            button_with_modal(
                name="modal-terminate-reservation",
                button="Terminate",
                title=f"Terminate reservation {reservation.description}?",
                modal="Are you sure you want to terminate this reservation?",
                url=f"/api/reservations/{reservation.id}/terminate",
            )
            if csm.current_state == ConnectionStateMachine.ConnectionReserveTimeout
            or csm.current_state == ConnectionStateMachine.ConnectionFailed
            or csm.current_state == ConnectionStateMachine.ConnectionReserveCommitted
            or csm.current_state == ConnectionStateMachine.ConnectionReserveFailed
            else []
        ),
        *(
            [
                c.Button(
                    text="Verify",
                    on_click=GoToEvent(url=f"/reservations/{reservation.id}/verify"),
                    class_name="+ ms-2",
                )
            ]
            if csm.current_state != ConnectionStateMachine.ConnectionNew
            and csm.current_state != ConnectionStateMachine.ConnectionReserveChecking
            and csm.current_state != ConnectionStateMachine.ConnectionReserveFailed
            else []
        ),
        title="Reservation details",
    )


async def reservation_log_stream(id: int) -> AsyncIterable[str]:
    lines = []
    last_timestamp = datetime.fromtimestamp(0)
    while True:
        await asyncio.sleep(0.5)
        with Session() as session:
            messages = (
                session.query(Log.message, Log.timestamp)  # type: ignore[call-overload]
                .filter(Log.reservation_id == id)
                .filter(Log.timestamp > last_timestamp)
                .all()
            )
        for message, timestamp in messages:
            lines.append(c.Div(components=[c.Text(text=f"{timestamp.isoformat()} - {message}")]))
            last_timestamp = timestamp
        m = FastUI(root=lines)  # type: ignore[arg-type]
        yield f"data: {m.model_dump_json(by_alias=True, exclude_none=True)}\n\n"


@router.get("/{id}/log/sse")
async def reservation_log_sse(id: int) -> StreamingResponse:
    return StreamingResponse(reservation_log_stream(id), media_type="text/event-stream")


@router.get("/{id}/log", response_model=FastUI, response_model_exclude_none=True)
async def reservation_log(id: int) -> list[AnyComponent]:
    """Show streaming log for reservation with given id."""
    with Session() as session:
        reservation = session.query(Reservation).filter(Reservation.id == id).one_or_none()  # type: ignore[arg-type]
    if reservation is None:
        return app_page(title=f"No reservation with id {id}.")
    return app_page(
        reservation_header(reservation),
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
        c.Button(
            text="Back",
            on_click=GoToEvent(url=f"/reservations/{id}/"),
            class_name="+ ms-2",
        ),
        title="Streaming logs",
    )


@router.get("/{id}/modify", response_model=FastUI, response_model_exclude_none=True)
def modify_form(id: int) -> list[AnyComponent]:
    """Render modify input form."""
    submit_url = "/api/reservations/create"
    return app_page(
        *reservation_tabs(),
        c.ModelForm(model=generate_modify_form(id), submit_url=submit_url, display_mode="page"),
        title="Modify reservation",
    )


@router.post("/{id}/reserve-again", response_model=FastUI, response_model_exclude_none=True)
async def reservation_retry_reserve(id: int) -> list[AnyComponent]:
    """Reserve reservation with given id again by loading the modify page."""
    return [
        c.FireEvent(event=PageEvent(name="modal-reserve-again-reservation", clear=True)),
        c.FireEvent(event=GoToEvent(url=f"/reservations/{id}/modify")),
    ]


@router.get("/{id}/verify", response_model=FastUI, response_model_exclude_none=True)
async def reservation_verify(id: int) -> list[AnyComponent]:
    """Verify reservation with given id."""
    components: list[AnyComponent]
    with Session() as session:
        reservation = session.query(Reservation).filter(Reservation.id == id).one()  # type: ignore[arg-type]
    # new_correlation_id_on_reservation()  # TODO: is this safe, or add this to nsi_send_query_summary_sync()?
    components = [reservation_header(reservation)]
    try:
        reply_dict = nsi_send_query_summary_sync(reservation)
        if "reservation" in reply_dict["Body"]["querySummarySyncConfirmed"]:
            nsi_connection_states = reply_dict["Body"]["querySummarySyncConfirmed"]["reservation"]["connectionStates"]
        else:
            raise AuraNsiError("NSI provider: reservation not found")
    except (RequestException, ConnectionError, AuraNsiError) as exception:
        components.append(c.Heading(text="Error", level=4))
        components.append(c.Paragraph(text=f"Cannot get NSI connection states: {exception!s}"))
    else:
        connection_state = to_aura_connection_state(nsi_connection_states)
        components.append(c.Heading(text="NSI Connection States", level=4))
        components.append(c.Code(text=pformat(nsi_connection_states)))
        components.append(c.Heading(text="Verification Result", level=4))
        if reservation.state == connection_state:
            components.append(c.Paragraph(text=f"{reservation.state} matches NSI connection states"))
        else:
            components.append(c.Paragraph(text=f"{reservation.state} should be {connection_state}"))
            components.append(
                c.Button(text="Fix State", on_click=GoToEvent(url=f"/reservations/{id}/set_state/{connection_state}"))
            )
    components.append(c.Button(text="Back", on_click=GoToEvent(url=f"/reservations/{id}/"), class_name="+ ms-2"))
    return app_page(
        *components,
        title="Verify connection state",
    )


@router.get("/{id}/set_state/{new_state}", response_model=FastUI, response_model_exclude_none=True)
async def reservation_set_state(id: int, new_state: str) -> list[AnyComponent]:
    """Set reservation with given id to connection_state."""
    if new_state not in ConnectionStateMachine.states_map.keys():
        raise HTTPException(status_code=400, detail="unknown connection state")
    with Session.begin() as session:
        reservation = session.query(Reservation).filter(Reservation.id == id).one()  # type: ignore[arg-type]
        old_state = reservation.state
        reservation.state = new_state
        logger.info(
            f"force reservation from state {old_state} to {new_state}",
            old_state=old_state,
            new_state=new_state,
            reservationId=reservation.id,
            connectionId=str(reservation.connectionId),
        )
    return [c.FireEvent(event=GoToEvent(url=f"/reservations/{id}/verify"))]


@router.post("/{id}/terminate", response_model=FastUI, response_model_exclude_none=True)
async def reservation_terminate(id: int) -> list[AnyComponent]:
    """Terminate reservation with given id."""
    try:
        with Session.begin() as session:
            reservation = session.query(Reservation).filter(Reservation.id == id).one()  # type: ignore[arg-type]
            csm = ConnectionStateMachine(reservation)
            csm.nsi_send_terminate()
        scheduler.add_job(nsi_send_terminate_job, args=[id])
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
            reservation = session.query(Reservation).filter(Reservation.id == id).one()  # type: ignore[arg-type]
            csm = ConnectionStateMachine(reservation)
            csm.nsi_send_release()
        scheduler.add_job(nsi_send_release_job, args=[id])
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
            reservation = session.query(Reservation).filter(Reservation.id == id).one()  # type: ignore[arg-type]
            ConnectionStateMachine(reservation).nsi_send_provision()
        scheduler.add_job(nsi_send_provision_job, args=[id])
        return [
            c.FireEvent(event=PageEvent(name="modal-provision-reservation", clear=True)),
            c.FireEvent(event=GoToEvent(url=f"/reservations/{id}/log")),
        ]
    except TransitionNotAllowed as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/all", response_model=FastUI, response_model_exclude_none=True)
def reservations_all() -> list[AnyComponent]:
    """Display overview of all reservations."""
    with Session() as session:
        reservations = session.query(Reservation).all()
    return app_page(
        *reservation_tabs(),
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
        *reservation_tabs(),
        reservation_table(reservations),
        title="Active reservations",
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
        *reservation_tabs(),
        reservation_table(reservations),
        title="Reservations that need attention",
    )
