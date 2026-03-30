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

"""Tests for aura.dds: DDS parsing functions."""

import base64
import zlib

import pytest

from aura.dds import has_alias, strip_urn, to_dict, to_list, topology_to_stps, unzip
from tests.data.topology_samples import MINIMAL_TOPOLOGY, MOXY_TOPOLOGY


class TestStripUrn:
    @pytest.mark.parametrize(
        "urn,expected",
        [
            pytest.param("urn:ogf:network:surf.example:2024:net:port", "surf.example:2024:net:port", id="with-prefix"),
            pytest.param("surf.example:2024:net:port", "surf.example:2024:net:port", id="without-prefix"),
            pytest.param("urn:ogf:network:", "", id="only-prefix"),
        ],
    )
    def test_strip_urn(self, urn, expected):
        assert strip_urn(urn) == expected


class TestToDict:
    def test_with_list(self):
        collection = [{"id": "a", "val": 1}, {"id": "b", "val": 2}]
        assert to_dict("id", collection) == {"a": {"id": "a", "val": 1}, "b": {"id": "b", "val": 2}}

    def test_with_dict(self):
        collection = {"id": "a", "val": 1}
        assert to_dict("id", collection) == {"a": {"id": "a", "val": 1}}

    def test_with_unsupported_type(self):
        assert to_dict("id", "string") == {}


class TestToList:
    def test_basic(self):
        collection = [{"id": "a"}, {"id": "b"}]
        assert to_list("id", collection) == ["a", "b"]

    def test_single_element(self):
        assert to_list("key", [{"key": "value"}]) == ["value"]


class TestHasAlias:
    @pytest.mark.parametrize(
        "inbound,outbound,expected",
        [
            pytest.param("alias_in", "alias_out", True, id="both-present"),
            pytest.param(None, "alias_out", False, id="inbound-none"),
            pytest.param("alias_in", None, False, id="outbound-none"),
            pytest.param(None, None, False, id="both-none"),
        ],
    )
    def test_has_alias(self, inbound, outbound, expected, stp_factory):
        stp = stp_factory(inboundAlias=inbound, outboundAlias=outbound)
        assert has_alias(stp) == expected


class TestUnzip:
    @staticmethod
    def _gzip_compress(data: bytes) -> bytes:
        """Compress data with gzip format (wbits=16+MAX_WBITS)."""
        compressor = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
        return compressor.compress(data) + compressor.flush()

    def test_roundtrip(self):
        original = b"<topology>test</topology>"
        compressed = base64.b64encode(self._gzip_compress(original))
        doc = {"content": compressed.decode()}
        assert unzip(doc) == original

    def test_empty_content(self):
        original = b""
        compressed = base64.b64encode(self._gzip_compress(original))
        doc = {"content": compressed.decode()}
        assert unzip(doc) == original


class TestTopologyToStps:
    def test_parses_moxy_topology(self):
        stps = topology_to_stps(MOXY_TOPOLOGY)
        assert len(stps) == 4
        stp_ids = {stp.stpId for stp in stps}
        assert "moxy.ana.dlp.surfnet.nl:2024:ana-moxy:hpc-1" in stp_ids
        assert "moxy.ana.dlp.surfnet.nl:2024:ana-moxy:research-1" in stp_ids
        assert "moxy.ana.dlp.surfnet.nl:2024:ana-moxy:link-to-surf-1" in stp_ids
        assert "moxy.ana.dlp.surfnet.nl:2024:ana-moxy:link-to-surf-2" in stp_ids

    def test_parses_vlan_ranges(self):
        stps = topology_to_stps(MOXY_TOPOLOGY)
        stp_by_id = {stp.stpId: stp for stp in stps}
        assert stp_by_id["moxy.ana.dlp.surfnet.nl:2024:ana-moxy:hpc-1"].vlanRange == "3762-3769"
        assert stp_by_id["moxy.ana.dlp.surfnet.nl:2024:ana-moxy:research-1"].vlanRange == "147"

    def test_parses_aliases_on_link_ports(self):
        stps = topology_to_stps(MOXY_TOPOLOGY)
        stp_by_id = {stp.stpId: stp for stp in stps}
        link1 = stp_by_id["moxy.ana.dlp.surfnet.nl:2024:ana-moxy:link-to-surf-1"]
        assert link1.inboundAlias == "surf.ana.dlp.surfnet.nl:2024:ana-surf:ana-link-1:out"
        assert link1.outboundAlias == "surf.ana.dlp.surfnet.nl:2024:ana-surf:ana-link-1:in"

    def test_no_aliases_on_endpoint_ports(self):
        stps = topology_to_stps(MOXY_TOPOLOGY)
        stp_by_id = {stp.stpId: stp for stp in stps}
        hpc = stp_by_id["moxy.ana.dlp.surfnet.nl:2024:ana-moxy:hpc-1"]
        assert hpc.inboundAlias is None
        assert hpc.outboundAlias is None

    def test_parses_descriptions(self):
        stps = topology_to_stps(MOXY_TOPOLOGY)
        stp_by_id = {stp.stpId: stp for stp in stps}
        assert stp_by_id["moxy.ana.dlp.surfnet.nl:2024:ana-moxy:hpc-1"].description == "High Performance Cluster in Canada"

    def test_all_stps_active(self):
        stps = topology_to_stps(MOXY_TOPOLOGY)
        assert all(stp.active for stp in stps)

    def test_missing_bidirectional_port_returns_empty(self):
        assert topology_to_stps({"id": "test"}) == []

    def test_missing_relation_returns_empty(self):
        topology = {"id": "test", "BidirectionalPort": []}
        assert topology_to_stps(topology) == []

    def test_minimal_topology(self):
        stps = topology_to_stps(MINIMAL_TOPOLOGY)
        assert len(stps) == 1
        assert stps[0].stpId == "test:2024:net:port-1"
        assert stps[0].vlanRange == "100-200"
