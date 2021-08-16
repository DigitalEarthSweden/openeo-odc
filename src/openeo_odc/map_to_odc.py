"""

"""

from openeo_odc.map_processes_odc import map_general, map_load_collection
from openeo_odc.utils import FitCurveUtils


def map_to_odc(graph, odc_env, odc_url):
    """Map openEO process graph to xarray/opendatacube functions."""
    fc_utils = FitCurveUtils()

    nodes = {}
    fit_curve = {}
    for k, node_id in enumerate(graph.ids):
        cur_node = graph[node_id]

        kwargs = {}
        kwargs['from_parameter'] = resolve_from_parameter(cur_node)
        if len(cur_node.result_processes) == 1:
            kwargs['result_node'] = cur_node.result_processes[0].id
        if cur_node.parent_process: #parent process can be eiter reduce_dimension or apply
            if cur_node.parent_process.process_id == 'reduce_dimension':
                kwargs['dimension'] = cur_node.parent_process.content['arguments']['dimension']
        if cur_node.process_id == "fit_curve":
            cur_node.content['arguments']['function'] = fc_utils.get_func_name(cur_node.id)
            fit_curve[fc_utils.get_dict_key(cur_node.id)]["return"] = f"    return _{kwargs.pop('result_node')}\n\n"

        param_sets = [{'x', 'y'}, {'x', }, {'data', 'value'}, {'base', 'p'}, {'data', }]
        if cur_node.process_id == 'load_collection':
            cur_node_content = map_load_collection(cur_node.id, cur_node.content)
        elif (params in set(cur_node.arguments.keys()) for params in param_sets):
            cur_node_content = map_general(cur_node.id, cur_node.content, kwargs)
        else:
            raise ValueError(f"Node {cur_node.id} with arguments {cur_node.arguments.keys()} could not be mapped!")

        # Handle fit_curve sub-process-graph
        if cur_node.parent_process and cur_node.parent_process.process_id == "fit_curve":
            fc_id = cur_node.parent_process.id
            fc_name = fc_utils.get_dict_key(fc_id)
            if fc_name not in fit_curve:
                fit_curve[fc_name] = {f"func_header_{fc_id}": fc_utils.get_func_header(fc_id)}
            fit_curve[fc_name][cur_node.id] = f"    {cur_node_content}"  # add indentation
        else:
            nodes[cur_node.id] = cur_node_content

    final_fc = {}
    for fc_proc in fit_curve.values():
        final_fc.update(**fc_proc)
    return {
        'header': create_job_header(odc_env, odc_url),
        **final_fc,
        **nodes,
    }


def resolve_from_parameter(node):
    """ Resolve 'from_parameter' dependencies.

    Converts e.g. {'from_parameter': 'data'} to {'data': 'dc_0'}

    """

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
            in_nodes[argument] = node.parent_process.arguments['data']['from_node']

    return in_nodes


def create_job_header(odc_env: str, dask_url: str):
    """Create job imports."""
    if odc_env is None:
        return f"""from dask.distributed import Client
import datacube
import openeo_processes as oeop

# Initialize ODC instance
cube = datacube.Datacube()
# Connect to Dask Scheduler
client = Client('{dask_url}')
"""
    else:
        return f"""from dask.distributed import Client
import datacube
import openeo_processes as oeop

# Initialize ODC instance
cube = datacube.Datacube(app='app_1', env='{odc_env}')
# Connect to Dask Scheduler
client = Client('{dask_url}')
"""
