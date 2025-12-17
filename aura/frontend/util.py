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
from typing import Any

from fastui import AnyComponent
from fastui import components as c
from fastui.components.display import DisplayLookup
from fastui.events import GoToEvent, PageEvent

from aura.fsm import ConnectionStateMachine
from aura.model import SDP, STP, Reservation
from aura.settings import settings

# do not know why, but otherwise FastUI will complain
c.Link.model_rebuild()


def app_page(*components: AnyComponent, title: str | None = None) -> list[AnyComponent]:
    return [
        c.PageTitle(text=f"AURA — {title}" if title else "AURA PoC"),
        c.Navbar(
            title=settings.SITE_TITLE,
            title_event=GoToEvent(url="/"),
            start_links=[
                c.Link(
                    components=[c.Text(text="Reservations")],
                    on_click=GoToEvent(url="/reservations/active"),
                    active="startswith:/reservations",
                ),
                c.Link(
                    components=[c.Text(text="STP")],
                    on_click=GoToEvent(url="/stp/active"),
                    active="startswith:/stp",
                ),
                c.Link(
                    components=[c.Text(text="SDP")],
                    on_click=GoToEvent(url="/sdp/active"),
                    active="startswith:/sdp",
                ),
                # c.Link(
                #     components=[c.Text(text="Auth")],
                #     on_click=GoToEvent(url="/auth/login/password"),
                #     active="startswith:/auth",
                # ),
                # c.Link(
                #     components=[c.Text(text="Forms")],
                #     on_click=GoToEvent(url="/forms/login"),
                #     active="startswith:/forms",
                # ),
            ],
        ),
        c.Page(
            components=[
                *((c.Heading(text=title),) if title else ()),
                *components,
                aura_logo(),
            ],
        ),
        c.Footer(
            extra_text="AURA PoC",
            links=[
                c.Link(
                    components=[c.Text(text="Github")],
                    on_click=GoToEvent(url="https://github.com/workfloworchestrator/nsi-aura/"),
                ),
            ],
        ),
    ]


def aura_logo() -> AnyComponent:
    return c.Div(
        components=[
            c.Image(
                # src='https://avatars.githubusercontent.com/u/110818415',
                src="/static/ANA-website-footer.png",
                alt="ANA footer Logo",
                width=900,
                height=240,
                loading="lazy",
                referrer_policy="no-referrer",
            )
        ],
        class_name="+ d-flex justify-content-center",
    )


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


def to_aura_connection_state(nsi_connection_states: dict[str, Any]) -> str:
    aura_connection_state = "UNKNOWN"
    if nsi_connection_states["lifecycleState"] == "Terminated":
        aura_connection_state = ConnectionStateMachine.ConnectionTerminated.value
    elif nsi_connection_states["lifecycleState"] == "Terminating":
        aura_connection_state = ConnectionStateMachine.ConnectionTerminating.value
    elif nsi_connection_states["lifecycleState"] == "Failed":
        aura_connection_state = ConnectionStateMachine.ConnectionFailed.value
    elif nsi_connection_states["lifecycleState"] == "PassedEndTime":
        pass  # TODO: implement NSI lifecycleState is PassedEndTime
    elif nsi_connection_states["reservationState"] == "ReserveChecking":  # NSI lifecycleState is Created
        aura_connection_state = ConnectionStateMachine.ConnectionReserveChecking.value
    elif nsi_connection_states["reservationState"] == "ReserveHeld":
        aura_connection_state = ConnectionStateMachine.ConnectionReserveHeld.value
    elif nsi_connection_states["reservationState"] == "ReserveCommitting":
        aura_connection_state = ConnectionStateMachine.ConnectionReserveCommitting.value
    elif nsi_connection_states["reservationState"] == "ReserveFailed":
        aura_connection_state = ConnectionStateMachine.ConnectionReserveFailed.value
    elif nsi_connection_states["reservationState"] == "ReserveTimeout":
        aura_connection_state = ConnectionStateMachine.ConnectionReserveTimeout.value
    elif nsi_connection_states["reservationState"] == "ReserveAborting":
        pass  # TODO: NSI reservationState is ReserveAborting not handled yet until modify is implemented
    elif nsi_connection_states["provisionState"] == "Provisioning":  # NSI reservationState is ReserveStart
        aura_connection_state = ConnectionStateMachine.ConnectionProvisioning.value
    elif nsi_connection_states["provisionState"] == "Releasing":
        aura_connection_state = ConnectionStateMachine.ConnectionReleasing.value
    elif (
        nsi_connection_states["provisionState"] == "Provisioned"
        and nsi_connection_states["dataPlaneStatus"]["active"] == "true"
    ):
        aura_connection_state = ConnectionStateMachine.ConnectionActive.value
    elif (
        nsi_connection_states["provisionState"] == "Provisioned"
        and nsi_connection_states["dataPlaneStatus"]["active"] == "false"
    ):
        aura_connection_state = ConnectionStateMachine.ConnectionProvisioned.value
    elif (
        nsi_connection_states["provisionState"] == "Released"
        and nsi_connection_states["dataPlaneStatus"]["active"] == "true"
    ):
        aura_connection_state = ConnectionStateMachine.ConnectionReleased.value
    elif (
        nsi_connection_states["provisionState"] == "Released"
        and nsi_connection_states["dataPlaneStatus"]["active"] == "false"
    ):
        aura_connection_state = ConnectionStateMachine.ConnectionReserveCommitted.value
    return aura_connection_state


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
        class_name="+ small",
    )


def stp_table(stps: list[STP]) -> c.Table:
    return c.Table(
        data_model=STP,
        data=stps,
        columns=[
            DisplayLookup(field="id", on_click=GoToEvent(url="/stp/{id}/")),
            DisplayLookup(field="stpId"),
            DisplayLookup(field="vlanRange"),
            DisplayLookup(field="description"),
            DisplayLookup(field="active"),
        ],
        class_name="+ small",
    )


def sdp_table(sdps: list[SDP]) -> c.Table:
    return c.Table(
        data_model=SDP,
        data=sdps,
        columns=[
            DisplayLookup(field="id", on_click=GoToEvent(url="/sdp/{id}/")),
            DisplayLookup(field="stpAId"),
            DisplayLookup(field="stpZId"),
            DisplayLookup(field="vlanRange"),
            DisplayLookup(field="description"),
            DisplayLookup(field="active"),
        ],
        class_name="+ small",
    )


def reservation_tabs() -> list[AnyComponent]:
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


def reservation_header(reservation: Reservation) -> c.Div:
    return c.Div(
        class_name="+ container fw-bold fs-6",
        components=[
            c.Div(
                class_name="+ row",
                components=[
                    c.Div(class_name="+ col-md-2", components=[c.Text(text="Id:")]),
                    c.Div(class_name="+ col-md-10", components=[c.Text(text=str(reservation.id))]),
                ],
            ),
            c.Div(
                class_name="+ row",
                components=[
                    c.Div(class_name="+ col-md-2", components=[c.Text(text="Description:")]),
                    c.Div(class_name="+ col-md-10", components=[c.Text(text=reservation.description)]),
                ],
            ),
            c.Div(
                class_name="+ row",
                components=[
                    c.Div(class_name="+ col-md-2", components=[c.Text(text="Connection ID:")]),
                    c.Div(class_name="+ col-md-10", components=[c.Text(text=str(reservation.connectionId))]),
                ],
            ),
            # add some margin at bottom size 3
            c.Div(class_name="+ row mb-3", components=[]),
        ],
    )
