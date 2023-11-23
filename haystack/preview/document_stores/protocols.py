from typing import Protocol, Optional, Dict, Any, List
import logging
from enum import Enum

from haystack.preview.dataclasses import Document


# Ellipsis are needed for the type checker, it's safe to disable module-wide
# pylint: disable=unnecessary-ellipsis

logger = logging.getLogger(__name__)


class DuplicatePolicy(Enum):
    SKIP = "skip"
    OVERWRITE = "overwrite"
    FAIL = "fail"


class DocumentStore(Protocol):
    """
    Stores Documents to be used by the components of a Pipeline.

    Classes implementing this protocol often store the documents permanently and allow specialized components to
    perform retrieval on them, either by embedding, by keyword, hybrid, and so on, depending on the backend used.

    In order to retrieve documents, consider using a Retriever that supports the DocumentStore implementation that
    you're using.
    """

    def to_dict(self) -> Dict[str, Any]:
        """
        Serializes this store to a dictionary.
        """
        ...

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DocumentStore":
        """
        Deserializes the store from a dictionary.
        """
        ...

    def count_documents(self) -> int:
        """
        Returns the number of documents stored.
        """
        ...

    def filter_documents(self, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """
        Returns the documents that match the filters provided.

        Filters are defined as nested dictionaries. There are two types of dictionaries:
        - Comparison
        - Logic

        Top level must be either be a Logic dictionary.
        Comparison dictionaries must contain the keys:

        - `field`
        - `operator`
        - `value`

        Logic dictionaries must contain the keys:

        - `operator`
        - `conditions`

        `conditions` key must be a list of dictionaries, either Comparison or Logic.

        `operator` values in Comparison dictionaries must be:

        - `==`
        - `!=`
        - `>`
        - `>=`
        - `<`
        - `<=`
        - `in`
        - `not in`

        `operator` values in Logic dictionaries must be:

        - `NOT`
        - `OR`
        - `AND`


        A simple filter:
        ```python
        filters = {"field": "meta.type", "operator": "==", "value": "article"}
        ```

        A more complex filter:
        ```python
        filters = {
            "operator": "AND",
            "conditions": [
                {"field": "meta.type", "operator": "==", "value": "article"},
                {"field": "meta.date", "operator": ">=", "value": 1420066800},
                {"field": "meta.date", "operator": "<", "value": 1609455600},
                {"field": "meta.rating", "operator": ">=", "value": 3},
                {
                    "operator": "OR",
                    "conditions": [
                        {"field": "meta.genre", "operator": "in", "value": ["economy", "politics"]},
                        {"field": "meta.publisher", "operator": "==", "value": "nytimes"},
                    ],
                },
            ],
        }

        :param filters: the filters to apply to the document list.
        :return: a list of Documents that match the given filters.
        """
        ...

    def write_documents(self, documents: List[Document], policy: DuplicatePolicy = DuplicatePolicy.FAIL) -> int:
        """
        Writes (or overwrites) documents into the DocumentStore.

        :param documents: a list of documents.
        :param policy: documents with the same ID count as duplicates. When duplicates are met,
            the DocumentStore can:
             - skip: keep the existing document and ignore the new one.
             - overwrite: remove the old document and write the new one.
             - fail: an error is raised
        :raises DuplicateError: Exception trigger on duplicate document if `policy=DuplicatePolicy.FAIL`
        :return: The number of documents that was written.
            If DuplicatePolicy.OVERWRITE is used, this number is always equal to the number of documents in input.
            If DuplicatePolicy.SKIP is used, this number can be lower than the number of documents in the input list.
        """
        ...

    def delete_documents(self, document_ids: List[str]) -> None:
        """
        Deletes all documents with a matching document_ids from the DocumentStore.
        Fails with `MissingDocumentError` if no document with this id is present in the DocumentStore.

        :param object_ids: the object_ids to delete
        """
        ...
