import json
import os
from typing import Optional, Dict, Union, List, Any, Callable
import logging
import re

import requests
import sseclient

from haystack.environment import HAYSTACK_REMOTE_API_TIMEOUT_SEC, HAYSTACK_REMOTE_API_MAX_RETRIES
from haystack.errors import (
    HuggingFaceInferenceLimitError,
    HuggingFaceInferenceUnauthorizedError,
    HuggingFaceInferenceError,
)
from haystack.nodes.prompt.invocation_layer import (
    PromptModelInvocationLayer,
    TokenStreamingHandler,
    DefaultTokenStreamingHandler,
)
from haystack.nodes.prompt.invocation_layer.handlers import DefaultPromptHandler
from haystack.utils import request_with_retry
from haystack.lazy_imports import LazyImport

logger = logging.getLogger(__name__)
HF_TIMEOUT = float(os.environ.get(HAYSTACK_REMOTE_API_TIMEOUT_SEC, 30))
HF_RETRIES = int(os.environ.get(HAYSTACK_REMOTE_API_MAX_RETRIES, 5))

with LazyImport() as boto3_import:
    import boto3


class SageMakerInvocationLayer(PromptModelInvocationLayer):
    """
    # TODO: add docs
    """

    def __init__(
        self,
        model_name_or_path: str,
        max_length: int = 100,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        region_name: Optional[str] = None,
        profile_name: Optional[str] = None,
        **kwargs,
    ):
        """
        :param model_name_or_path: The name for SageMaker Model Endpoint.
        :param max_length: The maximum length of the output text.
        :param aws_access_key_id: AWS access key ID.
        :param aws_secret_access_key: AWS secret access key.
        :param aws_session_token: AWS session token.
        :param region_name: AWS region name.
        :param profile_name: AWS profile name.
        """
        boto3_import.check()
        super().__init__(model_name_or_path)
        try:
            session = boto3.Session(
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                aws_session_token=aws_session_token,
                region_name=region_name,
                profile_name=profile_name,
            )
            self.client = session.client("sagemaker-runtime")
        except Exception as e:
            logger.error(
                f"Failed to initialize SageMaker client. Please check if you have aws cli configured or set the aws_kwargs for the boto3 session. {e}"
            )
        self.max_length = max_length

        # for a list of supported parameters (TODO: verify if all of them are supported in sagemaker)
        self.model_input_kwargs = {
            key: kwargs[key]
            for key in [
                "best_of",
                "details",
                "do_sample",
                "max_new_tokens",
                "max_time",
                "model_max_length",
                "num_return_sequences",
                "repetition_penalty",
                "return_full_text",
                "seed",
                "stream",
                "stream_handler",
                "temperature",
                "top_k",
                "top_p",
                "truncate",
                "typical_p",
                "watermark",
            ]
            if key in kwargs
        }

        # we pop the model_max_length from the model_input_kwargs as it is not sent to the model
        # but used to truncate the prompt if needed
        model_max_length = self.model_input_kwargs.pop("model_max_length", 1024)

        # Truncate prompt if prompt tokens > model_max_length-max_length (max_lengt is the length of the generated text)
        self.prompt_handler = DefaultPromptHandler(
            model_name_or_path="gpt2", model_max_length=model_max_length, max_length=self.max_length or 100
        )

    def invoke(self, *args, **kwargs):
        """
        Invokes a prompt on the model. It takes in a prompt and returns a list of responses using a REST invocation.
        :return: The responses are being returned.
        """
        prompt = kwargs.get("prompt")
        if not prompt:
            raise ValueError(
                f"No prompt provided. Model {self.model_name_or_path} requires prompt."
                f"Make sure to provide prompt in kwargs."
            )

        # stop_words to stop the model while generating the answer are currently not supported in SageMaker,
        # but we will truncate the response later on to at least achieve the same behaviour on the answer
        stop_words = kwargs.pop("stop_words", None) or []
        kwargs_with_defaults = self.model_input_kwargs

        # TODO: Check if still relevant / needed
        if "max_new_tokens" not in kwargs_with_defaults:
            kwargs_with_defaults["max_new_tokens"] = self.max_length
        kwargs_with_defaults.update(kwargs)

        # see https://huggingface.co/docs/api-inference/detailed_parameters#text-generation-task
        params = {
            "best_of": kwargs_with_defaults.get("best_of", None),
            "details": kwargs_with_defaults.get("details", True),
            "do_sample": kwargs_with_defaults.get("do_sample", False),
            "max_new_tokens": kwargs_with_defaults.get("max_new_tokens", self.max_length),
            "max_time": kwargs_with_defaults.get("max_time", None),
            "num_return_sequences": kwargs_with_defaults.get("num_return_sequences", None),
            "repetition_penalty": kwargs_with_defaults.get("repetition_penalty", None),
            "return_full_text": kwargs_with_defaults.get("return_full_text", False),
            "seed": kwargs_with_defaults.get("seed", None),
            "stop": kwargs_with_defaults.get("stop", stop_words),
            "temperature": kwargs_with_defaults.get("temperature", None),
            "top_k": kwargs_with_defaults.get("top_k", None),
            "top_p": kwargs_with_defaults.get("top_p", None),
            "truncate": kwargs_with_defaults.get("truncate", None),
            "typical_p": kwargs_with_defaults.get("typical_p", None),
            "watermark": kwargs_with_defaults.get("watermark", False),
        }
        # TODO: Change to boto request "invoke_endpoint"
        body = {"inputs": prompt, **params}
        response = self.client.invoke_endpoint(
            EndpointName=self.model_name_or_path,
            Body=json.dumps(body),
            ContentType="application/json",
            Accept="application/json",
        )
        response_json = response.get("Body").read().decode("utf-8")
        output = json.loads(response_json)
        generated_texts = [o["generated_text"] for o in output if "generated_text" in o]
        if params["stop"]:
            # cut the text after the first occurrence of a stop token
            generated_texts = [re.split("|".join(params["stop"]), t)[0] for t in generated_texts]
        return generated_texts

    # def _post(
    #     self,
    #     data: Dict[str, Any],
    #     stream: bool = False,
    #     attempts: int = HF_RETRIES,
    #     status_codes_to_retry: Optional[List[int]] = None,
    #     timeout: float = HF_TIMEOUT,
    # ) -> requests.Response:
    #     """
    #     Post data to the HF inference model. It takes in a prompt and returns a list of responses using a REST invocation.
    #     :param data: The data to be sent to the model.
    #     :param stream: Whether to stream the response.
    #     :param attempts: The number of attempts to make.
    #     :param status_codes_to_retry: The status codes to retry on.
    #     :param timeout: The timeout for the request.
    #     :return: The responses are being returned.
    #     """
    #     response: requests.Response
    #     if status_codes_to_retry is None:
    #         status_codes_to_retry = [429]
    #     try:
    #         # TODO CHANGE TO BOTO REQUEST
    #         pass
    #         # response = request_with_retry(
    #         #     method="POST",
    #         #     status_codes_to_retry=status_codes_to_retry,
    #         #     attempts=attempts,
    #         #     url=self.url,
    #         #     headers=self.headers,
    #         #     json=data,
    #         #     timeout=timeout,
    #         #     stream=stream,
    #         # )
    #     except requests.HTTPError as err:
    #         res = err.response
    #         if res.status_code == 429:
    #             raise HuggingFaceInferenceLimitError(f"API rate limit exceeded: {res.text}")
    #         if res.status_code == 401:
    #             raise HuggingFaceInferenceUnauthorizedError(f"API key is invalid: {res.text}")
    #
    #         raise HuggingFaceInferenceError(
    #             f"HuggingFace Inference returned an error.\nStatus code: {res.status_code}\nResponse body: {res.text}",
    #             status_code=res.status_code,
    #         )
    #     return response

    def _ensure_token_limit(self, prompt: Union[str, List[Dict[str, str]]]) -> Union[str, List[Dict[str, str]]]:
        # the prompt for this model will be of the type str
        resize_info = self.prompt_handler(prompt)  # type: ignore
        if resize_info["prompt_length"] != resize_info["new_prompt_length"]:
            logger.warning(
                "The prompt has been truncated from %s tokens to %s tokens so that the prompt length and "
                "answer length (%s tokens) fit within the max token limit (%s tokens). "
                "Shorten the prompt to prevent it from being cut off.",
                resize_info["prompt_length"],
                max(0, resize_info["model_max_length"] - resize_info["max_length"]),  # type: ignore
                resize_info["max_length"],
                resize_info["model_max_length"],
            )
        return str(resize_info["resized_prompt"])

    @classmethod
    def supports(cls, model_name_or_path: str, **kwargs) -> bool:
        # TODO check via boto3 if sagemaker endpoint exists (maybe also addition kwargs give us a hint, e.g. region)
        return True
