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

from typing import Any

import structlog
from statemachine import State, StateMachine
from structlog.stdlib import BoundLogger

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
                f"State transition to {state.name}",
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
    ConnectionTerminated = State("ConnectionTerminated", "CONNECTION_TERMINATED")
    ConnectionDeleted = State("ConnectionDeleted", "CONNECTION_DELETED", final=True)
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

    # fmt: off
    nsi_send_reserve = (
        ConnectionNew.to(ConnectionReserveChecking)
        | ConnectionReserveAborted.to(ConnectionReserveChecking)
        | ConnectionTerminated.to(ConnectionReserveChecking)
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
    gui_delete_connection = ConnectionTerminated.to(ConnectionDeleted)
    nsi_receive_error_event = (
        ConnectionActive.to(ConnectionFailed)
        | ConnectionProvisioned.to(ConnectionFailed)
    )
    gui_terminate_connection = (
        ConnectionActive.to(ConnectionTerminating)
        | ConnectionFailed.to(ConnectionTerminating)
    )
    nsi_receive_terminate_confirmed = ConnectionTerminating.to(ConnectionTerminated)
    gui_reserve_retry = (
        ConnectionReserveFailed.to(ConnectionReserveAborting)
        | ConnectionReserveTimeout.to(ConnectionReserveAborting)
    )
    # fmt: on

    # Cannot add job as part of transition because it is possible (but not likely) that the state is not stored before
    # the job wants to make the following transition and will fail
    #
    # def on_nsi_send_reserve(self):
    #     scheduler.add_job(nsi_send_reserve_job, args=[self.model.id])
    #
    # def on_nsi_send_reserve_commit(self):
    #     scheduler.add_job(nsi_send_reserve_commit_job, args=[self.model.id])
    #
    # def on_nsi_send_provision(self):
    #     scheduler.add_job(nsi_send_provision_job, args=[self.model.id])


if __name__ == "__main__":
    """Generate images for the statemachine(s)."""
    from statemachine.contrib.diagram import DotGraphMachine

    DotGraphMachine(ConnectionStateMachine)().write_png("images/ConnectionStateMachine.png")
