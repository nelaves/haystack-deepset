import pytest

from haystack.core.component.sockets import InputSocket, Sockets
from haystack.core.pipeline import Pipeline
from haystack.testing.factory import component_class


class TestSockets:
    def test_init(self):
        comp = component_class("SomeComponent", input_types={"input_1": int, "input_2": int})()
        sockets = {"input_1": InputSocket("input_1", int), "input_2": InputSocket("input_2", int)}
        io = Sockets(component=comp, sockets_dict=sockets, sockets_io_type=InputSocket)
        assert io._component == comp
        assert "input_1" in io.__dict__
        assert io.__dict__["input_1"] == comp.__haystack_inputs__._sockets_dict["input_1"]
        assert "input_2" in io.__dict__
        assert io.__dict__["input_2"] == comp.__haystack_inputs__._sockets_dict["input_2"]

    def test_init_with_empty_sockets(self):
        comp = component_class("SomeComponent")()
        io = Sockets(component=comp, sockets_dict={}, sockets_io_type=InputSocket)

        assert io._component == comp
        assert io._sockets_dict == {}

    def test_component_name(self):
        comp = component_class("SomeComponent")()
        io = Sockets(component=comp, sockets_dict={}, sockets_io_type=InputSocket)
        assert io._component_name() == str(comp)

    def test_component_name_added_to_pipeline(self):
        comp = component_class("SomeComponent")()
        pipeline = Pipeline()
        pipeline.add_component("my_component", comp)

        io = Sockets(component=comp, sockets_dict={}, sockets_io_type=InputSocket)
        assert io._component_name() == "my_component"

    def test_getattribute(self):
        comp = component_class("SomeComponent", input_types={"input_1": int, "input_2": int})()
        io = Sockets(component=comp, sockets_dict=comp.__haystack_inputs__._sockets_dict, sockets_io_type=InputSocket)

        assert io.input_1 == comp.__haystack_inputs__._sockets_dict["input_1"]
        assert io.input_2 == comp.__haystack_inputs__._sockets_dict["input_2"]

    def test_getattribute_non_existing_socket(self):
        comp = component_class("SomeComponent", input_types={"input_1": int, "input_2": int})()
        io = Sockets(component=comp, sockets_dict=comp.__haystack_inputs__._sockets_dict, sockets_io_type=InputSocket)

        with pytest.raises(AttributeError):
            io.input_3

    def test_repr(self):
        comp = component_class("SomeComponent", input_types={"input_1": int, "input_2": int})()
        io = Sockets(component=comp, sockets_dict=comp.__haystack_inputs__._sockets_dict, sockets_io_type=InputSocket)
        res = repr(io)
        assert res == f"{comp} inputs:\n  - input_1: int\n  - input_2: int"
