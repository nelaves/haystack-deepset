from pathlib import Path
import pytest
import pandas as pd
import numpy as np

from haystack.preview import Document
from haystack.preview.dataclasses.document import _create_id


@pytest.mark.unit
def test_simple_text_document_equality():
    assert Document(content="test content") == Document(content="test content")


@pytest.mark.unit
def test_simple_table_document_equality():
    assert Document(content=pd.DataFrame([1, 2]), content_type="table") == Document(
        content=pd.DataFrame([1, 2]), content_type="table"
    )


@pytest.mark.unit
def test_simple_image_document_equality():
    assert Document(content=Path(__file__).parent / "test_files" / "apple.jpg", content_type="image") == Document(
        content=Path(__file__).parent / "test_files" / "apple.jpg", content_type="image"
    )


@pytest.mark.unit
def test_equality_with_embeddings():
    assert Document(content="test content", embedding=np.array([10, 10])) == Document(
        content="test content", embedding=np.array([10, 10])
    )


@pytest.mark.unit
def test_equality_with_scores():
    assert Document(content="test content", score=100) == Document(content="test content", score=100.0)


@pytest.mark.unit
def test_equality_with_simple_metadata():
    assert Document(content="test content", metadata={"value": 1, "another": "value"}) == Document(
        content="test content", metadata={"value": 1, "another": "value"}
    )


@pytest.mark.unit
def test_equality_with_nested_metadata():
    assert Document(content="test content", metadata={"value": {"another": "value"}}) == Document(
        content="test content", metadata={"value": {"another": "value"}}
    )


@pytest.mark.unit
def test_equality_with_metadata_with_objects():
    assert Document(
        content="test content", metadata={"value": np.array([0, 1, 2]), "path": Path(__file__)}
    ) == Document(content="test content", metadata={"value": np.array([0, 1, 2]), "path": Path(__file__)})


@pytest.mark.unit
def test_default_text_document_to_dict():
    assert Document(content="test content").to_dict() == {
        "id": _create_id(classname=Document.__name__, content="test content"),
        "content": "test content",
        "content_type": "text",
        "metadata": {},
        "id_hash_keys": [],
        "score": None,
        "embedding": None,
    }


@pytest.mark.unit
def test_default_text_document_from_dict():
    assert Document.from_dict(
        {
            "id": _create_id(classname=Document.__name__, content="test content"),
            "content": "test content",
            "content_type": "text",
            "metadata": {},
            "id_hash_keys": [],
            "score": None,
            "embedding": None,
        }
    ) == Document(content="test content")


@pytest.mark.unit
def test_default_table_document_to_dict():
    df = pd.DataFrame([1, 2])
    dictionary = Document(content=df, content_type="table").to_dict()

    dataframe = dictionary.pop("content")
    assert dataframe.equals(df)

    assert dictionary == {
        "id": _create_id(classname=Document.__name__, content=df),
        "content_type": "table",
        "metadata": {},
        "id_hash_keys": [],
        "score": None,
        "embedding": None,
    }


@pytest.mark.unit
def test_default_table_document_from_dict():
    assert Document.from_dict(
        {
            "id": _create_id(classname=Document.__name__, content=pd.DataFrame([1, 2])),
            "content": pd.DataFrame([1, 2]),
            "content_type": "table",
            "metadata": {},
            "id_hash_keys": [],
            "score": None,
            "embedding": None,
        }
    ) == Document(content=pd.DataFrame([1, 2]), content_type="table")


@pytest.mark.unit
def test_default_image_document_to_dict():
    path = Path(__file__).parent / "test_files" / "apple.jpg"
    assert Document(content=path, content_type="image").to_dict() == {
        "id": _create_id(classname=Document.__name__, content=path),
        "content": path,
        "content_type": "image",
        "metadata": {},
        "id_hash_keys": [],
        "score": None,
        "embedding": None,
    }


@pytest.mark.unit
def test_default_image_document_from_dict():
    assert Document.from_dict(
        {
            "id": _create_id(classname=Document.__name__, content=Path(__file__).parent / "test_files" / "apple.jpg"),
            "content": Path(__file__).parent / "test_files" / "apple.jpg",
            "content_type": "image",
            "metadata": {},
            "id_hash_keys": [],
            "score": None,
            "embedding": None,
        }
    ) == Document(content=Path(__file__).parent / "test_files" / "apple.jpg", content_type="image")


@pytest.mark.unit
def test_document_with_most_attributes_to_dict():
    """
    This tests also id_hash_keys
    """
    doc = Document(
        content="test content",
        content_type="text",
        metadata={"some": "values", "test": 10},
        id_hash_keys=["test"],
        score=0.99,
        embedding=np.zeros([10, 10]),
    )
    dictionary = doc.to_dict()

    embedding = dictionary.pop("embedding")
    assert (embedding == np.zeros([10, 10])).all()

    assert dictionary == {
        "id": _create_id(
            classname=Document.__name__,
            content="test content",
            id_hash_keys=["test"],
            metadata={"some": "values", "test": 10},
        ),
        "content": "test content",
        "content_type": "text",
        "metadata": {"some": "values", "test": 10},
        "id_hash_keys": ["test"],
        "score": 0.99,
    }


@pytest.mark.unit
def test_document_with_most_attributes_from_dict():
    embedding = np.zeros([10, 10])
    assert Document.from_dict(
        {
            "id": _create_id(
                classname=Document.__name__,
                content="test content",
                id_hash_keys=["test"],
                metadata={"some": "values", "test": 10},
            ),
            "content": "test content",
            "content_type": "text",
            "metadata": {"some": "values", "test": 10},
            "id_hash_keys": ["test"],
            "score": 0.99,
            "embedding": embedding,
        }
    ) == Document(
        content="test content",
        content_type="text",
        metadata={"some": "values", "test": 10},
        id_hash_keys=["test"],
        score=0.99,
        embedding=embedding,
    )
