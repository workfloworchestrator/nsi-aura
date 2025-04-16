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
from typing import Annotated, Any
from uuid import UUID

from annotated_types import Ge, Gt, Le, doc
from pydantic import BaseModel, computed_field
from sqlalchemy.orm import column_property
from sqlalchemy.testing.schema import mapped_column
from sqlmodel import Field, SQLModel, select

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
    stpId: str
    inboundPort: str | None
    outboundPort: str | None
    inboundAlias: str | None
    outboundAlias: str | None
    vlanRange: str  # our labels are VLAN's
    description: str | None

    @property
    def organisationId(self) -> str:
        _, _, _, fqdn, date, *opaque_part = self.stpId.split(":")
        return fqdn + ":" + date

    @property
    def networkId(self) -> str:
        _, _, _, fqdn, date, *opaque_part = self.stpId.split(":")
        return opaque_part[0]

    @property
    def localId(self) -> str:
        _, _, _, fqdn, date, *opaque_part = self.stpId.split(":")
        return ":".join(opaque_part[1:])

    @property
    def urn_base(self) -> str:
        return f"urn:ogf:network:{self.stpId}"

    @property
    def urn(self) -> str:
        return f"{self.urn_base}?vlan={self.vlanRange}"


class SDP(SQLModel, table=True):
    """NSI Service Demarcation Point."""

    id: int | None = Field(default=None, primary_key=True)
    stpAId: int
    stpZId: int
    vlanRange: str  # our labels are VLAN's
    description: str | None


# On some installs we get confusion between Link(DataModel) and the Link HTML component
class NetworkLink(BaseModel):
    id: int
    name: str
    linkid: int
    svlanid: int  # start VLAN ID, hack for tuple
    evlanid: int  # end VLAN ID, hack for tuple. If same, then qualified STP
    domain: str  # domain for this endpoint


class Reservation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    connectionId: UUID | None
    globalReservationId: UUID
    correlationId: UUID
    description: str
    startTime: datetime | None
    endTime: datetime | None
    sourceStpId: int = mapped_column()
    destStpId: int = mapped_column()
    sdpId: int = mapped_column()  # TODO: replace with Reservation/SDP relation table for 1:n
    sourceVlan: Vlan
    destVlan: Vlan
    bandwidth: Bandwidth
    state: str  # Statemachine default state field name
    # state: str = Field(default=ConnectionStateMachine.ConnectionNew.value) # need to fix circular imports to use this

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sourceStp(self) -> Any:
        return self._sourceStp  # type: ignore[attr-defined]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def destStp(self) -> Any:
        return self._destStp  # type: ignore[attr-defined]

    # TODO: add sdp computed field


# workaround to use column_property with SQLModel by injecting the scalar subquery after the class definition
Reservation._sourceStp = column_property(
    select(STP.description).where(STP.id == Reservation.sourceStpId).correlate_except(STP).scalar_subquery()
)
Reservation._destStp = column_property(
    select(STP.description).where(STP.id == Reservation.destStpId).correlate_except(STP).scalar_subquery()
)


class Log(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    reservation_id: int
    name: str
    module: str
    line: int
    function: str
    filename: str
    timestamp: datetime
    message: str


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
