#  Copyright 2025 SURF.
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import structlog

from aura import state
from statemachine import State, StateMachine
from structlog.stdlib import BoundLogger

from aura.models import STP
from aura.nsi_comm import generate_reserve_xml, URN_STP_NAME, URN_STP_VLAN, nsi_util_post_soap, \
    nsi_soap_parse_reserve_reply, NSI_RESERVE_TEMPLATE_XMLFILE
from aura.settings import settings

logger = structlog.get_logger(__name__)


class AuraStateMachine(StateMachine):
    """Add logging capabilities to StateMachine."""

    log: BoundLogger

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Log name of finite state machine and call __init__ of super class with original arguments."""
        self.log = logger.bind(fsm=self.__class__.__name__)
        super().__init__(*args, **kwargs)

    def on_enter_state(self, state: State) -> None:
        """Statemachine will call this function on every state transition."""
        if isinstance(state, State):
            self.log.info(
                "State transition",
                to_state=state.id,
                connectionId=str(self.model.connectionId),  # type: ignore[union-attr]
            )


class ConnectionStateMachine(AuraStateMachine):
    """Reservation State Machine.

    .. image:: /images/ConnectionStateMachine.png
    """

    ConnectionNew = State("ConnectionNew", "CONNECTION_NEW", initial=True)
    ConnectionProvisioned = State("ConnectionProvisioned", "CONNECTION_PROVISIONED")
    ConnectionActive = State("ConnectionActive", "CONNECTION_ACTIVE")
    ConnectionFailed = State("ConnectionFailed", "CONNECTION_FAILED")
    ConnectionTerminated = State("ConnectionTerminated", "CONNECTION_TERMINATED", final=True)
    ConnectionReserveChecking = State("ConnectionReserveChecking", "CONNECTION_RESERVE_CHECKING")
    ConnectionReserveHeld = State("ConnectionReserveHeld", "RESERVE_HELD")
    ConnectionReserveCommitting = State("ConnectionReserveCommitting", "CONNECTION_RESERVE_COMMITTING")
    ConnectionReserveCommitted = State("ConnectionReserveCommitted", "CONNECTION_RESERVE_COMMITTED")
    ConnectionProvisioning = State("ConnectionProvisioning", "CONNECTION_PROVISIONING")
    ConnectionReserveFailed = State("ConnectionReserveFailed", "CONNECTION_RESERVE_FAILED")
    ConnectionReserveTimeout = State("ConnectionReserveTimeout", "CONNECTION_RESERVE_TIMEOUT")
    ConnectionReserveAborting = State("ConnectionReserveAborting", "CONNECTION_RESERVE_ABORTING")
    ConnectionReserveAborted = State("ConnectionReserveAborted", "CONNECTION_RESERVE_ABORTED")
    ConnectionTerminating = State("ConnectionTerminating", "CONNECTION_TERMINATING")
    ConnectionReprovisionTerminating = State("ConnectionReprovisionTerminating", "CONNECTION_REPROVISION_TERMINATING")
    ConnectionReprovisionTerminated = State("ConnectionReprovisionTerminated", "CONNECTION_REPROVISION_TERMINATED")

    # fmt: off
    nsi_send_reserve = (
        ConnectionNew.to(ConnectionReserveChecking)
        | ConnectionReserveAborted.to(ConnectionReserveChecking)
        | ConnectionReprovisionTerminated.to(ConnectionReserveChecking)
    )
    nsi_receive_reserve_confirmed = ConnectionReserveChecking.to(ConnectionReserveHeld)
    nsi_receive_reserve_failed = ConnectionReserveChecking.to(ConnectionReserveFailed)
    nsi_receive_reserve_timeout = ConnectionReserveHeld.to(ConnectionReserveTimeout)
    nsi_receive_reserve_abort_confirmed = ConnectionReserveAborting.to(ConnectionReserveAborted)
    nsi_send_reserve_commit = ConnectionReserveHeld.to(ConnectionReserveCommitting)
    nsi_receive_reserve_commit_confirmed = ConnectionReserveCommitting.to(ConnectionReserveCommitted)
    nsi_send_provision = ConnectionReserveCommitted.to(ConnectionProvisioning)
    nsi_receive_provision_confirmed = ConnectionProvisioning.to(ConnectionProvisioned)
    nsi_receive_data_plane_up = ConnectionProvisioned.to(ConnectionActive)
    nsi_receive_error_event = ConnectionActive.to(ConnectionFailed)
    gui_connection_reprovision = ConnectionFailed.to(ConnectionReprovisionTerminating)
    gui_terminate_connection = (
        ConnectionActive.to(ConnectionTerminating)
        | ConnectionFailed.to(ConnectionTerminating)
    )
    nsi_receive_terminate_confirmed = (
        ConnectionTerminating.to(ConnectionTerminated)
        | ConnectionReprovisionTerminating.to(ConnectionReprovisionTerminated)
    )
    gui_reserve_retry = (
        ConnectionReserveFailed.to(ConnectionReserveAborting)
        | ConnectionReserveTimeout.to(ConnectionReserveAborting)
    )
    # fmt: on

    @nsi_send_reserve.on
    def nsi_send_reserve(self):
        from aura.db import Session
        logger.info("this executes on the nsi send reserve transition")
        reserve_templpath = os.path.join(os.path.join(os.getcwd(), "static"), NSI_RESERVE_TEMPLATE_XMLFILE)
        with open(reserve_templpath) as reserve_templfile:
            reserve_templstr = reserve_templfile.read()
        with Session() as session:
            source_stp = session.query(STP).filter(STP.id == self.model.sourceSTP).one()
            dest_stp = session.query(STP).filter(STP.id == self.model.destSTP).one()
        correlation_id = uuid4()
        reserve_xml = generate_reserve_xml(
            reserve_templstr,  # SOAP reserve template
            correlation_id,  # correlation id
            str(settings.NSA_BASE_URL) + "/api/nsi/callback/",  # reply-to url
            self.model.description,  # reservation description
            uuid4(),  # TODO: global reservation id should be stored on reservation/connection in database
            self.model.startTime.replace(tzinfo=timezone.utc) if self.model.startTime else datetime.now(timezone.utc),  # start time, TODO: proper timezone handling
            self.model.endTime.replace(tzinfo=timezone.utc) if self.model.endTime else datetime.now(timezone.utc) + timedelta(weeks=1040),  # end time
            {URN_STP_NAME: source_stp.urn_base, URN_STP_VLAN: self.model.sourceVlan},  # source stp dict
            {URN_STP_NAME: dest_stp.urn_base, URN_STP_VLAN: self.model.destVlan},   # destination stp dict
            state.global_provider_nsa_id,   # provider nsa id
        )


        print("RESERVE: Request XML", reserve_xml)

        print("RESERVE: CALLING ORCH")
        soap_xml = nsi_util_post_soap(state.global_soap_provider_url, reserve_xml)

        print("RESERVE: GOT HTTP REPLY", soap_xml)

        retdict = nsi_soap_parse_reserve_reply(soap_xml)

        print("RESERVE: Got connectionId", retdict)
        retdict["correlationId"] = str(correlation_id)
        retdict["globalReservationId"] = str(state.global_reservation_uuid_py)
        # ,"connectionId":connection_id_str}


if __name__ == "__main__":
    """Generate images for the statemachine(s)."""
    from statemachine.contrib.diagram import DotGraphMachine

    DotGraphMachine(ConnectionStateMachine)().write_png("images/ConnectionStateMachine.png")
