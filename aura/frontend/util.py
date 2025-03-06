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

from fastui import AnyComponent
from fastui import components as c
from fastui.events import GoToEvent, PageEvent

# do not know why, but otherwise FastUI will complain
c.Link.model_rebuild()


def app_page(*components: AnyComponent, title: str | None = None) -> list[AnyComponent]:
    return [
        c.PageTitle(text=f"FastUI Demo — {title}" if title else "FastUI Demo"),
        c.Navbar(
            title="AURA PoC",
            title_event=GoToEvent(url="/"),
            start_links=[
                c.Link(
                    components=[c.Text(text="Reservations")],
                    on_click=GoToEvent(url="/reservations/active"),
                    active="startswith:/reservations",
                ),
                c.Link(
                    components=[c.Text(text="Database")],
                    on_click=GoToEvent(url="/database/reservation"),
                    active="startswith:/database",
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
                class_name="border rounded",
            )
        ]
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
