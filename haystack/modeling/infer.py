import logging
import multiprocessing as mp
import os
from functools import partial

import torch
from torch.utils.data.sampler import SequentialSampler
from torch.utils.data import Dataset
from tqdm import tqdm
from typing import List, Optional, Dict, Union, Generator

from haystack.modeling.data_handler.dataloader import NamedDataLoader
from haystack.modeling.data_handler.processor import Processor
from haystack.modeling.data_handler.samples import SampleBasket
from haystack.modeling.utils import grouper
from haystack.modeling.data_handler.inputs import QAInput
from haystack.modeling.model.adaptive_model import AdaptiveModel, BaseAdaptiveModel
from haystack.modeling.utils import initialize_device_settings, MLFlowLogger
from haystack.modeling.utils import set_all_seeds, calc_chunksize, log_ascii_workers
from haystack.modeling.model.predictions import QAPred

logger = logging.getLogger(__name__)


class Inferencer:
    """
    Loads a saved AdaptiveModel/ONNXAdaptiveModel from disk and runs it in inference mode. Can be used for a
    model with prediction head (down-stream predictions) and without (using LM as embedder).

    """

    def __init__(
        self,
        model: AdaptiveModel,
        processor: Processor,
        task_type: Optional[str],
        batch_size: int =4,
        gpu: bool =False,
        name: Optional[str] =None,
        return_class_probs: bool=False,
        num_processes: Optional[int] =None,
        disable_tqdm: bool =False
    ):
        """
        Initializes Inferencer from an AdaptiveModel and a Processor instance.

        :param model: AdaptiveModel to run in inference mode
        :param processor: A dataset specific Processor object which will turn input (file or dict) into a Pytorch Dataset.
        :param task_type: Type of task the model should be used for. Currently supporting: "question_answering"
        :param batch_size: Number of samples computed once per batch
        :param gpu: If GPU shall be used
        :param name: Name for the current Inferencer model, displayed in the REST API
        :param return_class_probs: either return probability distribution over all labels or the prob of the associated label
        :param num_processes: the number of processes for `multiprocessing.Pool`.
                              Set to value of 1 (or 0) to disable multiprocessing.
                              Set to None to let Inferencer use all CPU cores minus one.
                              If you want to debug the Language Model, you might need to disable multiprocessing!
                              **Warning!** If you use multiprocessing you have to close the
                              `multiprocessing.Pool` again! To do so call
                              :func:`~farm.infer.Inferencer.close_multiprocessing_pool` after you are
                              done using this class. The garbage collector will not do this for you!
        :param disable_tqdm: Whether to disable tqdm logging (can get very verbose in multiprocessing)
        :return: An instance of the Inferencer.

        """
        MLFlowLogger.disable()

        # Init device and distributed settings
        device, n_gpu = initialize_device_settings(use_cuda=gpu, local_rank=-1, use_amp=None)

        self.processor = processor
        self.model = model
        self.model.eval()
        self.batch_size = batch_size
        self.device = device
        self.language = self.model.get_language()
        self.task_type = task_type
        self.disable_tqdm = disable_tqdm
        self.problematic_sample_ids = set()  # type ignore

        # TODO add support for multiple prediction heads

        self.name = name if name != None else f"anonymous-{self.task_type}"
        self.return_class_probs = return_class_probs

        model.connect_heads_with_processor(processor.tasks, require_labels=False)
        set_all_seeds(42)

        self._set_multiprocessing_pool(num_processes)

    @classmethod
    def load(
        cls,
        model_name_or_path: str,
        revision: Optional[str] = None,
        batch_size: int = 4,
        gpu: bool = False,
        task_type: Optional[str] =None,
        return_class_probs: bool = False,
        strict: bool = True,
        max_seq_len: int = 256,
        doc_stride: int = 128,
        num_processes: Optional[int] =None,
        disable_tqdm: bool = False,
        tokenizer_class: Optional[str] = None,
        use_fast: bool = True,
        tokenizer_args: Dict =None,
        multithreading_rust: bool = True,
        **kwargs
    ):
        """
        Load an Inferencer incl. all relevant components (model, tokenizer, processor ...) either by

        1. specifying a public name from transformers' model hub (https://huggingface.co/models)
        2. or pointing to a local directory it is saved in.

        :param model_name_or_path: Local directory or public name of the model to load.
        :param revision: The version of model to use from the HuggingFace model hub. Can be tag name, branch name, or commit hash.
        :param batch_size: Number of samples computed once per batch
        :param gpu: If GPU shall be used
        :param task_type: Type of task the model should be used for. Currently supporting: "question_answering"
        :param return_class_probs: either return probability distribution over all labels or the prob of the associated label
        :param strict: whether to strictly enforce that the keys loaded from saved model match the ones in
                       the PredictionHead (see torch.nn.module.load_state_dict()).
                       Set to `False` for backwards compatibility with PHs saved with older version of FARM.
        :param max_seq_len: maximum length of one text sample
        :param doc_stride: Only QA: When input text is longer than max_seq_len it gets split into parts, strided by doc_stride
        :param num_processes: the number of processes for `multiprocessing.Pool`. Set to value of 0 to disable
                              multiprocessing. Set to None to let Inferencer use all CPU cores minus one. If you want to
                              debug the Language Model, you might need to disable multiprocessing!
                              **Warning!** If you use multiprocessing you have to close the
                              `multiprocessing.Pool` again! To do so call
                              :func:`~farm.infer.Inferencer.close_multiprocessing_pool` after you are
                              done using this class. The garbage collector will not do this for you!
        :param disable_tqdm: Whether to disable tqdm logging (can get very verbose in multiprocessing)
        :param tokenizer_class: (Optional) Name of the tokenizer class to load (e.g. `BertTokenizer`)
        :param use_fast: (Optional, True by default) Indicate if FARM should try to load the fast version of the tokenizer (True) or
            use the Python one (False).
        :param tokenizer_args: (Optional) Will be passed to the Tokenizer ``__init__`` method.
            See https://huggingface.co/transformers/main_classes/tokenizer.html and detailed tokenizer documentation
            on `Hugging Face Transformers <https://huggingface.co/transformers/>`_.
        :param multithreading_rust: Whether to allow multithreading in Rust, e.g. for FastTokenizers.
                                    Note: Enabling multithreading in Rust AND multiprocessing in python might cause
                                    deadlocks.
        :return: An instance of the Inferencer.

        """
        if tokenizer_args is None:
            tokenizer_args = {}

        device, n_gpu = initialize_device_settings(use_cuda=gpu, local_rank=-1, use_amp=None)
        name = os.path.basename(model_name_or_path)

        # a) either from local dir
        if os.path.exists(model_name_or_path):
            model = BaseAdaptiveModel.load(load_dir=model_name_or_path, device=device, strict=strict)
            processor = Processor.load_from_dir(model_name_or_path)

        # b) or from remote transformers model hub
        else:
            if not task_type:
                raise ValueError("Please specify the 'task_type' of the model you want to load from transformers. "
                                 "Valid options for arg `task_type`:"
                                 "'question_answering'")

            model = AdaptiveModel.convert_from_transformers(model_name_or_path,
                                                            revision=revision,
                                                            device=device,
                                                            task_type=task_type,
                                                            **kwargs)
            processor = Processor.convert_from_transformers(model_name_or_path,
                                                            revision=revision,
                                                            task_type=task_type,
                                                            max_seq_len=max_seq_len,
                                                            doc_stride=doc_stride,
                                                            tokenizer_class=tokenizer_class,
                                                            tokenizer_args=tokenizer_args,
                                                            use_fast=use_fast,
                                                            **kwargs)

        # override processor attributes loaded from config or HF with inferencer params
        processor.max_seq_len = max_seq_len
        processor.multithreading_rust = multithreading_rust
        if hasattr(processor, "doc_stride"):
            assert doc_stride < max_seq_len, "doc_stride is longer than max_seq_len. This means that there will be gaps " \
                                             "as the passage windows slide, causing the model to skip over parts of the document. " \
                                             "Please set a lower value for doc_stride (Suggestions: doc_stride=128, max_seq_len=384) "
            processor.doc_stride = doc_stride

        return cls(
            model,
            processor,
            task_type=task_type,
            batch_size=batch_size,
            gpu=gpu,
            name=name,
            return_class_probs=return_class_probs,
            num_processes=num_processes,
            disable_tqdm=disable_tqdm
        )

    def _set_multiprocessing_pool(self, num_processes: Optional[int]):
        """
        Initialize a multiprocessing.Pool for instances of Inferencer.

        :param num_processes: the number of processes for `multiprocessing.Pool`.
                              Set to value of 1 (or 0) to disable multiprocessing.
                              Set to None to let Inferencer use all CPU cores minus one.
                              If you want to debug the Language Model, you might need to disable multiprocessing!
                              **Warning!** If you use multiprocessing you have to close the
                              `multiprocessing.Pool` again! To do so call
                              :func:`~farm.infer.Inferencer.close_multiprocessing_pool` after you are
                              done using this class. The garbage collector will not do this for you!
        :return:
        """
        self.process_pool = None
        if num_processes == 0 or num_processes == 1:  # disable multiprocessing
            self.process_pool = None
        else:
            if num_processes is None:  # use all CPU cores
                if mp.cpu_count() > 3:
                    num_processes = mp.cpu_count() - 1
                else:
                    num_processes = mp.cpu_count()
            self.process_pool = mp.Pool(processes=num_processes)
            logger.info(
                f"Got ya {num_processes} parallel workers to do inference ..."
            )
            log_ascii_workers(n=num_processes,logger=logger)

    def close_multiprocessing_pool(self, join: bool = False):
        """Close the `multiprocessing.Pool` again.

        If you use multiprocessing you have to close the `multiprocessing.Pool` again!
        To do so call this function after you are done using this class.
        The garbage collector will not do this for you!

        :param join: wait for the worker processes to exit
        """
        if self.process_pool is not None:
            self.process_pool.close()
            if join:
                self.process_pool.join()
            self.process_pool = None

    def save(self, path: str):
        self.model.save(path)
        self.processor.save(path)

    def inference_from_file(self, file: str, multiprocessing_chunksize: int = None, return_json: bool = True):
        """
        Run down-stream inference on samples created from an input file.
        The file should be in the same format as the ones used during training
        (e.g. squad style for QA, tsv for doc classification ...) as the same Processor will be used for conversion.

        :param file: path of the input file for Inference
        :param multiprocessing_chunksize: number of dicts to put together in one chunk and feed to one process
        :return: list of predictions
        """
        dicts = self.processor.file_to_dicts(file)
        preds_all = self.inference_from_dicts(
            dicts,
            return_json=return_json,
            multiprocessing_chunksize=multiprocessing_chunksize,
        )
        return list(preds_all)

    def inference_from_dicts(
        self, dicts: List[Dict], return_json: bool = True, multiprocessing_chunksize: Optional[int] = None
    ) -> List:
        """
        Runs down-stream inference on samples created from input dictionaries.

        * QA (FARM style): [{"questions": ["What is X?"], "text":  "Some context containing the answer"}]

        :param dicts: Samples to run inference on provided as a list(or a generator object) of dicts.
                      One dict per sample.
        :param return_json: Whether the output should be in a json appropriate format. If False, it returns the prediction
                            object where applicable, else it returns PredObj.to_json()
                :param multiprocessing_chunksize: number of dicts to put together in one chunk and feed to one process
                                          (only relevant if you do multiprocessing)
        :return: list of predictions

        """

        # whether to aggregate predictions across different samples (e.g. for QA on long texts)
        # TODO remove or adjust after implmenting input objects properly
        # if set(dicts[0].keys()) == {"qas", "context"}:
        #     warnings.warn("QA Input dictionaries with [qas, context] as keys will be deprecated in the future",
        #                   DeprecationWarning)

        aggregate_preds = False
        if len(self.model.prediction_heads) > 0:
            aggregate_preds = hasattr(self.model.prediction_heads[0], "aggregate_preds")

        if self.process_pool is None:  # multiprocessing disabled (helpful for debugging or using in web frameworks)
            predictions = self._inference_without_multiprocessing(dicts, return_json, aggregate_preds)
            return predictions
        else:  # use multiprocessing for inference
            # Calculate values of multiprocessing_chunksize and num_processes if not supplied in the parameters.

            if multiprocessing_chunksize is None:
                _chunk_size, _ = calc_chunksize(len(dicts))
                multiprocessing_chunksize = _chunk_size

            predictions = self._inference_with_multiprocessing(
                dicts, return_json, aggregate_preds, multiprocessing_chunksize,
            )  # type ignore

            self.processor.log_problematic(self.problematic_sample_ids)
            # cast the generator to a list if it isnt already a list.
            if type(predictions) != list:
                return list(predictions)
            else:
                return predictions  # type ignore

    def _inference_without_multiprocessing(self, dicts: List[Dict], return_json: bool, aggregate_preds: bool) -> List:
        """
        Implementation of inference from dicts without using Python multiprocessing. Useful for debugging or in API
        framework where spawning new processes could be expensive.

        :param dicts: Samples to run inference on provided as a list of dicts. One dict per sample.
        :param return_json: Whether the output should be in a json appropriate format. If False, it returns the prediction
                            object where applicable, else it returns PredObj.to_json()
        :param aggregate_preds: whether to aggregate predictions across different samples (e.g. for QA on long texts)
        :return: list of predictions
        """
        indices = list(range(len(dicts)))
        dataset, tensor_names, problematic_ids, baskets = self.processor.dataset_from_dicts(
            dicts, indices=indices, return_baskets=True
        )
        self.problematic_sample_ids = problematic_ids

        # TODO change format of formatted_preds in QA (list of dicts)
        if aggregate_preds:
            preds_all = self._get_predictions_and_aggregate(dataset, tensor_names, baskets)
        else:
            preds_all = self._get_predictions(dataset, tensor_names, baskets)

        if return_json:
            # TODO this try catch should be removed when all tasks return prediction objects
            try:
                preds_all = [x.to_json() for x in preds_all]
            except AttributeError:
                pass

        return preds_all

    def _inference_with_multiprocessing(
        self, dicts: Union[List[Dict], Generator[Dict, None, None]], return_json: bool, aggregate_preds: bool, multiprocessing_chunksize: int
    ) -> Generator[Dict, None, None]:
        """
        Implementation of inference. This method is a generator that yields the results.

        :param dicts: Samples to run inference on provided as a list of dicts or a generator object that yield dicts.
        :param return_json: Whether the output should be in a json appropriate format. If False, it returns the prediction
                            object where applicable, else it returns PredObj.to_json()
        :param aggregate_preds: whether to aggregate predictions across different samples (e.g. for QA on long texts)
        :param multiprocessing_chunksize: number of dicts to put together in one chunk and feed to one process
        :return: generator object that yield predictions
        """

        # We group the input dicts into chunks and feed each chunk to a different process
        # in the pool, where it gets converted to a pytorch dataset
        results = self.process_pool.imap(
            partial(self._create_datasets_chunkwise, processor=self.processor),
            grouper(iterable=dicts, n=multiprocessing_chunksize),
            1,
        )  # type ignore

        # Once a process spits out a preprocessed chunk. we feed this dataset directly to the model.
        # So we don't need to wait until all preprocessing has finished before getting first predictions.
        for dataset, tensor_names, problematic_sample_ids, baskets in results:
            self.problematic_sample_ids.update(problematic_sample_ids)
            if dataset is None:
                logger.error(f"Part of the dataset could not be converted! \n"
                             f"BE AWARE: The order of predictions will not conform with the input order!")
            else:
                # TODO change format of formatted_preds in QA (list of dicts)
                if aggregate_preds:
                    predictions = self._get_predictions_and_aggregate(
                        dataset, tensor_names, baskets
                    )
                else:
                    predictions = self._get_predictions(dataset, tensor_names, baskets)

                if return_json:
                    # TODO this try catch should be removed when all tasks return prediction objects
                    try:
                        predictions = [x.to_json() for x in predictions]
                    except AttributeError:
                        pass
                yield from predictions

    @classmethod
    def _create_datasets_chunkwise(cls, chunk, processor: Processor):
        """Convert ONE chunk of data (i.e. dictionaries) into ONE pytorch dataset.
        This is usually executed in one of many parallel processes.
        The resulting datasets of the processes are merged together afterwards"""
        dicts = [d[1] for d in chunk]
        indices = [d[0] for d in chunk]
        dataset, tensor_names, problematic_sample_ids, baskets = processor.dataset_from_dicts(dicts, indices, return_baskets=True)
        return dataset, tensor_names, problematic_sample_ids, baskets

    def _get_predictions(self, dataset: Dataset, tensor_names: List, baskets: List[SampleBasket]):
        """
        Feed a preprocessed dataset to the model and get the actual predictions (forward pass + formatting).

        :param dataset: PyTorch Dataset with samples you want to predict
        :param tensor_names: Names of the tensors in the dataset
        :param baskets: For each item in the dataset, we need additional information to create formatted preds.
                        Baskets contain all relevant infos for that.
                        Example: QA - input string to convert the predicted answer from indices back to string space
        :return: list of predictions
        """
        samples = [s for b in baskets for s in b.samples]  # type ignore

        data_loader = NamedDataLoader(
            dataset=dataset, sampler=SequentialSampler(dataset), batch_size=self.batch_size, tensor_names=tensor_names
        )  # type ignore
        preds_all = []
        for i, batch in enumerate(tqdm(data_loader, desc=f"Inferencing Samples", unit=" Batches", disable=self.disable_tqdm)):
            batch = {key: batch[key].to(self.device) for key in batch}
            batch_samples = samples[i * self.batch_size : (i + 1) * self.batch_size]

            # get logits
            with torch.no_grad():
                logits = self.model.forward(**batch)
                preds = self.model.formatted_preds(
                    logits=logits,
                    samples=batch_samples,
                    tokenizer=self.processor.tokenizer,
                    return_class_probs=self.return_class_probs,
                    **batch)
                preds_all += preds
        return preds_all

    def _get_predictions_and_aggregate(self, dataset: Dataset, tensor_names: List, baskets: List[SampleBasket]):
        """
        Feed a preprocessed dataset to the model and get the actual predictions (forward pass + logits_to_preds + formatted_preds).

        Difference to _get_predictions():
         - Additional aggregation step across predictions of individual samples
         (e.g. For QA on long texts, we extract answers from multiple passages and then aggregate them on the "document level")

        :param dataset: PyTorch Dataset with samples you want to predict
        :param tensor_names: Names of the tensors in the dataset
        :param baskets: For each item in the dataset, we need additional information to create formatted preds.
                        Baskets contain all relevant infos for that.
                        Example: QA - input string to convert the predicted answer from indices back to string space
        :return: list of predictions
        """

        data_loader = NamedDataLoader(
            dataset=dataset, sampler=SequentialSampler(dataset), batch_size=self.batch_size, tensor_names=tensor_names
        )  # type ignore
        # TODO Sometimes this is the preds of one head, sometimes of two. We need a more advanced stacking operation
        # TODO so that preds of the right shape are passed in to formatted_preds
        unaggregated_preds_all = []

        for i, batch in enumerate(tqdm(data_loader, desc=f"Inferencing Samples", unit=" Batches", disable=self.disable_tqdm)):

            batch = {key: batch[key].to(self.device) for key in batch}

            # get logits
            with torch.no_grad():
                # Aggregation works on preds, not logits. We want as much processing happening in one batch + on GPU
                # So we transform logits to preds here as well
                logits = self.model.forward(**batch)
                # preds = self.model.logits_to_preds(logits, **batch)[0] (This must somehow be useful for SQuAD)
                preds = self.model.logits_to_preds(logits, **batch)
                unaggregated_preds_all.append(preds)

        # In some use cases we want to aggregate the individual predictions.
        # This is mostly useful, if the input text is longer than the max_seq_len that the model can process.
        # In QA we can use this to get answers from long input texts by first getting predictions for smaller passages
        # and then aggregating them here.

        # At this point unaggregated preds has shape [n_batches][n_heads][n_samples]

        # can assume that we have only complete docs i.e. all the samples of one doc are in the current chunk
        logits = [None]
        preds_all = self.model.formatted_preds(logits=logits, # For QA we collected preds per batch and do not want to pass logits
                                               preds=unaggregated_preds_all,
                                               baskets=baskets)  # type ignore
        return preds_all


