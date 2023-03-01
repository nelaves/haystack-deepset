from __future__ import annotations

import logging
import re
from typing import List, Optional, Union, Dict, Tuple, Any

from haystack import Pipeline, BaseComponent, Answer
from haystack.errors import AgentError
from haystack.nodes import PromptNode, BaseRetriever, PromptTemplate
from haystack.pipelines import (
    BaseStandardPipeline,
    ExtractiveQAPipeline,
    DocumentSearchPipeline,
    GenerativeQAPipeline,
    SearchSummarizationPipeline,
    FAQPipeline,
    TranslationWrapperPipeline,
    RetrieverQuestionGenerationPipeline,
)
from haystack.telemetry import send_custom_event

logger = logging.getLogger(__name__)


class Tool:
    """
    Agent uses tools to find the best answer. A tool is a pipeline or a node. When you add a tool to an Agent, the Agent can
    invoke the underlying pipeline or node to answer questions. 
    
    You must provide a name and a description for each tool. The name should be short and should indicate what the tool can do. The description should explain what the tool is useful for. The Agent uses the description to decide when to use a tool, so the wording you use is important.

    :param name: The name of the tool. The Agent uses this name to refer to the tool in the text the Agent generates.
        The name should be short, ideally one token, and a good description of what the tool can do, for example:
        "Calculator" or "Search". Use only letters (a-z, A-Z), digits (0-9) and underscores (_)."
    :param pipeline_or_node: The pipeline or node to run when the Agent invokes this tool.
    :param description: A description of what the tool is useful for. The Agent uses this description to decide
        when to use which tool. For example, you can describe a tool for calculations by "useful for when you need to
        answer questions about math".
    """

    def __init__(
        self,
        name: str,
        pipeline_or_node: Union[
            BaseComponent,
            Pipeline,
            ExtractiveQAPipeline,
            DocumentSearchPipeline,
            GenerativeQAPipeline,
            SearchSummarizationPipeline,
            FAQPipeline,
            TranslationWrapperPipeline,
            RetrieverQuestionGenerationPipeline,
        ],
        description: str,
    ):
        self.name = name
        self.pipeline_or_node = pipeline_or_node
        self.description = description


