"""

"""

from openeo_odc.map_processes_odc import (
    map_general,
    map_load_collection,
    map_load_result,
)
from openeo_odc.utils import PROCS_WITH_VARS, ExtraFuncUtils
import re


def map_to_odc(graph, odc_env, odc_url, job_id: str = None, user_id: str = None):
    """Map openEO process graph to xarray/opendatacube functions."""
    if (not job_id) or (not user_id):
        raise TypeError("Both the job_id and user_id must be provided.")

    extra_func_utils = ExtraFuncUtils()

    nodes = {}
    extra_func = {}

    for k, node_id in enumerate(graph.ids):
        cur_node = graph[node_id]
        parent_proc_id = (
            cur_node.parent_process.process_id if cur_node.parent_process else None
        )

        kwargs = {}
        kwargs["from_parameter"] = resolve_from_parameter(cur_node)
        if len(cur_node.result_processes) == 1:
            kwargs["result_node"] = cur_node.result_processes[0].id
        if (
            cur_node.parent_process
        ):  # parent process can be eiter reduce_dimension or apply
            if parent_proc_id == "reduce_dimension":
                # in apply and reduce_dimension the process is the node of the child process
                kwargs["dimension"] = cur_node.parent_process.content["arguments"][
                    "dimension"
                ]
                if "context" in cur_node.parent_process.content["arguments"]:
                    if (
                        "from_node"
                        in cur_node.parent_process.content["arguments"]["context"]
                    ):
                        kwargs["context"] = (
                            "_"
                            + cur_node.parent_process.content["arguments"]["context"][
                                "from_node"
                            ]
                        )
            if parent_proc_id == "apply_dimension":
                # in apply_dimension the process should be a callable process, for example 'mean'.
                # the 'mean' gets transformed to 'oeop.mean' in the string_creation.create_param_string function.
                kwargs["dimension"] = cur_node.parent_process.content["arguments"][
                    "dimension"
                ]
                cur_node.parent_process.content["arguments"][
                    "process"
                ] = cur_node.process_id
            if (
                parent_proc_id == "aggregate_temporal_period"
                or parent_proc_id == "aggregate_spatial"
            ):
                cur_node.parent_process.content["arguments"][
                    "reducer"
                ] = cur_node.process_id
            if parent_proc_id == "filter_labels":
                cur_node.parent_process.content["arguments"][
                    "condition"
                ] = cur_node.process_id

        if cur_node.process_id in PROCS_WITH_VARS:
            cur_node.content["arguments"]["function"] = extra_func_utils.get_func_name(
                cur_node.id
            )
            extra_func[extra_func_utils.get_dict_key(cur_node.id)][
                f"return_{cur_node.id}"
            ] = f"    return _{kwargs.pop('result_node')}\n\n"
        if cur_node.process_id == "save_results":
            graph_will_return_json_stuff = False
        param_sets = [
            {"x", "y"},
            {
                "x",
            },
            {"data", "value"},
            {"base", "p"},
            {
                "data",
            },
        ]
        if cur_node.process_id == "load_collection":
            cur_node_content = map_load_collection(cur_node.id, cur_node.content)
        elif cur_node.process_id == "load_result":
            cur_node_content = map_load_result(cur_node.id, cur_node.content)
        elif (params in set(cur_node.arguments.keys()) for params in param_sets):
            if cur_node.parent_process and parent_proc_id in PROCS_WITH_VARS:
                cur_node_content = map_general(
                    cur_node.id,
                    cur_node.content,
                    kwargs,
                    donot_map_params=PROCS_WITH_VARS[parent_proc_id].list,
                    job_id=job_id,
                )
            else:
                cur_node_content = map_general(
                    cur_node.id, cur_node.content, kwargs, job_id=job_id
                )
        else:
            raise ValueError(
                f"Node {cur_node.id} with arguments {cur_node.arguments.keys()} could not be mapped!"
            )

        # Handle fit_curve / predict_curve sub-process-graph
        if cur_node.parent_process and parent_proc_id in PROCS_WITH_VARS:
            fc_id = cur_node.parent_process.id
            fc_name = extra_func_utils.get_dict_key(fc_id)
            if fc_name not in extra_func:
                extra_func[fc_name] = {
                    f"func_header_{fc_id}": extra_func_utils.get_func_header(
                        fc_id, PROCS_WITH_VARS[parent_proc_id].str
                    )
                }
            extra_func[fc_name][
                cur_node.id
            ] = f"    {cur_node_content}"  # add indentation
        else:
            nodes[cur_node.id] = cur_node_content

    # BEGIN RISE add optional property predicates
    def _process_predicate_graph(
        nodes,
        current_node_name: str,
        current_load_collection_node,
        stac_property_name: str,
    ) -> None:
        """
        Current code from openeo_odc is wrong so we need to patch the nodes in the process graph.
        We do not want to redo the previous work so instead of working with the graph directly, we traverse the produced
        source code nodes. The only exception is for determining the parameter type (strings were not quoted by openeo_odc)
        What the function does:
        1) If the code refers to any other nodes, we need to process those nodes first and then transform those references
           to function calls.
        2) Transforms current_node_name as:
            a) function that takes one parameter, 'dataset'.
            b) If any of the parameters x or y is 'value', value is replaced by
               code that takes the value from dataset/metadata_doc/properties
            c) if any of the parametes x or y is a string, we need to quote it
        EXAMPLES:
        if nodes[current_node_name] is something like _lte1_1 = oeop.lte(**{'x': value, 'y': 95})  we generate
          ---> def _lte1_1(dataset): return oeop.lte(**{"x": dataset.metadata_doc["properties"].get("eo:cloud_cover"), "y": 95})
        if nodes[current_node_name] is something like _and1_3 = oeop.and_(**{'x': _lte1_1, 'y': _gte1_2})  we need to follow x and y
          ---> def _and1_3(dataset): return oeop.and_(**{"x": _lte1_1(dataset), "y": _gte1_2(dataset)})
        """
        # 1) Check if any arguments refer to other nodes and thus need patching
        x = re.search(r'["\']x["\']: (.*?),', nodes[current_node_name]).group(1)[1:]
        if x in nodes:
            # if x refers to another node we need to call it
            nodes[current_node_name] = nodes[current_node_name].replace(
                x, f"{x}(dataset)"
            )
            # We also need to process that part of the process tree
            _process_predicate_graph(
                nodes, x, current_load_collection_node, stac_property_name
            )
        else:
            x_value = current_load_collection_node.child_processes._nodes[
                current_node_name
            ].arguments["x"]
            if isinstance(x_value, str):
                # 2c)we need to quote the x argument in the code node because openeo forgot to.
                nodes[current_node_name] = nodes[current_node_name].replace(
                    x_value, f"'{x_value}'"
                )

        # Same procedure for the y argument
        y = re.search(r'["\']y["\']: (.*?)}', nodes[current_node_name]).group(1)[1:]
        if y in nodes:
            # if y refers to another node we need to call it
            nodes[current_node_name] = nodes[current_node_name].replace(
                y, f"{y}(dataset)"
            )
            # We also need to process that part of the process tree
            _process_predicate_graph(
                nodes, y, current_load_collection_node, stac_property_name
            )
        else:
            y_value = current_load_collection_node.child_processes._nodes[
                current_node_name
            ].arguments["y"]
            if isinstance(y_value, str):
                # 2c) we need to quote the y argument in the code node because openeo forgot to.
                nodes[current_node_name] = nodes[current_node_name].replace(
                    y_value, f"'{y_value}'"
                )

        # 2a)Transform to function
        nodes[current_node_name] = nodes[current_node_name].replace(
            f"_{current_node_name} = ", f"def _{current_node_name}(dataset) : return "
        )

        # 2b)any references to values should be replaced by dataset property
        nodes[current_node_name] = nodes[current_node_name].replace(
            "value", f"dataset.metadata_doc['properties'].get('{stac_property_name}')"
        )

    # Add optional property predicate(s) to all load_collection nodes
    for ix in range(1, 10):  # Can it be more than 10 load collection ?
        # python client and the web client omits different names for the load collection node
        current_load_collection_node = graph.get_node_by_name(
            f"loadcollection{ix}"
        ) or graph.get_node_by_name(f"load{ix}")
        if current_load_collection_node is None:
            break
        if (
            "properties" in str(current_load_collection_node)
            and current_load_collection_node.arguments["properties"] is not None
        ):
            # 1) Collect all used properties and the produced code nodes
            stac_property_names = current_load_collection_node.arguments[
                "properties"
            ].keys()  # ['eo:cloud_cover','title','etc]
            predicate_root_nodes = []  # These goes into the final predicate

            # 2) Update and patch the code for the process graph for each stac property adressed
            for prop_name in stac_property_names:  # p is e.g. eo:cloud_cover
                predicate_root_node_code = current_load_collection_node.arguments[
                    "properties"
                ][prop_name]["from_node"]
                predicate_root_nodes.append(predicate_root_node_code)
                # The node we fetcht the predicate from may include other nodes like
                _process_predicate_graph(
                    nodes,
                    predicate_root_node_code,
                    current_load_collection_node,
                    prop_name,
                )

            # 3) Build a single or composite predicate depending on the number of arguments
            if len(predicate_root_nodes) == 1:
                predicate = f"_{predicate_root_nodes[0]}"  # e.g. _lte1_1
            else:
                # e.g. lambda dataset: _lte1_1(dataset) and _gte1_1(dataset)
                predicates = "and ".join(
                    [f" _{p}(dataset) " for p in predicate_root_nodes]
                )
                predicate = f"lambda dataset : {predicates}"

            # 4) Add parameter 'dataset_predicate' to the load collection code
            nodes[current_load_collection_node.id] = nodes[
                current_load_collection_node.id
            ].replace("**{", "**{'dataset_predicate': " + predicate + ", ")

    # END   RISE add optional property predicates
    final_fc = {}
    for fc_proc in extra_func.values():
        final_fc.update(**fc_proc)

    # If we lack a save_results node, we assume the results are in the form of a JSON response
    # And Pack it as such
    last_node_name = list(nodes.keys())[-1]
    graph_will_return_json_stuff = "save_result" not in nodes[last_node_name]

    res_nodes = {
        "header": create_job_header(
            odc_env_collection=odc_env, dask_url=odc_url, job_id=job_id, user_id=user_id
        ),
        **final_fc,
        **nodes,
        "tail": create_job_tail(
            graph_will_return_json_stuff, last_node_name, job_id, odc_url
        ),
    }
    return res_nodes