class QAInferencer(Inferencer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.task_type != "question_answering":
            logger.warning("QAInferencer always has task_type='question_answering' even if another value is provided "
                           "to Inferencer.load() or QAInferencer()")
            self.task_type = "question_answering"

    def inference_from_dicts(self,
                             dicts: List[dict],
                             return_json: bool = True,
                             multiprocessing_chunksize: Optional[int] = None) -> List[QAPred]:
        return Inferencer.inference_from_dicts(self, dicts, return_json=return_json,
                                               multiprocessing_chunksize=multiprocessing_chunksize)

    def inference_from_file(self,
                            file: str,
                            multiprocessing_chunksize: Optional[int] = None,
                            return_json=True) -> List[QAPred]:
        return Inferencer.inference_from_file(self, file, return_json=return_json,
                                              multiprocessing_chunksize=multiprocessing_chunksize)

    def inference_from_objects(self,
                               objects: List[QAInput],
                               return_json: bool = True,
                               multiprocessing_chunksize: Optional[int] = None) -> List[QAPred]:
        dicts = [o.to_dict() for o in objects]
        # TODO investigate this deprecation warning. Timo: I thought we were about to implement Input Objects, then we can and should use inference from (input) objects!
        #logger.warning("QAInferencer.inference_from_objects() will soon be deprecated. Use QAInferencer.inference_from_dicts() instead")
        return self.inference_from_dicts(dicts, return_json=return_json,
                                         multiprocessing_chunksize=multiprocessing_chunksize)
