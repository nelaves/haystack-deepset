import pytest
import json
import numpy as np
import networkx as nx

import haystack
from haystack import Pipeline
from haystack.nodes import _json_schema
from haystack.nodes import FileTypeClassifier
from haystack.errors import PipelineConfigError

from .conftest import SAMPLES_PATH, MockDocumentStore, MockReader, MockRetriever
from . import conftest


#
# Fixtures
#


@pytest.fixture(autouse=True)
def mock_json_schema(request, monkeypatch, tmp_path):
    """
    JSON schema with the unstable version and only mocked nodes.
    """
    # Do not patch integration tests
    if "integration" in request.keywords:
        return

    # Mock the subclasses list to make it very small, containing only mock nodes
    monkeypatch.setattr(
        haystack.nodes._json_schema,
        "find_subclasses_in_modules",
        lambda *a, **k: [(conftest, MockDocumentStore), (conftest, MockReader), (conftest, MockRetriever)],
    )
    # Point the JSON schema path to tmp_path
    monkeypatch.setattr(haystack.pipelines.config, "JSON_SCHEMAS_PATH", tmp_path)

    # Generate mock schema in tmp_path
    filename = f"haystack-pipeline-unstable.schema.json"
    test_schema = _json_schema.get_json_schema(filename=filename, compatible_versions=["unstable"])

    with open(tmp_path / filename, "w") as schema_file:
        json.dump(test_schema, schema_file, indent=4)


#
# Integration
#


@pytest.mark.integration
@pytest.mark.elasticsearch
def test_load_and_save_from_yaml(tmp_path):
    config_path = SAMPLES_PATH / "pipeline" / "test_pipeline.yaml"

    # Test the indexing pipeline:
    # Load it
    indexing_pipeline = Pipeline.load_from_yaml(path=config_path, pipeline_name="indexing_pipeline")

    # Check if it works
    indexing_pipeline.get_document_store().delete_documents()
    assert indexing_pipeline.get_document_store().get_document_count() == 0
    indexing_pipeline.run(file_paths=SAMPLES_PATH / "pdf" / "sample_pdf_1.pdf")
    assert indexing_pipeline.get_document_store().get_document_count() > 0

    # Save it
    new_indexing_config = tmp_path / "test_indexing.yaml"
    indexing_pipeline.save_to_yaml(new_indexing_config)

    # Re-load it and compare the resulting pipelines
    new_indexing_pipeline = Pipeline.load_from_yaml(path=new_indexing_config)
    assert nx.is_isomorphic(new_indexing_pipeline.graph, indexing_pipeline.graph)

    # Check that modifying a pipeline modifies the output YAML
    modified_indexing_pipeline = Pipeline.load_from_yaml(path=new_indexing_config)
    modified_indexing_pipeline.add_node(FileTypeClassifier(), name="file_classifier", inputs=["File"])
    assert not nx.is_isomorphic(new_indexing_pipeline.graph, modified_indexing_pipeline.graph)

    # Test the query pipeline:
    # Load it
    query_pipeline = Pipeline.load_from_yaml(path=config_path, pipeline_name="query_pipeline")

    # Check if it works
    prediction = query_pipeline.run(
        query="Who made the PDF specification?", params={"ESRetriever": {"top_k": 10}, "Reader": {"top_k": 3}}
    )
    assert prediction["query"] == "Who made the PDF specification?"
    assert prediction["answers"][0].answer == "Adobe Systems"
    assert "_debug" not in prediction.keys()

    # Save it
    new_query_config = tmp_path / "test_query.yaml"
    query_pipeline.save_to_yaml(new_query_config)

    # Re-load it and compare the resulting pipelines
    new_query_pipeline = Pipeline.load_from_yaml(path=new_query_config)
    assert nx.is_isomorphic(new_query_pipeline.graph, query_pipeline.graph)

    # Check that different pipelines produce different files
    assert not nx.is_isomorphic(new_query_pipeline.graph, new_indexing_pipeline.graph)


#
# Unit
#


def test_load_yaml(tmp_path):
    with open(tmp_path / "tmp_config.yml", "w") as tmp_file:
        tmp_file.write(
            f"""
            version: unstable
            components:
            - name: retriever
              type: MockRetriever
            - name: reader
              type: MockReader
            pipelines:
            - name: query
              nodes:
              - name: retriever
                inputs:
                - Query
              - name: reader
                inputs:
                - retriever
        """
        )
    pipeline = Pipeline.load_from_yaml(path=tmp_path / "tmp_config.yml")
    assert len(pipeline.graph.nodes) == 3
    assert isinstance(pipeline.get_node("retriever"), MockRetriever)
    assert isinstance(pipeline.get_node("reader"), MockReader)


def test_load_yaml_non_existing_file():
    with pytest.raises(FileNotFoundError):
        Pipeline.load_from_yaml(path=SAMPLES_PATH / "pipeline" / "I_dont_exist.yml")