def resolve_from_parameter(node):
    """Resolve 'from_parameter' dependencies.

    Converts e.g. {'from_parameter': 'data'} to {'data': 'dc_0'}

    """
    overlap_resolver_map = {"x": "cube1", "y": "cube2"}

    in_nodes = {}

    # Resolve 'from_parameter' if field exists in node arguments
    for argument in node.arguments:
        # Check if current argument is iterable, else skip to next one
        try:
            _ = iter(node.arguments[argument])
        except TypeError:
            # Argument is not iterable (e.g. 1 or None)
            continue
        if "from_parameter" in node.arguments[argument]:
            try:
                from_param_name = node.arguments[argument]["from_parameter"]
                # Handle overlap resolver for merge_cubes process
                if (
                    node.parent_process.process_id == "merge_cubes"
                    and "overlap_resolver" in node.parent_process.arguments
                    and node.parent_process.arguments["overlap_resolver"]["from_node"]
                    == node.id
                ):
                    parent_data_key = overlap_resolver_map[from_param_name]
                    in_nodes[from_param_name] = node.parent_process.arguments[
                        parent_data_key
                    ]["from_node"]
                else:
                    # expected that parent process holds parameter in "data" argument
                    in_nodes[from_param_name] = node.parent_process.arguments["data"][
                        "from_node"
                    ]
            except KeyError:
                pass

    return in_nodes


