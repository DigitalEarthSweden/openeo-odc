"""

"""

from openeo_odc.map_processes_odc import (map_general, map_load_collection,
                                          map_load_result)
from openeo_odc.utils import PROCS_WITH_VARS, ExtraFuncUtils


def map_to_odc(graph, odc_env, odc_url, job_id: str = None, user_id: str = None):
    """Map openEO process graph to xarray/opendatacube functions."""
    if (not job_id) or (not user_id):
        raise TypeError("Both the job_id and user_id must be provided.")

    extra_func_utils = ExtraFuncUtils()

    nodes = {}
    extra_func = {}

    for k, node_id in enumerate(graph.ids):
        cur_node = graph[node_id]
        parent_proc_id = cur_node.parent_process.process_id if cur_node.parent_process else None

        kwargs = {}
        kwargs['from_parameter'] = resolve_from_parameter(cur_node)
        if len(cur_node.result_processes) == 1:
            kwargs['result_node'] = cur_node.result_processes[0].id
        if cur_node.parent_process: #parent process can be eiter reduce_dimension or apply
            if parent_proc_id == 'reduce_dimension':
                # in apply and reduce_dimension the process is the node of the child process
                kwargs['dimension'] = cur_node.parent_process.content['arguments']['dimension']
                if 'context' in cur_node.parent_process.content['arguments']:
                    if 'from_node' in cur_node.parent_process.content['arguments']['context']:
                        kwargs['context'] = '_' + cur_node.parent_process.content['arguments']['context']['from_node']
            if parent_proc_id == 'apply_dimension':
                # in apply_dimension the process should be a callable process, for example 'mean'.
                # the 'mean' gets transformed to 'oeop.mean' in the string_creation.create_param_string function.
                kwargs['dimension'] = cur_node.parent_process.content['arguments']['dimension']
                cur_node.parent_process.content['arguments']['process'] = cur_node.process_id
            if parent_proc_id == 'aggregate_temporal_period' or parent_proc_id == 'aggregate_spatial':
                cur_node.parent_process.content['arguments']['reducer'] = cur_node.process_id
            if parent_proc_id == 'filter_labels':
                cur_node.parent_process.content['arguments']['condition'] = cur_node.process_id

        if cur_node.process_id in PROCS_WITH_VARS:
            cur_node.content['arguments']['function'] = extra_func_utils.get_func_name(cur_node.id)
            extra_func[extra_func_utils.get_dict_key(cur_node.id)][f"return_{cur_node.id}"] = f"    return _{kwargs.pop('result_node')}\n\n"
        if cur_node.process_id == "save_results":
            graph_will_return_json_stuff = False
        param_sets = [{'x', 'y'}, {'x', }, {'data', 'value'}, {'base', 'p'}, {'data', }]
        if cur_node.process_id == 'load_collection':
            cur_node_content = map_load_collection(cur_node.id, cur_node.content)
        elif cur_node.process_id == 'load_result':
            cur_node_content = map_load_result(cur_node.id, cur_node.content)
        elif (params in set(cur_node.arguments.keys()) for params in param_sets):
            if cur_node.parent_process and parent_proc_id in PROCS_WITH_VARS:
                cur_node_content = map_general(cur_node.id, cur_node.content, kwargs,
                                               donot_map_params=PROCS_WITH_VARS[parent_proc_id].list, job_id=job_id)
            else:
                cur_node_content = map_general(cur_node.id, cur_node.content, kwargs, job_id=job_id)
        else:
            raise ValueError(f"Node {cur_node.id} with arguments {cur_node.arguments.keys()} could not be mapped!")

        # Handle fit_curve / predict_curve sub-process-graph
        if cur_node.parent_process and parent_proc_id in PROCS_WITH_VARS:
            fc_id = cur_node.parent_process.id
            fc_name = extra_func_utils.get_dict_key(fc_id)
            if fc_name not in extra_func:
                extra_func[fc_name] = {
                    f"func_header_{fc_id}": extra_func_utils.get_func_header(fc_id, PROCS_WITH_VARS[parent_proc_id].str)
                }
            extra_func[fc_name][cur_node.id] = f"    {cur_node_content}"  # add indentation
        else:
            nodes[cur_node.id] = cur_node_content

    # Add optional cloud coverage predicate to load_collection 
    for ix in range(1,10): # Can it be more than 10 load collection ? 
        # python client and the web client omits different names for the load collection node  
        load_collection_node = graph.get_node_by_name(f'loadcollection{ix}') or  graph.get_node_by_name(f'load{ix}')
        if load_collection_node is None:
            break
        if 'eo:cloud_cover' in str(load_collection_node):
            # We need to add the predicate to the loadcollection node and also modify
            # the produced code for the actual predicate. 
            predicate_node = load_collection_node.arguments['properties']['eo:cloud_cover']['from_node']
            # Add the predicate to load_collection
            nodes[load_collection_node.id] = nodes[load_collection_node.id].replace("**{",
                                            "**{'dataset_predicate':_"+ predicate_node + ",")
            # Modify the generated predicate so it becomes a lambda function
            prop_filter = nodes[predicate_node]
            # The prop_filter node looks like this: _lte1_1 = oeop.lte(**{"x": value, "y": 95}) but is really
            # should be '_lte1_1 =  lambda dataset: oeop.lte(**{"x": dataset.metadata.cloud_cover, "y": 95})'
            prop_filter = prop_filter.replace('value', 'dataset.metadata.cloud_cover')
            prop_filter = prop_filter.replace(" = ", f" = lambda dataset: ") 
            nodes[predicate_node] = prop_filter
    # End optional cloud cover filter

    final_fc = {}
    for fc_proc in extra_func.values():
        final_fc.update(**fc_proc)
    
    # If we lack a save_results node, we assume the results are in the form of a JSON response
    # And Pack it as such 
    last_node_name = list(nodes.keys())[-1]
    graph_will_return_json_stuff =  "save_result" not in nodes[last_node_name]
        
    res_nodes = {
        'header': create_job_header(odc_env_collection=odc_env, dask_url=odc_url, job_id=job_id, user_id=user_id),
        **final_fc,
        **nodes,
        'tail': create_job_tail(graph_will_return_json_stuff, last_node_name, job_id, odc_url),
    }
    return res_nodes


