import logging
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from multiprocessing import cpu_count
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import requests
from more_itertools import divide

from haystack.nodes.file_converter.base import BaseConverter
from haystack.schema import Document

logger = logging.getLogger(__name__)

fitz_installed = False
try:
    import fitz

    fitz_installed = True
except ImportError:
    logger.warning(
        """
        If PyMuPDF is not installed, please install it via `pip install PyMuPDF` or `pip install farm-haystack[pdf]`.
        PyMuPDF provides improved performance when converting PDF files.
        """
    )


class PDFToTextConverter(BaseConverter):
    def __init__(
        self,
        remove_numeric_tables: bool = False,
        valid_languages: Optional[List[str]] = None,
        id_hash_keys: Optional[List[str]] = None,
        encoding: Optional[str] = None,
        keep_physical_layout: Optional[bool] = None,
        multiprocessing: Optional[Union[bool, int]] = None,
    ):
        """
        :param remove_numeric_tables: This option uses heuristics to remove numeric rows from the tables.
                                      The tabular structures in documents might be noise for the reader model if it
                                      does not have table parsing capability for finding answers. However, tables
                                      may also have long strings that could possible candidate for searching answers.
                                      The rows containing strings are thus retained in this option.
        :param valid_languages: validate languages from a list of languages specified in the ISO 639-1
                                (https://en.wikipedia.org/wiki/ISO_639-1) format.
                                This option can be used to add test for encoding errors. If the extracted text is
                                not one of the valid languages, then it might likely be encoding error resulting
                                in garbled text.
        :param id_hash_keys: Generate the document id from a custom list of strings that refer to the document's
            attributes. If you want to ensure you don't have duplicate documents in your DocumentStore but texts are
            not unique, you can modify the metadata and pass e.g. `"meta"` to this field (e.g. [`"content"`, `"meta"`]).
            In this case the id will be generated by using the content and the defined metadata.
        :param encoding: Encoding that will be passed as `-enc` parameter to `pdftotext`, if keep_physical_layout is enabled.
                         Defaults to "UTF-8" in order to support special characters (e.g. German Umlauts, Cyrillic ...).
                         (See list of available encodings, such as "Latin1", by running `pdftotext -listenc` in the terminal)
        :param keep_physical_layout: This option will maintain original physical layout on the extracted text.
            It works by passing the `-layout` parameter to `pdftotext`. When disabled, PDF is read in the stream order.
        :param multiprocessing: Whether to use multiprocessing to speed up the conversion. If set to True, the total number of cores will be used.
                                If set to an integer, that number of cores will be used.
        """
        super().__init__(
            remove_numeric_tables=remove_numeric_tables, valid_languages=valid_languages, id_hash_keys=id_hash_keys
        )

        if self._check_xpdf() is False and fitz_installed is False:
            self._download_xpdf()

        self.encoding = encoding
        self.keep_physical_layout = keep_physical_layout
        self.multi_processing = multiprocessing

    def _check_xpdf(self) -> bool:
        self._temp_path = str(Path(tempfile.gettempdir()) / "haystack" / "xpdf")
        if not self._temp_path in os.environ["PATH"]:
            os.environ["PATH"] += os.pathsep + str(self._temp_path)

        try:
            res_text = subprocess.run(["pdftotext", "-v"], capture_output=True, text=True)
            res_info = subprocess.run(["pdfinfo", "-v"], capture_output=True, text=True)
            # There are some shells where the pdftotext version output is printed to stderr
            if (res_text.stdout.startswith("pdftotext") or res_text.stderr.startswith("pdftotext")) and (
                res_info.stdout.startswith("pdfinfo") or res_info.stderr.startswith("pdfinfo")
            ):
                return True
        except FileNotFoundError:
            logger.warning(
                """pdftotext and pdfinfo are not installed. They are part of Xpdf command line tools.
                   Installation on Linux:
                   wget --no-check-certificate https://dl.xpdfreader.com/xpdf-tools-linux-4.04.tar.gz &&
                   tar -xvf xpdf-tools-linux-4.04.tar.gz && sudo cp xpdf-tools-linux-4.04/bin64/pdftotext /usr/local/bin
                   Installation on MacOS:
                   brew install xpdf
                   You can find more details here: https://www.xpdfreader.com
                """
            )
        return False

    def _download_xpdf(self):
        def used_files(members, system, arch):
            for tarinfo in members:
                if (
                    tarinfo.name == f"xpdf-tools-{system}-4.04/bin{arch}/pdftotext"
                    or tarinfo.name == f"xpdf-tools-{system}-4.04/bin{arch}/pdfinfo"
                ):
                    yield tarinfo

        logger.debug("Trying to download xpdf from https://dl.xpdfreader.com/")

        system = platform.system().lower()

        if system == "linux" or system == "darwin" or system == "windows":
            os_tag = "linux" if system == "linux" else "win" if system == "windows" else "mac"
            os_arch = "64" if platform.machine().endswith("64") else "64" if system == "mac" else "32"

            temp_dir = Path(self._temp_path)

            if os.path.exists(temp_dir / "pdftotext") and os.path.exists(temp_dir / "pdfinfo"):
                return

            try:
                download_file = f"xpdf-tools-{os_tag}-4.04.{'tar.gz' if system != 'windows' else 'zip'}"
                response = requests.get(f"https://dl.xpdfreader.com/{download_file}")
                response.raise_for_status()
                temp_dir.mkdir(parents=True, exist_ok=True)
                temp_tar = temp_dir / download_file
                with open(temp_tar, "wb") as f:
                    f.write(response.content)

                tar = tarfile.open(temp_tar)

                tar.extractall(temp_dir, members=used_files(tar, system, os_arch))
                tar.close()

                os.unlink(temp_tar)
                shutil.copy(temp_dir / f"xpdf-tools-linux-4.04/bin{os_arch}/pdftotext", temp_dir / "pdftotext")
                shutil.copy(temp_dir / f"xpdf-tools-linux-4.04/bin{os_arch}/pdfinfo", temp_dir / "pdfinfo")
                shutil.rmtree(temp_dir / "xpdf-tools-linux-4.04/")

                if self._check_xpdf() is False:
                    raise ValueError(
                        """pdftotext automatic download is corrupted. Please install it manually.
                        Installation on Linux:
                        wget --no-check-certificate https://dl.xpdfreader.com/xpdf-tools-linux-4.04.tar.gz &&
                        tar -xvf xpdf-tools-linux-4.04.tar.gz && sudo cp xpdf-tools-linux-4.04/bin64/pdftotext /usr/local/bin
                        Installation on MacOS:
                        brew install xpdf
                        You can find more details here: https://www.xpdfreader.com
                        """
                    )

                return True

            except:
                raise ValueError(
                    """pdftotext automatic download failed. It is part of xpdf or poppler-utils software suite.
                    You need to install it to use keep_physical_layout.
                    Installation on Linux:
                    wget --no-check-certificate https://dl.xpdfreader.com/xpdf-tools-linux-4.04.tar.gz &&
                    tar -xvf xpdf-tools-linux-4.04.tar.gz && sudo cp xpdf-tools-linux-4.04/bin64/pdftotext /usr/local/bin
                    Installation on MacOS:
                    brew install xpdf
                    You can find more details here: https://www.xpdfreader.com
                    """
                )

        return False

    def convert(
        self,
        file_path: Path,
        meta: Optional[Dict[str, Any]] = None,
        remove_numeric_tables: Optional[bool] = None,
        valid_languages: Optional[List[str]] = None,
        encoding: Optional[str] = None,
        keep_physical_layout: Optional[bool] = None,
        id_hash_keys: Optional[List[str]] = None,
        start_page: Optional[int] = None,
        end_page: Optional[int] = None,
        multiprocessing: Optional[Union[bool, int]] = None,
    ) -> List[Document]:
        """
        Extract text from a .pdf file using the pdftotext library (https://www.xpdfreader.com/pdftotext-man.html)

        :param file_path: Path to the .pdf file you want to convert
        :param meta: Optional dictionary with metadata that shall be attached to all resulting documents.
                     Can be any custom keys and values.
        :param remove_numeric_tables: This option uses heuristics to remove numeric rows from the tables.
                                      The tabular structures in documents might be noise for the reader model if it
                                      does not have table parsing capability for finding answers. However, tables
                                      may also have long strings that could possible candidate for searching answers.
                                      The rows containing strings are thus retained in this option.
        :param valid_languages: validate languages from a list of languages specified in the ISO 639-1
                                (https://en.wikipedia.org/wiki/ISO_639-1) format.
                                This option can be used to add test for encoding errors. If the extracted text is
                                not one of the valid languages, then it might likely be encoding error resulting
                                in garbled text.
        :param encoding: Encoding that will be passed as `-enc` parameter to `pdftotext`.
                         Defaults to "UTF-8" in order to support special characters (e.g. German Umlauts, Cyrillic ...).
                         (See list of available encodings, such as "Latin1", by running `pdftotext -listenc` in the terminal)
        :param keep_physical_layout: This option will maintain original physical layout on the extracted text.
            It works by passing the `-layout` parameter to `pdftotext`. When disabled, PDF is read in the stream order.
        :param id_hash_keys: Generate the document id from a custom list of strings that refer to the document's
            attributes. If you want to ensure you don't have duplicate documents in your DocumentStore but texts are
            not unique, you can modify the metadata and pass e.g. `"meta"` to this field (e.g. [`"content"`, `"meta"`]).
            In this case the id will be generated by using the content and the defined metadata.
        :param start_page: The page number where to start the conversion
        :param end_page: The page number where to end the conversion.
        :param multiprocessing: Whether to use multiprocessing to speed up the conversion. If set to True, the total number of cores will be used.
                                If set to an integer, that number of cores will be used.
        """
        if remove_numeric_tables is None:
            remove_numeric_tables = self.remove_numeric_tables
        if valid_languages is None:
            valid_languages = self.valid_languages
        if id_hash_keys is None:
            id_hash_keys = self.id_hash_keys
        if encoding is None:
            encoding = self.encoding
        if multiprocessing is None:
            multiprocessing = self.multi_processing
        if keep_physical_layout is None:
            keep_physical_layout = self.keep_physical_layout

        if self._check_xpdf() is False and keep_physical_layout:
            self._download_xpdf()

        pages = self._read_pdf(
            file_path,
            layout=keep_physical_layout,
            start_page=start_page,
            end_page=end_page,
            encoding=encoding,
            multiprocessing=multiprocessing,
        )

        cleaned_pages = []
        for page in pages:
            lines = page.splitlines()
            cleaned_lines = []
            for line in lines:
                words = line.split()
                digits = [word for word in words if any(i.isdigit() for i in word)]

                # remove lines having > 40% of words as digits AND not ending with a period(.)
                if remove_numeric_tables:
                    if words and len(digits) / len(words) > 0.4 and not line.strip().endswith("."):
                        logger.debug("Removing line '%s' from %s", line, file_path)
                        continue
                cleaned_lines.append(line)

            page = "\n".join(cleaned_lines)
            cleaned_pages.append(page)

        if valid_languages:
            document_text = "".join(cleaned_pages)
            if not self.validate_language(document_text, valid_languages):
                logger.warning(
                    "The language for %s is not one of %s. The file may not have "
                    "been decoded in the correct text format.",
                    file_path,
                    valid_languages,
                )

        text = "\f".join(cleaned_pages)
        document = Document(content=text, meta=meta, id_hash_keys=id_hash_keys)
        return [document]

    def _get_text_parallel(self, page_mp):
        idx, cpu, filename, start, end, layout = page_mp

        doc = fitz.open(filename)

        parts = divide(cpu, [i for i in range(start, end)])

        text = ""
        for i in parts[idx]:
            page = doc[i]
            text += page.get_text("text", sort=layout) + "\f"

        return text

    def _get_text_parallel_xpdf(self, page_mp):
        idx, cpu, filename, parts, encoding, layout = page_mp

        segments = list(parts[idx])

        command = [
            "pdftotext",
            "-enc",
            str(encoding),
            "-layout" if layout else "-raw",
            "-f",
            str(min(segments)),
            "-l",
            str(max(segments)),
            str(filename),
            "-",
        ]

        output = subprocess.run(command, stdout=subprocess.PIPE, shell=False, check=False)
        document = output.stdout.decode(errors="ignore")

        return document

    def _get_page_count_xpdf(self, file_path: Path) -> int:
        command = ["pdfinfo", str(file_path)]
        output = subprocess.run(command, capture_output=True, text=True, shell=False, check=False)
        if output.returncode == 0:
            for line in output.stdout.splitlines():
                if line.startswith("Pages:"):
                    return int(line.split(":")[1].strip())

        return 0

    def _read_pdf(
        self,
        file_path: Path,
        layout: Optional[bool] = None,
        start_page: Optional[int] = None,
        end_page: Optional[int] = None,
        encoding: Optional[str] = None,
        multiprocessing: Optional[Union[bool, int]] = None,
    ) -> List[str]:
        """
        Extract pages from the pdf file at file_path.

        :param file_path: path of the pdf file
        :param layout: whether to retain the original physical layout for a page. If disabled, PDF pages are read in
                       the content stream order.
        :param start_page: The page number where to start the conversion, starting from 1.
        :param end_page: The page number where to end the conversion.
        :param encoding: Encoding that will be passed as `-enc` parameter to `pdftotext`.
                         Defaults to "UTF-8" in order to support special characters (e.g. German Umlauts, Cyrillic ...).
                         (See list of available encodings, such as "Latin1", by running `pdftotext -listenc` in the terminal)

        :param multiprocessing: Whether to use multiprocessing to speed up the conversion. If set to True, the total number of cores will be used.
                                If set to an integer, that number of cores will be used.
        """

        if not encoding:
            encoding = self.encoding

        if multiprocessing is None:
            multiprocessing = self.multi_processing

        if encoding is None:
            encoding = "UTF-8"

        if fitz_installed:
            doc = fitz.open(file_path)

            if start_page is None:
                start_page = 0
            else:
                start_page = start_page - 1

            page_count = int(doc.page_count)

            if end_page is None or (end_page is not None and end_page > page_count):
                end_page = page_count

            document = ""

            if multiprocessing is not None and (
                (isinstance(multiprocessing, bool) and multiprocessing)
                or (isinstance(multiprocessing, int) and multiprocessing > 1)
            ):
                cpu = cpu_count() if isinstance(multiprocessing, bool) else multiprocessing
                pages_mp = [(i, cpu, file_path, start_page, end_page, layout) for i in range(cpu)]

                with ProcessPoolExecutor(max_workers=cpu) as pool:
                    results = pool.map(self._get_text_parallel, pages_mp)
                    for page in results:
                        document += page
            else:
                for i in range(start_page, end_page):
                    page = doc[i]
                    document += page.get_text("text", sort=layout) + "\f"

        else:
            start_page = start_page or 1

            if end_page is None:
                end_page = self._get_page_count_xpdf(file_path)

            document = ""
            if multiprocessing is not None and (
                (isinstance(multiprocessing, bool) and multiprocessing)
                or (isinstance(multiprocessing, int) and multiprocessing > 1)
            ):
                cpu = cpu_count() if isinstance(multiprocessing, bool) else multiprocessing
                parts = divide(cpu, [i for i in range(start_page, end_page + 1)])
                pages_mp = [(i, cpu, file_path, parts, encoding, layout) for i in range(cpu)]

                with ThreadPoolExecutor(max_workers=cpu) as pool:
                    results = pool.map(self._get_text_parallel_xpdf, pages_mp)
                    for page in results:
                        document += page
            else:
                command = ["pdftotext", "-enc", str(encoding), "-layout" if layout else "-raw", "-f", str(start_page)]

                if end_page is not None:
                    command.extend(["-l", str(end_page)])

                command.extend([str(file_path), "-"])

                output = subprocess.run(command, stdout=subprocess.PIPE, shell=False, check=False)
                document = output.stdout.decode(errors="ignore")

        document = (
            "\f" * (start_page - 1 if not fitz_installed else start_page) + document
        )  # tracking skipped pages for correct page numbering
        pages = document.split("\f")
        pages = pages[:-1]  # the last page in the split is always empty.

        return pages