def create_job_header(
    dask_url: str,
    job_id: str,
    user_id: str,
    odc_env_collection: str = "default",
    odc_env_user_gen: str = "user_generated",
):
    """Create job imports."""
    code = "import rioxarray\n"
    code += "from shapely import ops\n"
    code += "import pyproj\n"
    code += "from shapely.ops import transform\n"
    code += "from shapely.geometry import Polygon\n"
    code += "\n"
    code += "import datacube\n"
    code += "import openeo_processes as oeop\n"
    code += "import time\n"
    code += "from dask.distributed import Client\n"
    code += "import os\n"
    code += "\n"

    code += "import json\n"
    code += "\n"

    code += "# Initialize ODC instance\n"
    code += "cube = datacube.Datacube()\n"

    code += "dask_url = os.environ.get('DASK_URL', None)\n"
    code += "if dask_url is not None:\n"
    code += "   client = Client(dask_url)\n"

    return code


def indent(indent, line):
    return " " * indent + line


def create_job_tail(graph_will_return_json_stuff, last_node_name, job_id, dask_url):
    res = ""
    # Ensure shutdown of cluster""" # TODO This should be done in a finally clause
    res += "if dask_url is not None:\n"
    res += "   client.close()\n"
    if graph_will_return_json_stuff:
        # Allow other results thatn tif/nc files to be returned
        save_cmd = f"with open('{job_id}.json', 'w') as f:\n"
        save_cmd += indent(4, f"df = _{last_node_name}\n")
        save_cmd += indent(4, "if 'compute' in dir(df):\n")
        save_cmd += indent(8, f"df = df.compute()\n")
        save_cmd += indent(
            8,
            "date_columns = df.select_dtypes(include=['datetime64']).columns.tolist()\n",
        )
        save_cmd += indent(8, "df[date_columns] = df[date_columns].astype(str)\n")
        save_cmd += indent(8, "f.write(df.to_json())\n")
        save_cmd += indent(4, "else:\n")
        save_cmd += indent(8, "res = {}\n")
        save_cmd += indent(8, f"res['result']=_{last_node_name}\n")
        save_cmd += indent(8, "res = json.dumps(res)\n")
        save_cmd += indent(8, "f.write(res)\n")

        res += save_cmd
    return res
