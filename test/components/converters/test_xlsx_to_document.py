import logging
from typing import Union

import pytest

from haystack.components.converters.xlsx import XLSXToDocument


class TestXLSXToDocument:
    def test_init(self) -> None:
        converter = XLSXToDocument()
        assert converter.sheet_name is None
        assert converter.read_excel_kwargs == {}
        assert converter.table_format == "csv"
        assert converter.table_format_kwargs == {}

    def test_run(self, test_files_path) -> None:
        converter = XLSXToDocument()
        paths = [test_files_path / "xlsx" / "test.xlsx"]
        results = converter.run(sources=paths, meta={"date_added": "2022-01-01T00:00:00"})
        documents = results["documents"]
        assert len(documents) == 2
        assert documents[0].content == ",A,B\n1,col_a,col_b\n2,1.5,test\n"
        assert documents[0].meta == {
            "date_added": "2022-01-01T00:00:00",
            "file_path": str(test_files_path / "xlsx" / "test.xlsx"),
            "xlsx": {"sheet_name": "Sheet1"},
        }
        assert documents[1].content == ",A,B\n1,col_c,col_d\n2,True,\n"
        assert documents[1].meta == {
            "date_added": "2022-01-01T00:00:00",
            "file_path": str(test_files_path / "xlsx" / "test.xlsx"),
            "xlsx": {"sheet_name": "Sheet2"},
        }

    @pytest.mark.parametrize(
        "sheet_name, expected_sheet_name, expected_content",
        [
            ("Sheet1", "Sheet1", ",A,B\n1,col_a,col_b\n2,1.5,test\n"),
            ("Sheet2", "Sheet2", ",A,B\n1,col_c,col_d\n2,True,\n"),
            (0, 0, ",A,B\n1,col_a,col_b\n2,1.5,test\n"),
            (1, 1, ",A,B\n1,col_c,col_d\n2,True,\n"),
        ],
    )
    def test_run_sheet_name(
        self, sheet_name: Union[int, str], expected_sheet_name: str, expected_content: str, test_files_path
    ) -> None:
        converter = XLSXToDocument(sheet_name=sheet_name)
        paths = [test_files_path / "xlsx" / "test.xlsx"]
        results = converter.run(sources=paths)
        documents = results["documents"]
        assert len(documents) == 1
        assert documents[0].content == expected_content
        assert documents[0].meta == {
            "file_path": str(test_files_path / "xlsx" / "test.xlsx"),
            "xlsx": {"sheet_name": expected_sheet_name},
        }

    def test_run_with_read_excel_kwargs(self, test_files_path) -> None:
        converter = XLSXToDocument(sheet_name="Sheet1", read_excel_kwargs={"skiprows": 1})
        paths = [test_files_path / "xlsx" / "test.xlsx"]
        results = converter.run(sources=paths, meta={"date_added": "2022-01-01T00:00:00"})
        documents = results["documents"]
        assert len(documents) == 1
        assert documents[0].content == ",A,B\n1,1.5,test\n"
        assert documents[0].meta == {
            "date_added": "2022-01-01T00:00:00",
            "file_path": str(test_files_path / "xlsx" / "test.xlsx"),
            "xlsx": {"sheet_name": "Sheet1"},
        }

    def test_run_error_wrong_file_type(self, caplog: pytest.LogCaptureFixture, test_files_path) -> None:
        converter = XLSXToDocument()
        sources = [test_files_path / "pdf" / "sample_pdf_1.pdf"]
        with caplog.at_level(logging.WARNING):
            results = converter.run(sources=sources)
            assert "sample_pdf_1.pdf and convert it" in caplog.text
            assert results["documents"] == []

    def test_run_error_non_existent_file(self, caplog: pytest.LogCaptureFixture) -> None:
        converter = XLSXToDocument()
        paths = ["non_existing_file.docx"]
        with caplog.at_level(logging.WARNING):
            converter.run(sources=paths)
            assert "Could not read non_existing_file.docx" in caplog.text
