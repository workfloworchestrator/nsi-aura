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

import structlog
from fastapi import APIRouter, Request
from fastui import AnyComponent, FastUI
from fastui import components as c
from fastui.events import BackEvent, GoToEvent

from aura.db import Session
from aura.fsm import ConnectionStateMachine
from aura.job import nsi_send_provision_job, nsi_send_reserve_commit_job, scheduler
from aura.model import STP, Reservation
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
                log.warning("reserve failed")
                csm.nsi_receive_reserve_failed()
            case '"http://schemas.ogf.org/nsi/2013/12/connection/service/reserveConfirmed"':
                log.info("reserve confirmed")
                csm.nsi_receive_reserve_confirmed()
                csm.nsi_send_reserve_commit()  # TODO: decide if we want to auto commit or not
            case '"http://schemas.ogf.org/nsi/2013/12/connection/service/reserveCommitConfirmed"':
                log.info("reserve commit confirmed")
                csm.nsi_receive_reserve_commit_confirmed()
                csm.nsi_send_provision()  # TODO: decide if we want to auto provision or not
            case '"http://schemas.ogf.org/nsi/2013/12/connection/service/provisionConfirmed"':
                log.info("provision confirmed")
                csm.nsi_receive_provision_confirmed()
            case '"http://schemas.ogf.org/nsi/2013/12/connection/service/errorEvent"':
                log.info("error event", text=error_event_dict["Body"]["errorEvent"]["serviceException"]["text"])
                csm.nsi_receive_error_event()
            case _:
                log.error("no matching soap action")
        reservation_id = reservation.id
    # start job that corresponds with above state transition # TODO decide if we want to auto commit/provision or not
    match request.headers["soapaction"]:
        case '"http://schemas.ogf.org/nsi/2013/12/connection/service/reserveConfirmed"':
            scheduler.add_job(nsi_send_reserve_commit_job, args=[reservation_id])
        case '"http://schemas.ogf.org/nsi/2013/12/connection/service/reserveCommitConfirmed"':
            scheduler.add_job(nsi_send_provision_job, args=[reservation_id])
