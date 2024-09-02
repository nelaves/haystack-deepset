# SPDX-FileCopyrightText: 2022-present deepset GmbH <info@deepset.ai>
#
# SPDX-License-Identifier: Apache-2.0

import copy
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class ChatRole(str, Enum):
    """Enumeration representing the roles within a chat."""

    ASSISTANT = "assistant"
    USER = "user"
    SYSTEM = "system"
    FUNCTION = "function"


@dataclass
class ChatMessage:
    """
    Represents a message in a LLM chat conversation.

    :param content: The text content of the message.
    :param role: The role of the entity sending the message.
    :param name: The name of the function being called (only applicable for role FUNCTION).
    :param meta: Additional metadata associated with the message.
    """

    content: str
    role: ChatRole
    name: Optional[str]
    meta: Dict[str, Any] = field(default_factory=dict, hash=False)

    def is_from(self, role: ChatRole) -> bool:
        """
        Check if the message is from a specific role.

        :param role: The role to check against.
        :returns: True if the message is from the specified role, False otherwise.
        """
        return self.role == role

    @classmethod
    def from_assistant(cls, content: str, meta: Optional[Dict[str, Any]] = None) -> "ChatMessage":
        """
        Create a message from the assistant.

        :param content: The text content of the message.
        :param meta: Additional metadata associated with the message.
        :returns: A new ChatMessage instance.
        """
        return cls(content, ChatRole.ASSISTANT, None, meta or {})

    @classmethod
    def from_user(cls, content: str) -> "ChatMessage":
        """
        Create a message from the user.

        :param content: The text content of the message.
        :returns: A new ChatMessage instance.
        """
        return cls(content, ChatRole.USER, None)

    @classmethod
    def from_system(cls, content: str) -> "ChatMessage":
        """
        Create a message from the system.

        :param content: The text content of the message.
        :returns: A new ChatMessage instance.
        """
        return cls(content, ChatRole.SYSTEM, None)

    @classmethod
    def from_function(cls, content: str, name: str) -> "ChatMessage":
        """
        Create a message from a function call.

        :param content: The text content of the message.
        :param name: The name of the function being called.
        :returns: A new ChatMessage instance.
        """
        return cls(content, ChatRole.FUNCTION, name)

    def to_dict(self) -> Dict[str, Any]:
        """
        Converts ChatMessage into a dictionary.

        :returns:
            Serialized version of the object.
        """
        data = asdict(self)
        data["role"] = self.role.value

        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatMessage":
        """
        Creates a new ChatMessage object from a dictionary.

        :param data:
            The dictionary to build the ChatMessage object.
        :returns:
            The created object.
        """
        data["role"] = ChatRole(data["role"])

        return cls(**data)

    def __deepcopy__(self, memo):
        """
        Custom implementation of deepcopy for ChatMessage.

        :param memo: A dictionary of objects already copied during the current deepcopy pass.
        :returns: A deep copy of the ChatMessage instance.
        """
        return ChatMessage(
            content=self.content,
            role=self.role,
            name=self.name,
            meta=copy.deepcopy(self.meta, memo),  # Deep copy of the mutable meta dict
        )

    def __copy__(self):
        """
        Custom implementation of copy for ChatMessage.

        :returns: A shallow copy of the ChatMessage instance.
        """
        return ChatMessage(content=self.content, role=self.role, name=self.name, meta=self.meta)
