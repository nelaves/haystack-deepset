# SPDX-FileCopyrightText: 2022-present deepset GmbH <info@deepset.ai>
#
# SPDX-License-Identifier: Apache-2.0
from typing import Optional
import logging

from dataclasses import dataclass

import pytest

from canals.testing import BaseTestComponent
from canals.component import component, ComponentInput, ComponentOutput


logger = logging.getLogger(__name__)


@component
class Greet:
    """
    Logs a greeting message without affecting the value passing on the connection.
    """

    @dataclass
    class Input(ComponentInput):
        value: int
        message: str
        log_level: str

    @dataclass
    class Output(ComponentOutput):
        value: int

    def __init__(
        self,
        message: Optional[str] = "\nGreeting component says: Hi! The value is {value}\n",
        log_level: Optional[str] = "INFO",
    ):
        """
        :param message: the message to log. Can use `{value}` to embed the value.
        :param log_level: the level to log at.
        """
        if log_level and not getattr(logging, log_level):
            raise ValueError(f"This log level does not exist: {log_level}")
        self.defaults = {"message": message, "log_level": log_level}

    def run(self, data: Input) -> Output:
        """
        Logs a greeting message without affecting the value passing on the connection.
        """
        print(data.log_level)
        level = getattr(logging, data.log_level, None)
        if not level:
            raise ValueError(f"This log level does not exist: {data.log_level}")

        logger.log(level=level, msg=data.message.format(value=data.value))
        return Greet.Output(value=data.value)


class TestGreet(BaseTestComponent):
    @pytest.fixture
    def components(self):
        return [
            Greet(),
            Greet(message="Hello, that's {value}"),
            Greet(log_level="WARNING"),
            Greet(message="Hello, that's {value}", log_level="WARNING"),
        ]

    def test_greet_message(self, caplog):
        caplog.set_level(logging.WARNING)
        component = Greet()
        results = component.run(Greet.Input(value=10, message="Hello, that's {value}", log_level="WARNING"))
        assert results == Greet.Output(value=10)
        assert "Hello, that's 10" in caplog.text
