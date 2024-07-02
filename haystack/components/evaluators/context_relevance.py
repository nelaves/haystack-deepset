# SPDX-FileCopyrightText: 2022-present deepset GmbH <info@deepset.ai>
#
# SPDX-License-Identifier: Apache-2.0

from statistics import mean
from typing import Any, Dict, List, Optional

from haystack import component, default_from_dict, default_to_dict
from haystack.components.evaluators.llm_evaluator import LLMEvaluator
from haystack.utils import Secret, deserialize_secrets_inplace

# Private global variable for default examples to include in the prompt if the user does not provide any examples
_DEFAULT_EXAMPLES = [
    {
        "inputs": {
            "questions": "What is the capital of Germany?",
            "contexts": ["Berlin is the capital of Germany. Berlin and was founded in 1244."],
        },
        "outputs": {"relevant_statements": ["Berlin is the capital of Germany."]},
    },
    {
        "inputs": {
            "questions": "What is the capital of France?",
            "contexts": [
                "Berlin is the capital of Germany and was founded in 1244.",
                "Europe is a continent with 44 countries.",
                "Madrid is the capital of Spain.",
            ],
        },
        "outputs": {"relevant_statements": ["Insufficient Information"]},
    },
    {
        "inputs": {"questions": "What is the capital of Italy?", "contexts": ["Rome is the capital of Italy."]},
        "outputs": {"relevant_statements": ["Rome is the capital of Italy."]},
    },
]


@component
class ContextRelevanceEvaluator(LLMEvaluator):
    """
    Evaluator that checks if a provided context is relevant to the question.

    An LLM breaks up the context into multiple statements and checks whether each statement
    is relevant for answering a question.
    The final score for the context relevance is a number from 0.0 to 1.0. It represents the proportion of
    statements that can be inferred from the provided contexts.

    Usage example:
    ```python
    from haystack.components.evaluators import ContextRelevanceEvaluator

    questions = ["Who created the Python language?"]
    contexts = [
        [(
            "Python, created by Guido van Rossum in the late 1980s, is a high-level general-purpose programming "
            "language. Its design philosophy emphasizes code readability, and its language constructs aim to help "
            "programmers write clear, logical code for both small and large-scale software projects."
        )],
    ]

    evaluator = ContextRelevanceEvaluator()
    result = evaluator.run(questions=questions, contexts=contexts)
    print(result["score"])
    # 1.0
    print(result["individual_scores"])
    # [1.0]
    print(result["results"])
    # [{
    #   'statements': ['Python, created by Guido van Rossum in the late 1980s.'],
    #   'statement_scores': [1],
    #   'score': 1.0
    # }]
    ```
    """

    def __init__(
        self,
        examples: Optional[List[Dict[str, Any]]] = None,
        progress_bar: bool = True,
        api: str = "openai",
        api_key: Secret = Secret.from_env_var("OPENAI_API_KEY"),
        raise_on_failure: bool = True,
    ):
        """
        Creates an instance of ContextRelevanceEvaluator.

        :param examples:
            Optional few-shot examples conforming to the expected input and output format of ContextRelevanceEvaluator.
            Default examples will be used if none are provided.
            Each example must be a dictionary with keys "inputs" and "outputs".
            "inputs" must be a dictionary with keys "questions" and "contexts".
            "outputs" must be a dictionary with "statements" and "statement_scores".
            Expected format:
            [{
                "inputs": {
                    "questions": "What is the capital of Italy?", "contexts": ["Rome is the capital of Italy."],
                },
                "outputs": {
                    "statements": ["Rome is the capital of Italy."],
                    "statement_scores": [1],
                },
            }]
        :param progress_bar:
            Whether to show a progress bar during the evaluation.
        :param api:
            The API to use for calling an LLM through a Generator.
            Supported APIs: "openai".
        :param api_key:
            The API key.
        :param raise_on_failure:
            Whether to raise an exception if the API call fails.

        """

        self.instructions = (
            "Please extract only sentences from the provided context which are absolutely relevant and "
            "required to answer the following question. If no relevant sentences are found, or if you "
            "believe the question cannot be answered from the given context, return the phrase "
            '"Insufficient Information"'
        )
        self.inputs = [("questions", List[str]), ("contexts", List[List[str]])]
        self.outputs = ["relevant_statements"]
        self.examples = examples or _DEFAULT_EXAMPLES
        self.api = api
        self.api_key = api_key

        super(ContextRelevanceEvaluator, self).__init__(
            instructions=self.instructions,
            inputs=self.inputs,
            outputs=self.outputs,
            examples=self.examples,
            api=self.api,
            api_key=self.api_key,
            raise_on_failure=raise_on_failure,
            progress_bar=progress_bar,
        )

    @component.output_types(score=float, results=List[Dict[str, Any]])
    def run(self, questions: List[str], contexts: List[List[str]]) -> Dict[str, Any]:
        """
        Run the LLM evaluator.

        :param questions:
            A list of questions.
        :param contexts:
            A list of lists of contexts. Each list of contexts corresponds to one question.
        :returns:
            A dictionary with the following outputs:
                - `score`: Mean context relevance score over all the provided input questions.
                - `results`: A list of dictionaries with `relevant_statements` and `score` for each input context.
        """
        result = super(ContextRelevanceEvaluator, self).run(questions=questions, contexts=contexts)

        for idx, res in enumerate(result["results"]):
            if res is None:
                result["results"][idx] = {"relevant_statements": [], "score": float("nan")}
                continue
            if "relevant_statements" in res:
                if res["relevant_statements"] == ["Insufficient Information"]:
                    res["score"] = 0
                elif res["relevant_statements"] is not None:
                    res["score"] = 1

        # calculate average context relevance score over all queries
        result["score"] = mean([res["score"] for res in result["results"]])

        return result

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize this component to a dictionary.

        :returns:
            A dictionary with serialized data.
        """
        return default_to_dict(
            self,
            api=self.api,
            api_key=self.api_key.to_dict() if self.api_key else None,
            examples=self.examples,
            progress_bar=self.progress_bar,
            raise_on_failure=self.raise_on_failure,
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextRelevanceEvaluator":
        """
        Deserialize this component from a dictionary.

        :param data:
            The dictionary representation of this component.
        :returns:
            The deserialized component instance.
        """
        deserialize_secrets_inplace(data["init_parameters"], keys=["api_key"])
        return default_from_dict(cls, data)
