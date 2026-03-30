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

"""Tests for aura.log: DatabaseLogHandler and UvicornAccessLogFilter."""

from logging import LogRecord
from unittest.mock import MagicMock, patch

import pytest

from aura.log import DatabaseLogHandler, UvicornAccessLogFilter


class TestDatabaseLogHandler:
    @patch("aura.log.Session")
    def test_emit_with_reservationId(self, mock_session_cls):
        handler = DatabaseLogHandler()
        record = LogRecord("test", 20, "test.py", 1, None, (), None)
        record.msg = {"event": "test event", "reservationId": 42}

        mock_session = MagicMock()
        mock_session_cls.begin.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_cls.begin.return_value.__exit__ = MagicMock(return_value=False)

        handler.emit(record)
        mock_session.add.assert_called_once()

    @patch("aura.log.Session")
    def test_emit_without_structlog_dict_skips(self, mock_session_cls):
        handler = DatabaseLogHandler()
        record = LogRecord("test", 20, "test.py", 1, "plain string message", (), None)

        mock_session = MagicMock()
        mock_session_cls.begin.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_cls.begin.return_value.__exit__ = MagicMock(return_value=False)

        handler.emit(record)
        mock_session.add.assert_not_called()

    @patch("aura.log.Session")
    def test_emit_with_no_matching_id_sets_negative(self, mock_session_cls):
        handler = DatabaseLogHandler()
        record = LogRecord("test", 20, "test.py", 1, None, (), None)
        record.msg = {"event": "some event"}

        mock_session = MagicMock()
        mock_session_cls.begin.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_cls.begin.return_value.__exit__ = MagicMock(return_value=False)

        handler.emit(record)
        # reservationId is -1, so add should not be called (reservationId < 0)
        mock_session.add.assert_not_called()


class TestUvicornAccessLogFilter:
    def test_healthcheck_filtered_out(self):
        filt = UvicornAccessLogFilter()
        record = LogRecord("uvicorn.access", 20, "test.py", 1, "msg", (), None)
        record.args = ("127.0.0.1", "GET", "/healthcheck")
        assert filt.filter(record) is False

    def test_other_endpoint_passes(self):
        filt = UvicornAccessLogFilter()
        record = LogRecord("uvicorn.access", 20, "test.py", 1, "msg", (), None)
        record.args = ("127.0.0.1", "GET", "/api/reservations")
        assert filt.filter(record) is True

    def test_empty_args_passes(self):
        filt = UvicornAccessLogFilter()
        record = LogRecord("uvicorn.access", 20, "test.py", 1, "msg", (), None)
        record.args = None
        assert filt.filter(record) is True

    def test_short_args_passes(self):
        filt = UvicornAccessLogFilter()
        record = LogRecord("uvicorn.access", 20, "test.py", 1, "msg", (), None)
        record.args = ("127.0.0.1",)
        assert filt.filter(record) is True
