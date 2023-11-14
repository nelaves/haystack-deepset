import logging

import pytest

from haystack.preview.components.file_converters import HTMLToDocument
from haystack.preview.dataclasses import ByteStream


class TestHTMLToDocument:
    @pytest.mark.unit
    def test_init_params_default(self):
        """Test if the component sets default initialization parameters correctly."""
        converter = HTMLToDocument()
        assert converter.progress_bar is True

    @pytest.mark.unit
    def test_init_params_custom(self):
        """Test if the component sets custom initialization parameters correctly."""
        converter = HTMLToDocument(progress_bar=False)
        assert converter.progress_bar is False

    @pytest.mark.integration
    def test_run(self, preview_samples_path):
        """
        Test if the component runs correctly.
        """
        sources = [preview_samples_path / "html" / "what_is_haystack.html"]
        converter = HTMLToDocument()
        output = converter.run(sources=sources)
        docs = output["documents"]
        assert len(docs) == 1
        assert "Haystack" in docs[0].content

    @pytest.mark.integration
    def test_run_doc_metadata(self, preview_samples_path):
        """
        Test if the component runs correctly when metadata is supplied by the user.
        """
        converter = HTMLToDocument()
        sources = [preview_samples_path / "html" / "what_is_haystack.html"]
        metadata = [{"file_name": "what_is_haystack.html"}]
        results = converter.run(sources=sources, meta=metadata)
        docs = results["documents"]

        assert len(docs) == 1
        assert "Haystack" in docs[0].content
        assert docs[0].meta == {"file_name": "what_is_haystack.html"}

    @pytest.mark.integration
    def test_run_bytestream_metadata(self, preview_samples_path):
        """
        Test if the component runs correctly when metadata is read from the ByteStream object.
        """
        converter = HTMLToDocument()
        with open(preview_samples_path / "html" / "what_is_haystack.html", "rb") as file:
            byte_stream = file.read()
            stream = ByteStream(byte_stream, metadata={"content_type": "text/html", "url": "test_url"})

        results = converter.run(sources=[stream])
        docs = results["documents"]

        assert len(docs) == 1
        assert "Haystack" in docs[0].content
        assert docs[0].meta == {"content_type": "text/html", "url": "test_url"}

    @pytest.mark.integration
    def test_run_bytestream_and_doc_metadata(self, preview_samples_path):
        """
        Test if the component runs correctly when metadata is read from the ByteStream object and supplied by the user.

        There is no overlap between the metadata received.
        """
        converter = HTMLToDocument()
        with open(preview_samples_path / "html" / "what_is_haystack.html", "rb") as file:
            byte_stream = file.read()
            stream = ByteStream(byte_stream, metadata={"content_type": "text/html", "url": "test_url"})

        metadata = [{"file_name": "what_is_haystack.html"}]
        results = converter.run(sources=[stream], meta=metadata)
        docs = results["documents"]

        assert len(docs) == 1
        assert "Haystack" in docs[0].content
        assert docs[0].meta == {"file_name": "what_is_haystack.html", "content_type": "text/html", "url": "test_url"}

    @pytest.mark.integration
    def test_run_bytestream_doc_overlapping_metadata(self, preview_samples_path):
        """
        Test if the component runs correctly when metadata is read from the ByteStream object and supplied by the user.

        There is an overlap between the metadata received.

        The component should use the supplied metadata to overwrite the values if there is an overlap between the keys.
        """
        converter = HTMLToDocument()
        with open(preview_samples_path / "html" / "what_is_haystack.html", "rb") as file:
            byte_stream = file.read()
            # ByteStream has "url" present in metadata
            stream = ByteStream(byte_stream, metadata={"content_type": "text/html", "url": "test_url_correct"})

        # "url" supplied by the user overwrites value present in metadata
        metadata = [{"file_name": "what_is_haystack.html", "url": "test_url_new"}]
        results = converter.run(sources=[stream], meta=metadata)
        docs = results["documents"]

        assert len(docs) == 1
        assert "Haystack" in docs[0].content
        assert docs[0].meta == {
            "file_name": "what_is_haystack.html",
            "content_type": "text/html",
            "url": "test_url_new",
        }

    @pytest.mark.integration
    def test_run_wrong_file_type(self, preview_samples_path, caplog):
        """
        Test if the component runs correctly when an input file is not of the expected type.
        """
        sources = [preview_samples_path / "audio" / "answer.wav"]
        converter = HTMLToDocument()
        with caplog.at_level(logging.WARNING):
            output = converter.run(sources=sources)
            assert "codec can't decode byte" in caplog.text

        docs = output["documents"]
        assert not docs

    @pytest.mark.unit
    def test_run_error_handling(self, caplog):
        """
        Test if the component correctly handles errors.
        """
        sources = ["non_existing_file.html"]
        converter = HTMLToDocument()
        with caplog.at_level(logging.WARNING):
            result = converter.run(sources=sources)
            assert "Could not read non_existing_file.html" in caplog.text
            assert not result["documents"]

    @pytest.mark.unit
    def test_mixed_sources_run(self, preview_samples_path):
        """
        Test if the component runs correctly if the input is a mix of paths and ByteStreams.
        """
        sources = [
            preview_samples_path / "html" / "what_is_haystack.html",
            str((preview_samples_path / "html" / "what_is_haystack.html").absolute()),
        ]
        with open(preview_samples_path / "html" / "what_is_haystack.html", "rb") as f:
            byte_stream = f.read()
            sources.append(ByteStream(byte_stream))

        converter = HTMLToDocument()
        output = converter.run(sources=sources)
        docs = output["documents"]
        assert len(docs) == 3
        for doc in docs:
            assert "Haystack" in doc.content