def resolve_from_parameter(node):
    """ Resolve 'from_parameter' dependencies.

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
        if 'from_parameter' in node.arguments[argument]:
            try:
                from_param_name = node.arguments[argument]['from_parameter']
                # Handle overlap resolver for merge_cubes process
                if node.parent_process.process_id == "merge_cubes" and \
                        "overlap_resolver" in node.parent_process.arguments and \
                        node.parent_process.arguments["overlap_resolver"]["from_node"] == node.id:
                    parent_data_key = overlap_resolver_map[from_param_name]
                    in_nodes[from_param_name] = node.parent_process.arguments[parent_data_key]["from_node"]
                else:
                    # expected that parent process holds parameter in "data" argument
                    in_nodes[from_param_name] = node.parent_process.arguments['data']['from_node']
            except KeyError:
                pass

    return in_nodes

def create_job_header(dask_url: str, job_id: str, user_id: str, odc_env_collection: str = "default", odc_env_user_gen: str = "user_generated"):
    """Create job imports."""
    code = "import rioxarray\n"
    code += "from shapely import ops\n"
    code += "import pyproj\n"
    code += "from shapely.ops import transform\n"
    code += "from shapely.geometry import Polygon\n"
    code += "\n"

    code += "# from dask_gateway import Gateway\n"
    code += "import datacube\n"
    code += "import openeo_processes as oeop\n"
    code += "import time\n"
    code += "\n"

    code += "import json\n"
    code += "\n"
    
    code += "# Initialize ODC instance\n"
    code += "cube = datacube.Datacube()\n"

    if dask_url:
        code += "# Connect to the gateway\n"
        code += "#gateway = Gateway('{dask_url}')\n"
        code += "#options = gateway.cluster_options()\n"
        code += "#options.user_id = '{user_id}'\n"
        code += "#options.job_id = '{job_id}'\n"
        code += "#cluster = gateway.new_cluster(options)\n"
        code += "#cluster.adapt(minimum=1, maximum=3)\n"
        code += "#time.sleep(60)\n"
        code += "#client = cluster.get_client()\n"
        code += "# Note that we shold encapsulate the progran in try-except-finally\n"
 
    return code 

def indent(indent, line):
    return " " * indent + line

def create_job_tail(graph_will_return_json_stuff,last_node_name, job_id, dask_url):
    res = ""
    if dask_url:
        # Ensure shutdown of cluster""" # This should be done in a finally clause
        res +="cluster.shutdown()\ngateway.close()"
    if graph_will_return_json_stuff:
        # Allow other results thatn tif/nc files to be returned
        save_cmd = f"with open('{job_id}.json', 'w') as f:\n"
        save_cmd += indent(4, f"df = _{last_node_name}.compute()\n")
        save_cmd += indent(4, "date_columns = df.select_dtypes(include=['datetime64']).columns.tolist()\n")
        save_cmd += indent(4, "df[date_columns] = df[date_columns].astype(str)\n")
        save_cmd += indent(4, "f.write(df.to_json())\n")
        res += save_cmd
    return res
