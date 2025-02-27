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

from collections import defaultdict
from datetime import datetime
from typing import Annotated
from uuid import uuid4

import structlog
from fastapi import APIRouter
from fastui import AnyComponent, FastUI
from fastui import components as c
from fastui.events import GoToEvent
from fastui.forms import SelectSearchResponse, fastui_form
from pydantic import BaseModel, Field

from aura.db import Session
from aura.fsm import ConnectionStateMachine
from aura.job import nsi_send_reserve_job, scheduler
from aura.model import STP, Bandwidth, Reservation, Vlan
from aura.settings import settings

router = APIRouter()

logger = structlog.get_logger(__name__)


class InputForm(BaseModel):
    """Input form with all connection input fields with validation, where possible."""

    description: str = Field(
        title="connection description",
    )
    sourceSTP: str = Field(
        title="source endpoint",
        json_schema_extra={"search_url": "/api/forms/search_endpoints"},
    )
    sourceVlan: Vlan = Field(
        title="source VLAN ID",
        description="value between 2 and 4094",
    )
    destSTP: str = Field(
        title="destination endpoint",
        json_schema_extra={"search_url": "/api/forms/search_endpoints"},
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


@router.get("/api/forms/search_endpoints", response_model=SelectSearchResponse)
def search_view() -> SelectSearchResponse:
    """Get list of endpoints from database suitable for input form drop down."""
    with Session() as session:
        stps = session.query(STP).all()
    endpoints = defaultdict(list)
    for stp in stps:
        endpoints[stp.description].append({"value": str(stp.id), "label": stp.localId})
    options = [{"label": k, "options": v} for k, v in endpoints.items()]
    return SelectSearchResponse(options=options)


@router.post("/api/forms/post_form/", response_model=FastUI, response_model_exclude_none=True)
def post_form(form: Annotated[InputForm, fastui_form(InputForm)]):
    """Store values from input form in reservation database and start NSI reserve job."""
    reservation = Reservation(
        globalReservationId=uuid4(),
        correlationId=uuid4(),
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

    return [c.FireEvent(event=GoToEvent(url="/"))]


@router.get("/api/forms/input_form/", response_model=FastUI, response_model_exclude_none=True)
def input_form() -> list[AnyComponent]:
    """Render input form."""
    submit_url = str(settings.SERVER_URL_PREFIX) + "api/forms/post_form/"
    return [
        c.Page(
            components=[
                c.Heading(text="input form", level=2, class_name="+ text-danger"),
                c.ModelForm(model=InputForm, submit_url=submit_url, display_mode="page"),
            ]
        )
    ]
