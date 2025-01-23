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
import os

#
# Constants
#


SITE_TITLE = "AuRA - NSI uRA for Federating ANA"
# SITE_TITLE = 'AuRA - NSI ultimate Requester Agent for ANA'

#
# NSI Orchestrator
#
# GLOBAL_ORCHESTRATOR_URL='https://supa.moxy.ana.dlp.surfnet.nl:443'
## Test with bad URL
# GLOBAL_ORCHESTRATOR_URL='https://nosupa.moxy.ana.dlp.surfnet.nl'
# GLOBAL_ORCHESTRATOR_DISCOVERY_PATH='/discovery'

# DEMO_PROVIDER_NSA_ID='urn:ogf:network:moxy.ana.dlp.surfnet.nl:2024:nsa:supa'


ANAGRAM_DDS_URL = "https://dds.ana.dlp.surfnet.nl/dds/"

UPA_URN_PREFIX = "urn:ogf:network:"

DEFAULT_LINK_DOMAIN = "ANA"


# AuRA
# apparently cannot dynamically figure out?
SERVER_URL_PREFIX = "http://127.0.0.1:8000"
# SERVER_URL_PREFIX="http://145.100.104.178:8000"


#
# Used in polling and callbacks
#
FASTAPI_MSGNAME_RESERVE = "reserve"
FASTAPI_MSGNAME_QUERY_RECURSIVE = "queryRecursive"

# fake not ONLINE data
sample_qr_cbpath = os.path.join("samples", "query-recursive-callback-example3.xml")