class Agent:
    """
    An Agent answers queries using the tools you give to it. The tools are pipelines or nodes. The Agent uses a large
    language model (LLM) through the PromptNode you initialize it with. To answer a query, the Agent follows this sequence:
    1. It generates a thought based on the query.
    2. It decides which tool to use.
    3. It generates the input for the tool.
    4. Based on the output it gets from the tool, the Agent can either stop if it now knows the answer or repeat the
    process of 1) generate thought, 2) choose tool, 3) generate input.

    Agents are useful for questions containing multiple subquestions that can be answered step-by-step (Multihop QA)
    using multiple pipelines and nodes as tools.
    """

    def __init__(
        self,
        prompt_node: PromptNode,
        prompt_template: Union[str, PromptTemplate] = "zero-shot-react",
        tools: Optional[List[Tool]] = None,
        max_iterations: int = 5,
        tool_pattern: str = r'Tool:\s*(\w+)\s*Tool Input:\s*("?)([^"\n]+)\2\s*',
        final_answer_pattern: str = r"Final Answer:\s*(\w+)\s*",
    ):
        """
         Creates an Agent instance.

        :param prompt_node: The PromptNode that the Agent uses to decide which tool to use and what input to provide to it in each iteration.
        :param prompt_template: The name of a PromptTemplate for the PromptNode. It's used for generating thoughts and choosing tools to answer queries step-by-step. You can use the default `zero-shot-react` template or create a new template in a similar format.
        :param tools: A list of tools the Agent can run. If you don't specify any tools here, you must add them with `add_tool()` before running the Agent.
        :param max_iterations: The number of times the Agent can run a tool +1 to let it infer it knows the final answer.
            Set it to at least 2, so that the Agent can run one a tool once and then infer it knows the final answer. The default is 5.
        :param tool_pattern: A regular expression to extract the name of the tool and the corresponding input from the text the Agent generated.
        :param final_answer_pattern: A regular expression to extract the final answer from the text the Agent generated.
        """
        self.prompt_node = prompt_node
        self.prompt_template = (
            prompt_node.get_prompt_template(prompt_template) if isinstance(prompt_template, str) else prompt_template
        )
        self.tools = {tool.name: tool for tool in tools} if tools else {}
        self.tool_names = ", ".join(self.tools.keys())
        self.tool_names_with_descriptions = "\n".join(
            [f"{tool.name}: {tool.description}" for tool in self.tools.values()]
        )
        self.max_iterations = max_iterations
        self.tool_pattern = tool_pattern
        self.final_answer_pattern = final_answer_pattern
        send_custom_event(event=f"{type(self).__name__} initialized")

    def add_tool(self, tool: Tool):
        """
        Add a tool to the Agent. This also updates the PromptTemplate for the Agent's PromptNode with the tool name.

        :param tool: The tool to add to the Agent. Any previously added tool with the same name will be overwritten. Example:
        `agent.add_tool(
            Tool(
                name="Calculator",
                pipeline_or_node=calculator 
                description="Useful when you need to answer questions about math"
            )
        )
        """
        self.tools[tool.name] = tool
        self.tool_names = ", ".join(self.tools.keys())
        self.tool_names_with_descriptions = "\n".join(
            [f"{tool.name}: {tool.description}" for tool in self.tools.values()]
        )

    def has_tool(self, tool_name: str):
        """
        Check whether the Agent has a tool with the name you provide.

        :param tool_name: The name of the tool for which you want to check whether the Agent has it.
        """
        return tool_name in self.tools

    def run(
        self, query: str, max_iterations: Optional[int] = None, params: Optional[dict] = None
    ) -> Dict[str, Union[str, List[Answer]]]:
        """
        Runs the Agent given a query and optional parameters to pass on to the tools used. The result is in the
        same format as a pipeline's result: a dictionary with a key `answers` containing a list of answers.

        :param query: The search query.
        :param max_iterations: The number of times the Agent can run a tool +1 to infer it knows the final answer.
            If you want to set it, make it at least 2 so that the Agent can run a tool once and then infer it knows the final answer.
        :param params: A dictionary of parameters you want to pass to the tools that are pipelines.
                       To pass a parameter to all nodes in those pipelines, use the format: `{"top_k": 10}`.
                       To pass a parameter to targeted nodes in those pipelines, use the format:
                        `{"Retriever": {"top_k": 10}, "Reader": {"top_k": 3}}`.
                        You can only pass parameters to tools that are pipelines, but not nodes.
        """
        if not self.tools:
            raise AgentError(
                "An Agent needs tools to run. Add at least one tool using `add_tool()` or set the parameter `tools` when initializing the Agent."
            )
        if max_iterations is None:
            max_iterations = self.max_iterations
        if max_iterations < 2:
            raise AgentError(
                f"max_iterations must be at least 2 to let the Agent use a tool once and then infer it knows the final answer. It was set to {max_iterations}."
            )

        transcript = self._get_initial_transcript(query=query)
        # Generate a thought with a plan what to do, choose a tool, generate input for it, and run it.
        # Repeat this until the final answer is found or the maximum number of iterations is reached.
        for _ in range(max_iterations):
            preds = self.prompt_node(transcript)
            if not preds:
                raise AgentError(f"The Agent generated no output. Transcript:\n{transcript}")

            # Try to extract final answer or tool name and input from the generated text and update the transcript
            final_answer = self._extract_final_answer(pred=preds[0])
            if final_answer is not None:
                transcript += preds[0]
                return self._format_answer(query=query, transcript=transcript, answer=final_answer)
            tool_name, tool_input = self._extract_tool_name_and_tool_input(pred=preds[0])
            if tool_name is None or tool_input is None:
                raise AgentError(f"Wrong output format. Transcript:\n{transcript}") #is there any way to fix it?

            result = self._run_tool(tool_name=tool_name, tool_input=tool_input, transcript=transcript, params=params)
            observation = self._extract_observation(result)
            transcript += f"{preds[0]}\nObservation: {observation}\nThought: Now that I know that {observation} is the answer to {tool_name} {tool_input}, I "

        logger.warning(
            "The Agent reached the maximum number of iterations (%s) for query (%s). Increase the max_iterations parameter "
            "or the Agent won't be able to provide an answer to this query.",
            max_iterations,
            query,
        )
        return self._format_answer(query=query, transcript=transcript, answer="")

    def run_batch(
        self, queries: List[str], max_iterations: Optional[int] = None, params: Optional[dict] = None
    ) -> Dict[str, str]:
        """
        Runs the Agent in a batch mode.

        :param queries: List of search queries.
        :param max_iterations: The number of times the Agent can run a tool +1 to infer it knows the final answer.
            If you want to set it, make it at least 2 so that the Agent can run a tool once and then infer it knows the final answer.
        :param params: A dictionary of parameters you want to pass to the tools that are pipelines.
                       To pass a parameter to all nodes in those pipelines, use the format: `{"top_k": 10}`.
                       To pass a parameter to targeted nodes in those pipelines, use the format:
                        `{"Retriever": {"top_k": 10}, "Reader": {"top_k": 3}}`.
                        You can only pass parameters to tools that are pipelines but not nodes.
        """
        results: Dict = {"queries": [], "answers": [], "transcripts": []}
        for query in queries:
            result = self.run(query=query, max_iterations=max_iterations, params=params)
            results["queries"].append(result["query"])
            results["answers"].append(result["answers"])
            results["transcripts"].append(result["transcript"])

        return results

    def _run_tool(
        self, tool_name: str, tool_input: str, transcript: str, params: Optional[dict] = None
    ) -> Union[Tuple[Dict[str, Any], str], Dict[str, Any]]:
        if not self.has_tool(tool_name):
            raise AgentError(
                f"The tool {tool_name} wasn't added to the Agent tools: {self.tools.keys()}."
                "Add the tool using `add_tool()` or include it in the parameter `tools` when initializing the Agent."
                f"Transcript:\n{transcript}"
            )

        pipeline_or_node = self.tools[tool_name].pipeline_or_node
        # We can only pass params to pipelines but not to nodes
        if isinstance(pipeline_or_node, (Pipeline, BaseStandardPipeline)):
            result = pipeline_or_node.run(query=tool_input, params=params)
        elif isinstance(pipeline_or_node, BaseRetriever):
            result = pipeline_or_node.run(query=tool_input, root_node="Query")
        else:
            result = pipeline_or_node.run(query=tool_input)
        return result

    def _extract_observation(self, result: Union[Tuple[Dict[str, Any], str], Dict[str, Any]]) -> str:
        observation = ""
        # if result was returned by a node it is of type tuple. We use only the output but not the name of the output.
        # if result was returned by a pipeline it is of type dict that we can use directly.
        if isinstance(result, tuple):
            result = result[0]
        if isinstance(result, dict):
            if result.get("results", None):
                observation = result["results"][0]
            elif result.get("answers", None):
                observation = result["answers"][0].answer
            elif result.get("documents", None):
                observation = result["documents"][0].content

        # observation remains "" if no result/answer/document was returned
        return observation

    def _extract_tool_name_and_tool_input(self, pred: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse the tool name and the tool input from the prediction output of the Agent's PromptNode.

        :param pred: Prediction output of the Agent's PromptNode from which to parse the tool and tool input.
        """
        tool_match = re.search(self.tool_pattern, pred)
        if tool_match:
            tool_name = tool_match.group(1)
            tool_input = tool_match.group(3)
            return tool_name.strip('" []').strip(), tool_input.strip('" ')
        return None, None

    def _extract_final_answer(self, pred: str) -> Optional[str]:
        """
        Parse the final answer from the prediction output of the Agent's PromptNode.

        :param pred: Prediction output of the Agent's PromptNode from which to parse the final answer.
        """
        final_answer_match = re.search(self.final_answer_pattern, pred)
        if final_answer_match:
            final_answer = final_answer_match.group(1)
            return final_answer.strip('" ')
        return None

    def _format_answer(self, query: str, answer: str, transcript: str) -> Dict[str, Union[str, List[Answer]]]:
        """
        Formats an answer as a dict containing `query` and `answers`, similar to the output of a Pipeline.
        The full transcript based on the Agent's initial prompt template and the text it generated during execution.

        :param query: The search query.
        :param answer: The final answer the Agent returned. An empty string corresponds to no answer.
        :param transcript: The text the Agent generated and the initial, filled template for debug purposes.
        """
        return {"query": query, "answers": [Answer(answer=answer, type="generative")], "transcript": transcript}

    def _get_initial_transcript(self, query: str):
        """
        Fills the Agent's PromptTemplate with the query, tool names, and descriptions.

        :param query: The search query.
        """
        return next(
            self.prompt_template.fill(
                query=query, tool_names=self.tool_names, tool_names_with_descriptions=self.tool_names_with_descriptions
            ),
            "",
        )
