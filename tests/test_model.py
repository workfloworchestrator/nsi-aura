# Copyright 2024-2026 SURF.
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

"""Tests for aura.model: STP properties and type validation."""

import pytest

from aura.model import STP


class TestSTPOrganisationId:
    @pytest.mark.parametrize(
        "stp_id,expected",
        [
            pytest.param(
                "urn:ogf:network:surf.ana.dlp.surfnet.nl:2024:ana-surf:university-1",
                "surf.ana.dlp.surfnet.nl:2024",
                id="surf",
            ),
            pytest.param(
                "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:hpc-1",
                "moxy.ana.dlp.surfnet.nl:2024",
                id="moxy",
            ),
        ],
    )
    def test_organisationId(self, stp_id, expected, stp_factory):
        stp = stp_factory(stpId=stp_id)
        assert stp.organisationId == expected


class TestSTPNetworkId:
    @pytest.mark.parametrize(
        "stp_id,expected",
        [
            pytest.param(
                "urn:ogf:network:surf.ana.dlp.surfnet.nl:2024:ana-surf:university-1",
                "ana-surf",
                id="surf",
            ),
            pytest.param(
                "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:hpc-1",
                "ana-moxy",
                id="moxy",
            ),
        ],
    )
    def test_networkId(self, stp_id, expected, stp_factory):
        stp = stp_factory(stpId=stp_id)
        assert stp.networkId == expected


class TestSTPLocalId:
    @pytest.mark.parametrize(
        "stp_id,expected",
        [
            pytest.param(
                "urn:ogf:network:surf.ana.dlp.surfnet.nl:2024:ana-surf:university-1",
                "university-1",
                id="simple-local",
            ),
            pytest.param(
                "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:hpc-1",
                "hpc-1",
                id="hpc",
            ),
            pytest.param(
                "urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:ana-moxy:link-to-surf-1:in",
                "link-to-surf-1:in",
                id="multi-colon-local",
            ),
        ],
    )
    def test_localId(self, stp_id, expected, stp_factory):
        stp = stp_factory(stpId=stp_id)
        assert stp.localId == expected


class TestSTPUrn:
    def test_urn_base(self, stp_factory):
        stp = stp_factory(stpId="urn:ogf:network:surf.ana.dlp.surfnet.nl:2024:ana-surf:university-1")
        assert stp.urn_base == "urn:ogf:network:urn:ogf:network:surf.ana.dlp.surfnet.nl:2024:ana-surf:university-1"

    def test_urn_with_vlan(self, stp_factory):
        stp = stp_factory(
            stpId="urn:ogf:network:surf.ana.dlp.surfnet.nl:2024:ana-surf:university-1",
            vlanRange="100-200",
        )
        expected = "urn:ogf:network:urn:ogf:network:surf.ana.dlp.surfnet.nl:2024:ana-surf:university-1?vlan=100-200"
        assert stp.urn == expected

    def test_urn_base_stripped_stpid(self, stp_factory):
        """Test with stpId that doesn't have urn:ogf:network: prefix (as stored after strip_urn)."""
        stp = stp_factory(stpId="surf.ana.dlp.surfnet.nl:2024:ana-surf:university-1")
        assert stp.urn_base == "urn:ogf:network:surf.ana.dlp.surfnet.nl:2024:ana-surf:university-1"

    def test_urn_stripped_stpid(self, stp_factory):
        """Test with stpId after strip_urn processing."""
        stp = stp_factory(stpId="surf.ana.dlp.surfnet.nl:2024:ana-surf:university-1", vlanRange="100-200")
        assert stp.urn == "urn:ogf:network:surf.ana.dlp.surfnet.nl:2024:ana-surf:university-1?vlan=100-200"


class TestSTPPropertiesWithStrippedStpId:
    """Test STP properties with stpId format as stored in DB (after strip_urn).

    The organisationId/networkId/localId properties expect the full URN format
    with urn:ogf:network: prefix (at least 5 colon-separated parts).
    Stripped stpIds have fewer parts and will raise ValueError.
    """

    def test_stripped_stpid_raises_on_properties(self, stp_factory):
        stp = stp_factory(stpId="surf.ana.dlp.surfnet.nl:2024:ana-surf:university-1")
        with pytest.raises(ValueError, match="not enough values to unpack"):
            _ = stp.organisationId
