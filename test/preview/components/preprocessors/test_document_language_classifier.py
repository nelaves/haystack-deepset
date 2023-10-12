import logging
import pytest

from haystack.preview import Document
from haystack.preview.components.preprocessors import DocumentLanguageClassifier


class TestDocumentLanguageClassifier:
    @pytest.mark.unit
    def test_to_dict(self):
        component = DocumentLanguageClassifier(languages=["en", "de"])
        data = component.to_dict()
        assert data == {"type": "DocumentLanguageClassifier", "init_parameters": {"languages": ["en", "de"]}}

    @pytest.mark.unit
    def test_from_dict(self):
        data = {"type": "DocumentLanguageClassifier", "init_parameters": {"languages": ["en", "de"]}}
        component = DocumentLanguageClassifier.from_dict(data)
        assert component.languages == ["en", "de"]

    @pytest.mark.unit
    def test_non_document_input(self):
        with pytest.raises(TypeError, match="DocumentLanguageClassifier expects a list of Document as input."):
            classifier = DocumentLanguageClassifier()
            classifier.run(documents="This is an english sentence.")

    @pytest.mark.unit
    def test_single_document(self):
        with pytest.raises(TypeError, match="DocumentLanguageClassifier expects a list of Document as input."):
            classifier = DocumentLanguageClassifier()
            classifier.run(documents=Document(text="This is an english sentence."))

    @pytest.mark.unit
    def test_empty_list(self):
        classifier = DocumentLanguageClassifier()
        result = classifier.run(documents=[])
        assert result == {"en": [], "unmatched": []}

    @pytest.mark.unit
    def test_detect_language(self):
        classifier = DocumentLanguageClassifier()
        detected_language = classifier.detect_language(Document(text="This is an english sentence."))
        assert detected_language == "en"

    @pytest.mark.unit
    def test_route_to_en_and_unmatched(self):
        classifier = DocumentLanguageClassifier()
        english_document = Document(text="This is an english sentence.")
        german_document = Document(text="Ein deutscher Satz ohne Verb.")
        result = classifier.run(documents=[english_document, german_document])
        assert result == {"en": [english_document], "unmatched": [german_document]}

    @pytest.mark.unit
    def test_warning_if_no_language_detected(self, caplog):
        with caplog.at_level(logging.WARNING):
            classifier = DocumentLanguageClassifier()
            classifier.run(documents=[Document(text=".")])
            assert "Langdetect cannot detect the language of Document with id" in caplog.text