def test_load_yaml_invalid_yaml(tmp_path):
    with open(tmp_path / "tmp_config.yml", "w") as tmp_file:
        tmp_file.write("this is not valid YAML!")
    with pytest.raises(PipelineConfigError):
        Pipeline.load_from_yaml(path=tmp_path / "tmp_config.yml")


def test_load_yaml_missing_version(tmp_path):
    with open(tmp_path / "tmp_config.yml", "w") as tmp_file:
        tmp_file.write(
            """
            components:
            - name: docstore
              type: MockDocumentStore
            pipelines:
            - name: my_pipeline
              nodes:
              - name: docstore
                inputs:
                - Query
        """
        )
    with pytest.raises(PipelineConfigError) as e:
        Pipeline.load_from_yaml(path=tmp_path / "tmp_config.yml")
        assert "version" in str(e)


def test_load_yaml_non_existing_version(tmp_path):
    with open(tmp_path / "tmp_config.yml", "w") as tmp_file:
        tmp_file.write(
            """
            version: random
            components:
            - name: docstore
              type: MockDocumentStore
            pipelines:
            - name: my_pipeline
              nodes:
              - name: docstore
                inputs:
                - Query
        """
        )
    with pytest.raises(PipelineConfigError) as e:
        Pipeline.load_from_yaml(path=tmp_path / "tmp_config.yml")
        assert "version" in str(e) and "random" in str(e)


def test_load_yaml_incompatible_version(tmp_path):
    with open(tmp_path / "tmp_config.yml", "w") as tmp_file:
        tmp_file.write(
            """
            version: 1.1.0
            components:
            - name: docstore
              type: MockDocumentStore
            pipelines:
            - name: my_pipeline
              nodes:
              - name: docstore
                inputs:
                - Query
        """
        )
    with pytest.raises(PipelineConfigError) as e:
        Pipeline.load_from_yaml(path=tmp_path / "tmp_config.yml")
        assert "version" in str(e) and "1.1.0" in str(e)


def test_load_yaml_no_components(tmp_path):
    with open(tmp_path / "tmp_config.yml", "w") as tmp_file:
        tmp_file.write(
            f"""
            version: unstable
            components:
            pipelines:
            - name: my_pipeline
              nodes:
        """
        )
    with pytest.raises(PipelineConfigError) as e:
        Pipeline.load_from_yaml(path=tmp_path / "tmp_config.yml")
        assert "components" in str(e)


def test_load_yaml_wrong_component(tmp_path):
    with open(tmp_path / "tmp_config.yml", "w") as tmp_file:
        tmp_file.write(
            f"""
            version: unstable
            components:
            - name: docstore
              type: ImaginaryDocumentStore
            pipelines:
            - name: my_pipeline
              nodes:
              - name: docstore
                inputs:
                - Query
        """
        )
    with pytest.raises(PipelineConfigError) as e:
        Pipeline.load_from_yaml(path=tmp_path / "tmp_config.yml")
        assert "ImaginaryDocumentStore" in str(e)


def test_load_yaml_custom_component(tmp_path):

    class CustomDocumentStore(MockDocumentStore):
         def __init__(self, param: int):
             self.param = param

    with open(tmp_path / "tmp_config.yml", "w") as tmp_file:
        tmp_file.write(
            f"""
            version: unstable
            components:
            - name: docstore
              type: CustomDocumentStore
              params:
                param: 1
            pipelines:
            - name: my_pipeline
              nodes:
              - name: docstore
                inputs:
                - Query
        """)
    Pipeline.load_from_yaml(path=tmp_path / "tmp_config.yml")


@pytest.mark.skip("TO BE DISCUSSED")
def test_load_yaml_custom_component_with_helper_class(tmp_path):
    """
    This test can work from the perspective of YAML schema validation. 
    HelperClass is picked up correctly and everything gets loaded.
    
    However, the class creation does not pass the "dumb" string validation
    step due to the parenthesis. 
    
    To be decided what we want to do in this case.
    """
    class HelperClass:
        def __init__(self, another_param: str):
            self.param = another_param
          
    class CustomDocumentStore(MockDocumentStore):
         def __init__(self, some_exotic_parameter: HelperClass):
             self.param = some_exotic_parameter

    with open(tmp_path / "tmp_config.yml", "w") as tmp_file:
        tmp_file.write(
            f"""
            version: unstable
            components:
            - name: docstore
              type: CustomDocumentStore
              params:
                some_exotic_parameter: HelperClass("hello")
            pipelines:
            - name: my_pipeline
              nodes:
              - name: docstore
                inputs:
                - Query
        """)
        Pipeline.load_from_yaml(path=tmp_path / "tmp_config.yml")


def test_load_yaml_no_pipelines(tmp_path):
    with open(tmp_path / "tmp_config.yml", "w") as tmp_file:
        tmp_file.write(
            f"""
            version: unstable
            components:
            - name: docstore
              type: MockDocumentStore
            pipelines:
        """
        )
    with pytest.raises(PipelineConfigError) as e:
        Pipeline.load_from_yaml(path=tmp_path / "tmp_config.yml")
        assert "pipeline" in str(e)


