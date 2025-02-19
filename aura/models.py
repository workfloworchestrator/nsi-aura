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

from datetime import datetime
from typing import Annotated
from uuid import UUID

from annotated_types import Ge, Gt, Le, doc
from pydantic import BaseModel
from sqlmodel import Field, SQLModel

#
# Types
#
Vlan = Annotated[int, Ge(2), Le(4094), doc("VLAN ID.")]
Bandwidth = Annotated[int, Gt(0)]

#
# Models
#


#
# Endpoint
# --------
# TODO: CONCURRENCY: add absolute identifier such that those can be used in URLs instead of Model id's
# which may change during a reload of topos
#
class Endpoint(BaseModel):
    id: int
    name: str
    svlanid: int  # start VLAN ID, hack for tuple
    evlanid: int  # end VLAN ID, hack for tuple. If same, then qualified STP
    domain: str  # domain for this endpoint


class STP(SQLModel, table=True):
    """NSI Service Termination Point."""

    id: int | None = Field(default=None, primary_key=True)
    organisationId: str  # ORGID ":" DATE (see GFD.202)
    networkId: str  # <STP identifier> ::= <networkId> “:” <localId> <label> (see GDF.237)
    localId: str
    vlanRange: str  # our labels are VLAN's
    description: str | None

    @property
    def urn_base(self):
        return f"urn:ogf:network:{self.organisationId}:{self.networkId}:{self.localId}"

    @property
    def urn(self):
        return f"{self.urn_base}?vlan={self.vlanRange}"


# On some installs we get confusion between Link(DataModel) and the Link HTML component
class NetworkLink(BaseModel):
    id: int
    name: str
    linkid: int
    svlanid: int  # start VLAN ID, hack for tuple
    evlanid: int  # end VLAN ID, hack for tuple. If same, then qualified STP
    domain: str  # domain for this endpoint


class Reservation(SQLModel, table=True):
    """TODO: class should be renamed to `Connection`."""

    id: int | None = Field(default=None, primary_key=True)
    connectionId: str | None
    globalReservationId: UUID | None
    correlationId: UUID | None
    description: str
    startTime: datetime | None
    endTime: datetime | None
    sourceSTP: int
    destSTP: int
    sourceVlan: Vlan
    destVlan: Vlan
    bandwidth: Bandwidth
    reservationState: str | None
    lifecycleState: str | None
    dataPlaneStatus: str | None
    state: str  # Statemachine default state field name # TODO: this should replace other state's
    # state: str = Field(default=ConnectionStateMachine.ConnectionNew.value) # need to fix circular imports to use this


#
# Span i.e. a Connection i,e., two STPs that are connected, e.g. for showing a path
#
class Span(BaseModel):
    id: int
    connectionId: str  # connectionId UUID
    sourceSTP: str  # source STP URN
    destSTP: str  # dest STP URN


#
# Discovery, i.e. NSI metadata information on a uPA such as version and expires
#
class Discovery(BaseModel):
    id: int
    agentid: str  # 'urn:ogf:network:ana.dlp.surfnet.nl:2024:nsa:safnari',
    version: str  # '2024-11-27T15:07:21.050548388Z',
    expires: str  # '2025-11-27T15:07:24.229Z'},
    # 'services': {'application/vnd.ogf.nsi.dds.v1+xml': 'https://dds.ana.dlp.surfnet.nl/dds', 'application/vnd.ogf.nsi.cs.v2.requester+soap': 'https://safnari.ana.dlp.surfnet.nl/nsi-v2/ConnectionServiceRequester', 'application/vnd.ogf.nsi.cs.v2.provider+soap': 'https://safnari.ana.dlp.surfnet.nl/nsi-v2/ConnectionServiceProvider'}}
