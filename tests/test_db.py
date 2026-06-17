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

"""Tests for aura.db: database engine configuration."""


def test_engine_uses_pool_pre_ping():
    """The engine must enable pool_pre_ping to survive dropped backend connections.

    Reproduces the production crash where nsi_poll_dds_job failed with
    'OperationalError: server closed the connection unexpectedly' after Azure
    Postgres closed a stale pooled connection. pool_pre_ping validates a
    connection before use and transparently reconnects when it is dead.
    """
    import aura.db

    assert aura.db.engine.pool._pre_ping is True
