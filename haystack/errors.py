# coding: utf8
"""Custom Errors for Haystack"""

from typing import Optional
from jsonschema.exceptions import ValidationError


class HaystackError(Exception):
    """
    Any error generated by Haystack.

    This error wraps its source transparently in such a way that its attributes
    can be accessed directly: if the original error has a `message` attribute,
    `HaystackError.message` will exist and have the expected content.

    Give the source error as the `source` parameter to enable this behavior.
    Subclasses of HaystackError might enforce specific error classes as their source.
    """

    def __init__(self, message: str = "", source: Optional[Exception] = None, docs_link: Optional[str] = None):
        super().__init__()
        self.message = message
        self.source = source
        self.docs_link = None

        if self.source:
            try:
                source_string = str(getattr(self.source, "message"))
            except AttributeError:
                source_string = str(self.source)

            if message and message.strip() != "" and source_string != "":
                self.message = f"{message} ({source_string})"
            else:
                self.message = source_string

    def __getattr__(self, attr):
        # If self.source is None, it will raise the expected AttributeError
        getattr(self.source, attr)

    def __str__(self):
        if self.docs_link:
            docs_message = f"\n\nCheck out the documentation at {self.docs_link}"
            return self.message + docs_message
        return self.message

    def __repr__(self):
        return str(self)


class PipelineError(HaystackError):
    """Exception for issues raised within a pipeline"""

    def __init__(
        self,
        message: str = "",
        source: Optional[Exception] = None,
        docs_link: Optional[str] = "https://haystack.deepset.ai/pipelines",
    ):
        super().__init__(message=message, source=source, docs_link=docs_link)


class PipelineSchemaError(PipelineError):
    pass


class PipelineConfigError(PipelineError):
    """Exception for issues raised within a pipeline's config file"""

    def __init__(
        self,
        message: str = "",
        source: Optional[Exception] = None,
        docs_link: Optional[str] = "https://haystack.deepset.ai/pipelines#yaml-file-definitions",
    ):
        super().__init__(message=message, source=source, docs_link=docs_link)


class DocumentStoreError(HaystackError):
    """Exception for issues that occur in a document store"""

    pass


class DuplicateDocumentError(DocumentStoreError, ValueError):
    """Exception for Duplicate document"""

    pass
