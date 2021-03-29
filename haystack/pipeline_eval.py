
from farm.evaluation.squad_evaluation import compute_f1 as calculate_f1_str
from farm.evaluation.squad_evaluation import compute_exact as calculate_em_str
from haystack.document_store.elasticsearch import ElasticsearchDocumentStore
from haystack.preprocessor.utils import fetch_archive_from_http
from haystack.retriever.sparse import ElasticsearchRetriever
from haystack.retriever.dense import DensePassageRetriever
from haystack.reader.farm import FARMReader
from haystack.finder import Finder
from haystack import Pipeline
from farm.utils import initialize_device_settings

import logging
import subprocess
import time

logger = logging.getLogger(__name__)

LAUNCH_ELASTICSEARCH = True
doc_index = "tutorial5_docs"
label_index = "tutorial5_labels"
top_k_retriever = 10

def launch_es():
    logger.info("Starting Elasticsearch ...")
    status = subprocess.run(
        ['docker run -d -p 9200:9200 -e "discovery.type=single-node" elasticsearch:7.9.2'], shell=True
    )
    if status.returncode:
        logger.warning("Tried to start Elasticsearch through Docker but this failed. "
                       "It is likely that there is already an existing Elasticsearch instance running. ")
    else:
        time.sleep(15)

def main():

    launch_es()

    document_store = ElasticsearchDocumentStore()
    es_retriever = ElasticsearchRetriever(document_store=document_store)
    eval_retriever = EvalRetriever()
    reader = FARMReader("deepset/roberta-base-squad2", top_k_per_candidate=4, num_processes=1)
    eval_reader = EvalReader()

    # Download evaluation data, which is a subset of Natural Questions development set containing 50 documents
    doc_dir = "../data/nq"
    s3_url = "https://s3.eu-central-1.amazonaws.com/deepset.ai-farm-qa/datasets/nq_dev_subset_v2.json.zip"
    fetch_archive_from_http(url=s3_url, output_dir=doc_dir)

    # Add evaluation data to Elasticsearch document store
    # We first delete the custom tutorial indices to not have duplicate elements
    document_store.delete_all_documents(index=doc_index)
    document_store.delete_all_documents(index=label_index)
    document_store.add_eval_data(filename="../data/nq/nq_dev_subset_v2.json", doc_index=doc_index, label_index=label_index)
    labels = document_store.get_all_labels(index=label_index)
    q_to_l_dict = {x.question: x.answer for x in labels}

    # Here is the pipeline definition
    p = Pipeline()
    p.add_node(component=es_retriever, name="ESRetriever", inputs=["Query"])
    p.add_node(component=eval_retriever, name="EvalRetriever", inputs=["ESRetriever"])
    p.add_node(component=reader, name="QAReader", inputs=["EvalRetriever"])
    p.add_node(component=eval_reader, name="EvalReader", inputs=["QAReader"])

    results = []
    for i, (q, l) in enumerate(q_to_l_dict.items()):
        res = p.run(query=q,
                    top_k_retriever=top_k_retriever,
                    labels=l,
                    top_k_reader=10,
                    index=doc_index,
                    # skip_incorrect_retrieval=True
                    )
        results.append(res)

    # TODO: This might not be the best design especially in distributed pipelines
    #  maybe per sample results should be passed on to a final node which does all the aggregation
    #  and metric computation
    print_eval_metrics(eval_retriever, eval_reader)

def print_eval_metrics(eval_retriever, eval_reader):
    total_queries = eval_retriever.query_count
    retriever_recall = eval_retriever.recall
    correct_retrieval = eval_retriever.correct_retrieval
    reader_top_1_em = eval_reader.top_1_em
    reader_top_k_em = eval_reader.top_k_em
    reader_top_1_f1 = eval_reader.top_1_f1
    reader_top_k_f1 = eval_reader.top_k_f1
    pipeline_top_1_em = eval_reader.top_1_em_count / total_queries
    pipeline_top_k_em = eval_reader.top_k_em_count / total_queries
    pipeline_top_1_f1 = eval_reader.top_1_f1_sum / total_queries
    pipeline_top_k_f1 = eval_reader.top_k_f1_sum / total_queries

    print("Retriever")
    print("-----------------")
    print(f"total queries: {total_queries}")
    print(f"recall: {retriever_recall}")
    print()
    print("Reader")
    print("-----------------")
    print(f"answer in retrieved docs: {correct_retrieval}")
    print(f"top 1 EM: {reader_top_1_em}")
    print(f"top k EM: {reader_top_k_em}")
    print(f"top 1 F1: {reader_top_1_f1}")
    print(f"top k F1: {reader_top_k_f1}")
    print()
    print("Pipeline")
    print("-----------------")
    print(f"top 1 EM: {pipeline_top_1_em}")
    print(f"top k EM: {pipeline_top_k_em}")
    print(f"top 1 F1: {pipeline_top_1_f1}")
    print(f"top k F1: {pipeline_top_k_f1}")

class EvalRetriever:
    def __init__(self):
        self.outgoing_edges = 1
        self.correct_retrieval = 0
        self.query_count = 0
        self.recall = 0.0
        # self.log = []

    def run(self, documents, labels, **kwargs):
        # Open domain mode
        self.query_count += 1
        if type(labels) == str:
            labels = [labels]
        texts = [x.text for x in documents]
        correct_retrieval = False
        for t in texts:
            for label in labels:
                if label.lower() in t.lower():
                    self.correct_retrieval += 1
                    correct_retrieval = True
                    break
            if correct_retrieval:
                break
        self.recall = self.correct_retrieval / self.query_count
        # self.log.append({"documents": documents, "labels": labels, "correct_retrieval": correct_retrieval, **kwargs})
        return {"documents": documents, "labels": labels, "correct_retrieval": correct_retrieval, **kwargs}, "output_1"


class EvalReader:
    def __init__(self):
        self.outgoing_edges = 1
        self.query_count = 0
        self.top_1_em_count = 0
        self.top_k_em_count = 0
        self.top_1_f1_sum = 0
        self.top_k_f1_sum = 0
        self.top_1_em = 0.0
        self.top_k_em = 0.0
        self.top_1_f1 = 0.0
        self.top_k_f1 = 0.0

    def run(self, **kwargs):
        self.query_count += 1
        predictions = [p["answer"] for p in kwargs["answers"]]
        # TODO figure out how to handle cases where Reader returns zero answers
        if predictions:
            gold_labels = kwargs["labels"]
            self.top_1_em_count += calculate_em_str_multi(gold_labels, predictions[0])
            self.top_1_f1_sum += calculate_f1_str_multi(gold_labels, predictions[0])
            self.top_k_em_count += max([calculate_em_str_multi(gold_labels, p) for p in predictions])
            self.top_k_f1_sum += max([calculate_f1_str_multi(gold_labels, p) for p in predictions])
        self.update_metrics()
        return {**kwargs}, "output_1"

    def update_metrics(self):
        self.top_1_em = self.top_1_em_count / self.query_count
        self.top_k_em = self.top_k_em_count / self.query_count
        self.top_1_f1 = self.top_1_f1_sum / self.query_count
        self.top_k_f1 = self.top_k_f1_sum / self.query_count


def calculate_em_str_multi(gold_labels, prediction):
    for gold_label in gold_labels:
        result = calculate_em_str(gold_label, prediction)
        if result == 1.0:
            return 1.0
    return 0.0

def calculate_f1_str_multi(gold_labels, prediction):
    results = []
    for gold_label in gold_labels:
        result = calculate_f1_str(gold_label, prediction)
        results.append(result)
    return max(results)

if __name__ == "__main__":
    main()