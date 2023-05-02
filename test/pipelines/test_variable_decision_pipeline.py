from pathlib import Path
from pprint import pprint

from canals.pipeline import Pipeline
from test.components import AddValue, Remainder, Double

import logging

logging.basicConfig(level=logging.DEBUG)


def test_pipeline(tmp_path):
    add_one = AddValue(add=1)

    pipeline = Pipeline()
    pipeline.add_component("add_one", add_one)
    pipeline.add_component("remainder", Remainder(divisor=3))
    pipeline.add_component("add_ten", AddValue(add=10))
    pipeline.add_component("double", Double())
    pipeline.add_component("add_three", AddValue(add=3))
    pipeline.add_component("add_one_again", add_one)

    pipeline.connect("add_one", "remainder")
    pipeline.connect("remainder.remainder_is_0", "add_ten.value")
    pipeline.connect("remainder.remainder_is_1", "double")
    pipeline.connect("remainder.remainder_is_2", "add_three.value")
    pipeline.connect("add_three", "add_one_again")

    try:
        pipeline.draw(tmp_path / "variable_decision_pipeline.png")
    except ImportError:
        logging.warning("pygraphviz not found, pipeline is not being drawn.")

    results = pipeline.run({"add_one": {"value": 1}})
    pprint(results)

    assert results == {"add_one_again": {"value": 6}}


if __name__ == "__main__":
    test_pipeline(Path(__file__).parent)
