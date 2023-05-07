import unittest
from unittest.mock import patch, Mock, call, MagicMock
import json
import os

import pytest

from haystack.nodes import PromptNode
from haystack.nodes.prompt.invocation_layer.handlers import DefaultTokenStreamingHandler, TokenStreamingHandler
from haystack.nodes.prompt.invocation_layer import HFInferenceEndpointInvocationLayer, CohereInvocationLayer


@pytest.mark.unit
def test_default_constructor():
    """
    Test that the default constructor sets the correct values
    """

    layer = CohereInvocationLayer(model_name_or_path="command", api_key="some_fake_key")

    assert layer.api_key == "some_fake_key"
    assert layer.max_length == 100
    assert layer.model_input_kwargs == {}


@pytest.mark.unit
@pytest.mark.parametrize(
    "model_kwargs, model_kwargs_rejected",
    [({"temperature": 0.7, "end_sequences": ["end"], "stream": True}, {"fake_param": 0.7, "another_fake_param": 1})],
)
def test_constructor_with_model_kwargs(model_kwargs, model_kwargs_rejected):
    """
    Test that model_kwargs are correctly set in the constructor
    and that model_kwargs_rejected are correctly filtered out
    """
    layer = CohereInvocationLayer(
        model_name_or_path="command", api_key="some_fake_key", **model_kwargs, **model_kwargs_rejected
    )
    assert layer.model_input_kwargs == model_kwargs
    assert len(model_kwargs_rejected) == 2


@pytest.mark.unit
def test_invoke_with_no_kwargs():
    """
    Test that invoke raises an error if no prompt is provided
    """
    layer = CohereInvocationLayer(model_name_or_path="command", api_key="some_fake_key")
    with pytest.raises(ValueError) as e:
        layer.invoke()
        assert e.match("No prompt provided.")


@pytest.mark.unit
@pytest.mark.parametrize("model", ["command", "command-light"])
@pytest.mark.parametrize("using_constructor", [True, False])
def test_invoke_with_stop_words(model, using_constructor):
    """
    Test stop words are correctly passed from PromptNode to wire in HFInferenceEndpointInvocationLayer
    """
    stop_words = ["but", "not", "bye"]
    pn = PromptNode(model_name_or_path=model, api_key="fake_key", stop_words=stop_words if using_constructor else None)
    assert isinstance(pn.prompt_model.model_invocation_layer, CohereInvocationLayer)
    with unittest.mock.patch("haystack.nodes.prompt.invocation_layer.CohereInvocationLayer._post") as mock_post:
        # Mock the response, need to return a list of dicts
        mock_post.return_value = MagicMock(text='{"generations":[{"text": "Hello"}]}')

        if using_constructor:
            pn("Tell me hello")
        else:
            pn("Tell me hello", stop_words=stop_words if not using_constructor else None)

        assert mock_post.called

        # Check if stop_words are passed to _post as stop parameter
        called_args, _ = mock_post.call_args
        assert "end_sequences" in called_args[0]
        assert called_args[0]["end_sequences"] == stop_words


@pytest.mark.unit
@pytest.mark.parametrize("model", ["command", "command-light"])
@pytest.mark.parametrize("using_constructor", [True, False])
@pytest.mark.parametrize("stream", [True, False])
def test_streaming_stream_param(model, using_constructor, stream):
    """
    Test stream parameter is correctly passed from PromptNode to wire in CohereInvocationLayer
    """
    if using_constructor:
        pn = PromptNode(model_name_or_path=model, api_key="fake_key", model_kwargs={"stream": stream})
    else:
        pn = PromptNode(model_name_or_path=model, api_key="fake_key")

    assert isinstance(pn.prompt_model.model_invocation_layer, CohereInvocationLayer)
    with unittest.mock.patch("haystack.nodes.prompt.invocation_layer.CohereInvocationLayer._post") as mock_post:
        # Mock the response, need to return a list of dicts
        mock_post.return_value = MagicMock(text='{"generations":[{"text": "Hello"}]}')

        if using_constructor:
            pn("Tell me hello")
        else:
            pn("Tell me hello", stream=stream)

        assert mock_post.called

        # Check if stop_words are passed to _post as stop parameter
        called_args, called_kwargs = mock_post.call_args

        # stream is always passed to _post
        assert "stream" in called_kwargs

        # Check if stream is True, then stream is passed as True to _post
        if stream:
            assert called_kwargs["stream"]
        # Check if stream is False, then stream is passed as False to _post
        else:
            assert not called_kwargs["stream"]


@pytest.mark.unit
@pytest.mark.parametrize("model", ["command", "command-light"])
@pytest.mark.parametrize("using_constructor", [True, False])
@pytest.mark.parametrize("stream_handler", [DefaultTokenStreamingHandler(), None])
def test_streaming_stream_handler_param(model, using_constructor, stream_handler):
    """
    Test stream_handler parameter is correctly from PromptNode passed to wire in CohereInvocationLayer
    """
    if using_constructor:
        pn = PromptNode(model_name_or_path=model, api_key="fake_key", model_kwargs={"stream_handler": stream_handler})
    else:
        pn = PromptNode(model_name_or_path=model, api_key="fake_key")

    assert isinstance(pn.prompt_model.model_invocation_layer, CohereInvocationLayer)
    with unittest.mock.patch(
        "haystack.nodes.prompt.invocation_layer.CohereInvocationLayer._post"
    ) as mock_post, unittest.mock.patch(
        "haystack.nodes.prompt.invocation_layer.CohereInvocationLayer._process_streaming_response"
    ) as mock_post_stream:
        # Mock the response, need to return a list of dicts
        mock_post.return_value = MagicMock(text='{"generations":[{"text": "Hello"}]}')

        if using_constructor:
            pn("Tell me hello")
        else:
            pn("Tell me hello", stream_handler=stream_handler)

        assert mock_post.called

        # Check if stop_words are passed to _post as stop parameter
        called_args, called_kwargs = mock_post.call_args

        # stream is always passed to _post
        assert "stream" in called_kwargs

        # if stream_handler is used then stream is always True
        if stream_handler:
            assert called_kwargs["stream"]
            # and stream_handler is passed as an instance of TokenStreamingHandler
            called_args, called_kwargs = mock_post_stream.call_args
            assert "stream_handler" in called_kwargs
            assert isinstance(called_kwargs["stream_handler"], TokenStreamingHandler)
        # if stream_handler is not used then stream is always False
        else:
            assert not called_kwargs["stream"]


def test_supports():
    """
    Test that supports returns True correctly for CohereInvocationLayer
    """
    # doesn't support fake model
    assert not CohereInvocationLayer.supports("fake_model", api_key="fake_key")

    # supports cohere command with api_key
    assert CohereInvocationLayer.supports("command", api_key="fake_key")

    # supports cohere command-light with api_key
    assert CohereInvocationLayer.supports("command-light", api_key="fake_key")
