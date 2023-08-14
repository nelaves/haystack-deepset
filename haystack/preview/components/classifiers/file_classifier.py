import logging
import mimetypes
import re
from collections import defaultdict
from pathlib import Path
from typing import List, Union, Optional

from haystack.preview import component

logger = logging.getLogger(__name__)


@component
class FileTypeClassifier:
    """
    A component that classifies files based on their MIME types.

    The FileTypeClassifier takes a list of file paths and groups them by their MIME types.
    The list of MIME types to consider is provided during the initialization of the component.

    This component is particularly useful when working with a large number of files, and you
    want to categorize them based on their MIME types.
    """

    def __init__(self, mime_types: List[str]):
        """
        Initialize the FileTypeClassifier.

        :param mime_types: A list of file mime types to consider when classifying
        files (e.g. ["text/plain", "audio/x-wav", "image/jpeg"]).
        """
        if not mime_types:
            raise ValueError("The list of mime types cannot be empty.")

        all_known_mime_types = all(self.is_known_mime_type(mime_type) for mime_type in mime_types)
        if not all_known_mime_types:
            raise ValueError(f"The list of mime types contains unknown mime types: {mime_types}")

        # convert the mime types to the underscore format (e.g. text_plain)
        # otherwise we'll have issues with the dataclass field name convention
        # in the output dataclass
        mime_types = [self.to_underscore_format(mime_type) for mime_type in mime_types]
        # add the "unclassified" mime type to the list of mime types
        mime_types.append("unclassified")

        component.set_output_types(self, **{mime_type: List[Path] for mime_type in mime_types})
        self.mime_types = mime_types

    def run(self, paths: List[Union[str, Path]]):
        """
        Run the FileTypeClassifier.

        This method takes the input data, iterates through the provided file paths, checks the file
        mime type of each file, and groups the file paths by their mime types.

        :param paths: The input data containing the file paths to classify.
        :return: The output data containing the classified file paths.
        """
        mime_types = defaultdict(list)
        for path in paths:
            if isinstance(path, str):
                path = Path(path)
            mime_type = self.to_underscore_format(self.get_mime_type(path))
            if mime_type in self.mime_types:
                mime_types[mime_type].append(path)
            else:
                mime_types["unclassified"].append(path)

        return mime_types

    def get_mime_type(self, path: Path) -> Optional[str]:
        """
        Get the MIME type of the provided file path.

        :param path: The file path to get the MIME type for.
        :return: The MIME type of the provided file path, or None if the MIME type cannot be determined.
        """
        return mimetypes.guess_type(path.as_posix())[0]

    def to_underscore_format(self, mime_type: Optional[str]) -> str:
        """
        Convert the provided MIME type to underscore format.
        :param mime_type: The MIME type to convert.
        :return: The converted MIME type or an empty string if the provided MIME type is None.
        """
        if mime_type:
            return "".join(c if c.isalnum() else "_" for c in mime_type)
        return ""

    def is_known_mime_type(self, mime_type: str) -> bool:
        """
        Check if the provided MIME type is a known MIME type.
        :param mime_type: The MIME type to check.
        :return: True if the provided MIME type is a known MIME type, False otherwise.
        """
        # this mimetypes check fails on Windows, therefore we use a regex instead
        # return mime_type in mimetypes.types_map.values() or mime_type in mimetypes.common_types.values()
        return bool(re.match(r"^.+/[^/]+$", mime_type))
