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
from statemachine.exceptions import TransitionNotAllowed

from aura.fsm import ConnectionStateMachine
from aura.job import nsi_send_provision_job, nsi_send_reserve_commit_job, scheduler
from aura.model import Reservation
from aura.nsi_comm import nsi_util_xml_to_dict

router = APIRouter()

logger = structlog.get_logger(__name__)


def soap_action(request: Request, action: str) -> bool:
    """Check if the given action matches the soap action header on the request."""
    return request.headers["soapaction"] == action


@router.post("/callback/")
async def nsi_callback(request: Request):
    """Receive and process NSI async callback."""
    from aura.db import Session

    log = logger.bind(module=__name__, job=nsi_callback.__name__)
    body = await request.body()
    with Session.begin() as session:
        try:
            if soap_action(request, '"http://schemas.ogf.org/nsi/2013/12/connection/service/errorEvent"'):
                error_event_dict = nsi_util_xml_to_dict(body)
                connectionId = error_event_dict["Body"]["errorEvent"]["connectionId"]
                reservation = session.query(Reservation).filter(Reservation.connectionId == connectionId).one()
            elif soap_action(request, '"http://schemas.ogf.org/nsi/2013/12/connection/service/dataPlaneStateChange"'):
                state_change_dict = nsi_util_xml_to_dict(body)
                connectionId = state_change_dict["Body"]["dataPlaneStateChange"]["connectionId"]
                reservation = session.query(Reservation).filter(Reservation.connectionId == connectionId).one()
            elif soap_action(request, '"http://schemas.ogf.org/nsi/2013/12/connection/service/reserveTimeout"'):
                state_change_dict = nsi_util_xml_to_dict(body)
                connectionId = state_change_dict["Body"]["reserveTimeout"]["connectionId"]
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
                    log.warning("reserve failed from nsi provider")
                    csm.nsi_receive_reserve_failed()
                case '"http://schemas.ogf.org/nsi/2013/12/connection/service/reserveTimeout"':
                    log.warning("reserve timeout from nsi provider")
                    csm.nsi_receive_reserve_timeout()
                case '"http://schemas.ogf.org/nsi/2013/12/connection/service/reserveConfirmed"':
                    log.info("reserve confirmed from nsi provider")
                    csm.nsi_receive_reserve_confirmed()
                    csm.nsi_send_reserve_commit()  # TODO: decide if we want to auto commit or not
                # case '"http://schemas.ogf.org/nsi/2013/12/connection/service/reserveAbortConfirmed"':
                #     log.info("reserve abort confirmed from nsi provider")
                #     csm.nsi_receive_reserve_abort_confirmed()
                #     csm.nsi_send_reserve()  # TODO: decide if we want to auto provision or not
                case '"http://schemas.ogf.org/nsi/2013/12/connection/service/reserveCommitConfirmed"':
                    log.info("reserve commit confirmed from nsi provider")
                    csm.nsi_receive_reserve_commit_confirmed()
                    csm.nsi_send_provision()  # TODO: decide if we want to auto provision or not
                case '"http://schemas.ogf.org/nsi/2013/12/connection/service/provisionConfirmed"':
                    log.info("provision confirmed from nsi provider")
                    csm.nsi_receive_provision_confirmed()
                case '"http://schemas.ogf.org/nsi/2013/12/connection/service/releaseConfirmed"':
                    log.info("release confirmed from nsi provider")
                    csm.nsi_receive_release_confirmed()
                case '"http://schemas.ogf.org/nsi/2013/12/connection/service/terminateConfirmed"':
                    log.info("terminate confirmed from nsi provider")
                    csm.nsi_receive_terminate_confirmed()
                case '"http://schemas.ogf.org/nsi/2013/12/connection/service/dataPlaneStateChange"':
                    active = state_change_dict["Body"]["dataPlaneStateChange"]["dataPlaneStatus"]["active"]
                    if active == "true":
                        log.info("data plane state change up from nsi provider", active=active)
                        csm.nsi_receive_data_plane_up()
                    else:
                        log.info("data plane state change down from nsi provider", active=active)
                        csm.nsi_receive_data_plane_down()
                case '"http://schemas.ogf.org/nsi/2013/12/connection/service/errorEvent"':
                    text = error_event_dict["Body"]["errorEvent"]["serviceException"]["text"]
                    log.warning(f"error event from nsi provider: {text}", text=text)
                    csm.nsi_receive_error_event()
                case _:
                    log.error("no matching soap action in message from nsi provider")
            reservation_id = reservation.id
        except TransitionNotAllowed as e:
            log.warning(str(e))
    # start job that corresponds with above state transition # TODO decide if we want to auto commit/provision or not
    match request.headers["soapaction"]:
        case '"http://schemas.ogf.org/nsi/2013/12/connection/service/reserveConfirmed"':
            scheduler.add_job(nsi_send_reserve_commit_job, args=[reservation_id])
        case '"http://schemas.ogf.org/nsi/2013/12/connection/service/reserveCommitConfirmed"':
            scheduler.add_job(nsi_send_provision_job, args=[reservation_id])
        # case '"http://schemas.ogf.org/nsi/2013/12/connection/service/reserveAbortConfirmed"':
        #     scheduler.add_job(nsi_send_reserve_commit_job(), args=[reservation_id])
