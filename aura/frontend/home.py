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

from fastapi import APIRouter
from fastui import AnyComponent, FastUI
from fastui import components as c

from aura.frontend.util import app_page

router = APIRouter()

text = """
NSI-AuRA, the Network Service Interface (NSI) ultimate Requester Agent (uRA)
for the Advanced North Atlantic (ANA) consortium (https://www.anaeng.global).
This is part of a project called ANA-GRAM, the ANA Global Resource Aggregation Method,
to federate the ANA trans-Atlantic links via network automation.
"""


@router.get("/", response_model=FastUI, response_model_exclude_none=True)
def home() -> list[AnyComponent]:
    return app_page(
        c.Heading(text="Introduction"),
        c.Paragraph(text=text),
        c.Div(
            components=[
                c.Image(
                    src="/static/ConnectionStateAndActions.drawio.png",
                    alt="AURA Connection State and Actions diagram",
                    loading="lazy",
                    referrer_policy="no-referrer",
                )
            ],
            class_name="+ d-flex justify-content-center",
        ),
    )