def test_load_yaml_invalid_pipeline_name(tmp_path):
    with open(tmp_path / "tmp_config.yml", "w") as tmp_file:
        tmp_file.write(
            f"""
            version: unstable
            components:
            - name: docstore
              type: MockDocumentStore
            pipelines:
            - name: my_pipeline
              nodes:
              - name: docstore
                inputs:
                - Query
        """
        )
    with pytest.raises(PipelineConfigError) as e:
        Pipeline.load_from_yaml(path=tmp_path / "tmp_config.yml", pipeline_name="invalid")
        assert "invalid" in str(e) and "pipeline" in str(e)


def test_load_yaml_pipeline_with_wrong_nodes(tmp_path):
    with open(tmp_path / "tmp_config.yml", "w") as tmp_file:
        tmp_file.write(
            f"""
            version: unstable
            components:
            - name: docstore
              type: MockDocumentStore
            pipelines:
            - name: my_pipeline
              nodes:
              - name: not_existing_node
                inputs:
                - Query
        """
        )
    with pytest.raises(PipelineConfigError) as e:
        Pipeline.load_from_yaml(path=tmp_path / "tmp_config.yml")
        assert "not_existing_node" in str(e)


def test_load_yaml_pipeline_not_acyclic_graph(tmp_path):
    with open(tmp_path / "tmp_config.yml", "w") as tmp_file:
        tmp_file.write(
            f"""
            version: unstable
            components:
            - name: retriever
              type: MockRetriever
            - name: reader
              type: MockRetriever
            pipelines:
            - name: my_pipeline
              nodes:
              - name: retriever
                inputs:
                - reader
              - name: reader
                inputs:
                - retriever
        """
        )
    with pytest.raises(PipelineConfigError) as e:
        Pipeline.load_from_yaml(path=tmp_path / "tmp_config.yml")
        assert "reader" in str(e) or "retriever" in str(e)
        assert "loop" in str(e)


def test_load_yaml_wrong_root(tmp_path):
    with open(tmp_path / "tmp_config.yml", "w") as tmp_file:
        tmp_file.write(
            f"""
            version: unstable
            components:
            - name: retriever
              type: MockRetriever
            pipelines:
            - name: my_pipeline
              nodes:
              - name: retriever
                inputs:
                - Nothing
        """
        )
    with pytest.raises(PipelineConfigError) as e:
        Pipeline.load_from_yaml(path=tmp_path / "tmp_config.yml")
        assert "Nothing" in str(e)
        assert "root" in str(e).lower()


def test_load_yaml_two_roots(tmp_path):
    with open(tmp_path / "tmp_config.yml", "w") as tmp_file:
        tmp_file.write(
            f"""
            version: unstable
            components:
            - name: retriever
              type: MockRetriever
            - name: retriever_2
              type: MockRetriever
            pipelines:
            - name: my_pipeline
              nodes:
              - name: retriever
                inputs:
                - Query
              - name: retriever_2
                inputs:
                - File
        """
        )
    with pytest.raises(PipelineConfigError) as e:
        Pipeline.load_from_yaml(path=tmp_path / "tmp_config.yml")
        assert "File" in str(e) or "Query" in str(e)


def test_load_yaml_disconnected_component(tmp_path):
    with open(tmp_path / "tmp_config.yml", "w") as tmp_file:
        tmp_file.write(
            f"""
            version: unstable
            components:
            - name: docstore
              type: MockDocumentStore
            - name: retriever
              type: MockRetriever
            pipelines:
            - name: query
              nodes:
              - name: docstore
                inputs:
                - Query
        """
        )
    pipeline = Pipeline.load_from_yaml(path=tmp_path / "tmp_config.yml")
    assert len(pipeline.graph.nodes) == 2
    assert isinstance(pipeline.get_document_store(), MockDocumentStore)
    assert not pipeline.get_node("retriever")


def test_save_yaml(tmp_path):
    pipeline = Pipeline()
    pipeline.add_node(MockRetriever(), name="retriever", inputs=["Query"])
    pipeline.save_to_yaml(tmp_path / "saved_pipeline.yml")

    with open(tmp_path / "saved_pipeline.yml", "r") as saved_yaml:
        content = saved_yaml.read()

        assert content.count("retriever") == 2
        assert "MockRetriever" in content
        assert "Query" in content
        assert f"version: {haystack.__version__}" in content


def test_save_yaml_overwrite(tmp_path):
    pipeline = Pipeline()
    retriever = MockRetriever()
    pipeline.add_node(component=retriever, name="retriever", inputs=["Query"])

    with open(tmp_path / "saved_pipeline.yml", "w") as _:
        pass

    pipeline.save_to_yaml(tmp_path / "saved_pipeline.yml")

    with open(tmp_path / "saved_pipeline.yml", "r") as saved_yaml:
        content = saved_yaml.read()
        assert content != ""
