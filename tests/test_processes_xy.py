"""
Tests processes with input type func(x, y)
"""
from typing import Tuple, Any, Dict

import pytest
from openeo_odc.map_processes_odc import map_required

from tests.utils import create_params, set_process


@pytest.fixture(
    params=[
        ({'x': 3, 'y': 6}, "{'x': 3,'y': 6}"),
        ({'x': {'from_node': 'red_3'}, 'y': 6}, "{'x': red_3,'y': 6}"),
        ({'x': {'from_node': 'red_3'}, 'y': {'from_node': 'blue_2'}}, "{'x': red_3,'y': blue_2}"),
    ]
)
def get_xy_param(request):
    return create_params("node_xy", request.param[0], request.param[1])


@pytest.fixture(
    params=[
        ({'x': 3}, "{'x': 3}"),
        ({'x': {'from_node': 'red_3'}}, "{'x': red_3}"),
    ]
)
def get_x_param(request):
    return create_params("node_x", request.param[0], request.param[1])


@pytest.fixture(
    params=[
        ({'data': [1, 2, 3, 4], 'value': 4}, "{'data': [1, 2, 3, 4],'value': 4}"),
        # ({'data': ['1', '2', '3', '4'], 'value': '4'}, "{'data': ['1', '2', '3', '4'],'value': '4'}"),
        # ({'data': ['this', 'is', 'a', 'test'], 'value': 'test'}, "{'data': ['this', 'is', 'a', 'test'],'value': 'test'}"),
        ({'data': {'from_node': 'red_3'}, 'value': 4}, "{'data': red_3,'value': 4}"),
        ({'data': [1, 2, 3, 4], 'value': {'from_node': 'blue_2'}}, "{'data': [1, 2, 3, 4],'value': blue_2}"),
    ]
)
def get_data_val_param(request):
    return create_params("node_data_val", request.param[0], request.param[1])


@pytest.mark.parametrize("process", (
        "gt",
        "gte",
        "lt",
        "lte",
        "add",
        "divide",
        "mod",
        "subtract",
        "multiply",
        "normalized_difference",
        "arctan2",
        "and",
        "or",
        "xor",
))
def test_xy(process: str, get_xy_param: Tuple[str, Dict[str, Any], str]):
    """Test conversions of processes with input x, y."""
    node_id, process_def, process_ref = set_process(*get_xy_param, process)

    out = map_required(node_id, process_def)

    assert out == process_ref


@pytest.mark.parametrize("process", (
        "is_nan",
        "is_no_data",
        "is_valid",
        "not",
        "absolute",
        "int",
        "sgn",
        "sqrt",
        "constant",
        "ln",
        "ceil",
        "floor",
        "arccos",
        "arcsin",
        "arctan",
        "arcsinh",
        "arctanh",
        "cos",
        "cosh",
        "sin",
        "sinh",
        "tan",
        "tanh",
))
def test_x(process: str, get_x_param: Tuple[str, Dict[str, Any], str]):
    """Test conversions of processes with input x."""
    node_id, process_def, process_ref = set_process(*get_x_param, process)

    out = map_required(node_id, process_def)

    assert out == process_ref


@pytest.mark.parametrize('process', (
        "array_contains",
        "array_find",
))
def test_data_value(process: str, get_data_val_param: Tuple[str, Dict[str, Any], str]):
    node_id, process_def, process_ref = set_process(*get_data_val_param, process)

    out = map_required(node_id, process_def)

    assert out == process_ref


@pytest.mark.parametrize("arg_in,arg_out", (
        ({'base': 4, 'p': 2}, "{'base': 4,'p': 2}"),
        ({'base': 4.1, 'p': 2.9}, "{'base': 4.1,'p': 2.9}"),
        ({'base': {'from_node': 'red_3'}, 'p': 4}, "{'base': red_3,'p': 4}"),
        ({'base': 4, 'p': {'from_node': 'blue_2'}}, "{'base': 4,'p': blue_2}"),
        ({'base': {'from_node': 'red_3'}, 'p': {'from_node': 'blue_2'}}, "{'base': red_3,'p': blue_2}"),
))
def test_power(arg_in: Dict[str, Any], arg_out: str):
    """Test conversions of power process with input base, p."""
    node_id, process_def, process_ref = set_process(*create_params("node_power", arg_in, arg_out), "power")

    out = map_required(node_id, process_def)

    assert out == process_ref