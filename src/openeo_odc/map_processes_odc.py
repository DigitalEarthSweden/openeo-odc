"""

"""
from ast import arg

from asyncio.format_helpers import extract_stack
from datetime import datetime
import numpy as np
from copy import deepcopy
from typing import List

from openeo_odc.utils import get_oeop_str
from openeo_odc.string_creation import create_param_string

from shapely import ops

DASK_CHUNK_SIZE_X = 12114
DASK_CHUNK_SIZE_Y = 12160


# ----------------------------------------------------------------------------------
#                            add_optional_arg_to_params
# ----------------------------------------------------------------------------------
def add_optional_arg_to_params(params,arguments,argkey,paramkey=None, add_none_vals=False):
    '''
    Only add argument key to params if the argument is given and not None
    unless add_none_vals is true :)
    '''
    paramkey = paramkey or argkey
    val = arguments.get(argkey,None)
    if val or add_none_vals:
        params[paramkey]=val
    return
# ----------------------------------------------------------------------------------
#                     add_optional_spatial_extent_to_params
# ----------------------------------------------------------------------------------
def add_optional_spatial_extent_to_params(params, process):
    if 'spatial_extent' not in process['arguments']:
        return
    try:
        extent = process['arguments']['spatial_extent']
        # From process, either None, bbox OR GeoJSON can be specified.
        latlong = ['south','north','east','west']
        if all([arg in extent for arg in latlong]):
            params['x'] = (extent['west'],extent['east'])
            params['y'] = (extent['south'],extent['north'])
            return None
        
        features =  extent.get('features',[])
        lowLon, highLon = (1000000000.0, 0.0)
        lowLat, highLat = (1000000000.0, 0.0)
        polygons = []
        for feature in features:
            coords = feature['geometry']['coordinates'][0]
            polygon = ops.Polygon(coords)
            (minx, miny, maxx, maxy) = polygon.exterior.bounds
            width = maxx - minx
            height = maxy - miny
            if width == 0 or height == 0:
                continue
            polygons.append(coords)
            lowLon = min(lowLon,minx)
            lowLat = min(lowLat,miny)
            highLon = max(highLon,maxx)
            highLat = max(highLat,maxy)
            
            
            # TODO: Make sure web-editor complies!
            #polygon = features[0]['geometry']['coordinates'][0]
            #lowLat      = np.min([[el[1] for el in polygon]])
            #highLat     = np.max([[el[1] for el in polygon]])
            #lowLon      = np.min([[el[0] for el in polygon]])
            #highLon     = np.max([[el[0] for el in polygon]])
            
        params['x'] = (lowLon,highLon)
        params['y'] = (lowLat,highLat)

        return polygons
    except Exception as e: # KeyError means that the json was malformed. 
        print(e)
        pass # TODO: Raise a good exception here

# ----------------------------------------------------------------------------------
#                      add_optional_time_arg_to_params
# ----------------------------------------------------------------------------------
def add_optional_time_arg_to_params(params, process):
    def up_to_not_including(date):
        return np.datetime_as_string(np.datetime64(date) - np.timedelta64(1, 's'), timezone='UTC') # Achieves, "up to but not including"
    
    default_timeStart = '1970-01-01'
    default_timeEnd   = str(datetime.now()).split(' ')[0] # Today is the default date for timeEnd, to include all the dates if not specified
    params['time'] = [default_timeStart, default_timeEnd]

    if 'temporal_extent' not in process['arguments']:
       return
    extent = process['arguments']['temporal_extent']
    
    if len(extent)>0:
       params['time'][0] = extent[0]
    if len(extent)>1:
       params['time'][1] = up_to_not_including(extent[1])


# ----------------------------------------------------------------------------------
#                      generate_polygon_clipping_code
# ----------------------------------------------------------------------------------
def  generate_polygon_clipping_code(input_crs, dataset, coordinates):
    input_crs = input_crs or 'EPSG:4326'
    code = ""
    code += "Polygon([[17.85,56.8],[18.0,57.9],[18.5,57]])\n"
    code += "\n"
    code += f"poly_coords = {coordinates}\n \n"
    code += "polygons = [ Polygon(coords) for coords in poly_coords]\n"
    code += f"in_crs = pyproj.CRS('{input_crs}')\n"
    code += f"out_crs = pyproj.CRS({dataset}.crs)\n"
    code += "re_project = pyproj.Transformer.from_crs(in_crs, out_crs, always_xy=True).transform\n"
    code += "polygons = [transform(re_project, polygon) for polygon in polygons]\n"
    code += f"{dataset} = {dataset}.rio.clip(polygons, drop=True, invert=False)\n"
     
    return code

# ----------------------------------------------------------------------------------
#                               map_load_collection
# ----------------------------------------------------------------------------------
def map_load_collection(id, process):
    """ Map to load_collection process for ODC datacubes.

    Creates a string like the following:
    dc = oeop.load_collection(odc_cube=datacube,
                              **{'product': 'B_Sentinel_2',
                                 'x': (11.28, 11.41),
                                 'y': (46.52, 46.46),
                                 'time': ['2018-06-04', '2018-06-23'],
                                 'dask_chunks': {'time': 'auto',
                                                 'x': 'auto',
                                                 'y': 'auto'},
                                 'measurements': ['B08', 'B04', 'B02']})

    Returns: str

    """

    params = {
        'product': process['arguments']['id'],
        'dask_chunks': {'y': DASK_CHUNK_SIZE_Y,'x':DASK_CHUNK_SIZE_X, 'time':'auto'},
        }
    # Assume that if parameters are given, they should be correct or an exception is thrown 
    polygon_coordinates =  add_optional_spatial_extent_to_params(params, process)
 
    add_optional_time_arg_to_params(params, process)

    add_optional_arg_to_params(params, process['arguments']['spatial_extent'],'crs')
     
    params['measurements'] =  process['arguments'].get('bands',[])
   
    dataset =f"{'_'+id}" 
    code =  f"{dataset} = oeop.load_collection(odc_cube=cube, **{params})\n"

    if polygon_coordinates:
      code += generate_polygon_clipping_code(input_crs = params.get('crs',None), 
                                             dataset=dataset, coordinates=polygon_coordinates)
    
    return code

# ----------------------------------------------------------------------------------
#                               map_load_result
# ----------------------------------------------------------------------------------
def map_load_result(id, process) -> str:
    """Map load_result process.

    This needs to be handled separately because the user_generated ODC environment / cube must be used.
    """
    # ODC does not allow "-" in product names, there the job_id is slightly adopted to retrieve the product name
    product_name = process['arguments']['id'].replace("-", "_")
    params = {
        'product': product_name,
        'dask_chunks': {'y': DASK_CHUNK_SIZE_Y,'x':DASK_CHUNK_SIZE_X, 'time':'auto'},
        }
    # Assume that if parameters are given, they should be correct or an exception is thrown 
   
    polygon =  add_optional_spatial_extent_to_params(params, process)
    add_optional_time_arg_to_params(params, process)

    params['measurements'] =  process['arguments'].get('bands',[])

    code = f"_{id} = oeop.load_result(odc_cube=cube_user_gen, **{params})\n"

    if polygon:
        code += generate_polygon_clipping_code(input_crs = params.get('crs',None), dataset=dataset, polygon=polygon)
    
    return code

# ----------------------------------------------------------------------------------
#                                map_general
# ----------------------------------------------------------------------------------
def map_general(id, process, kwargs=None, donot_map_params: List[str] = None, job_id:str ="") -> str:
    """Map processes with required arguments only.

    Currently processes with params ('x', 'y'), ('data', 'value'), ('base', 'p'), and ('x') are supported.
    Creates a string like the following: sub_6 = oeop.subtract(**{'x': dep_1, 'y': dep_2})

    Returns: str
    """
    if kwargs is None:
        kwargs = {}
    process_name = process['process_id']
    params = deepcopy(process['arguments'])
    from_param = kwargs['from_parameter'] if kwargs and 'from_parameter' in kwargs else None
    if process_name in ['fit_regr_random_forest', 'predict_random_forest']:
        params['client'] = 'client'
    if 'result_node' in kwargs: #if result_node is in kwargs, data must always be in params
        if process_name not in ['merge_cubes', 'apply_dimension', 'aggregate_temporal_period', 'filter_labels', 'aggregate_spatial']:
            params['data'] = '_' + kwargs['result_node']
        if process_name not in ['apply', 'fit_curve', 'predict_curve', 'merge_cubes', 'apply_dimension', 'aggregate_temporal_period', 'filter_labels', 'aggregate_spatial']:
            params['reducer'] = {}
        _ = kwargs.pop('result_node', None)
    for key in params:
        params[key] = convert_from_node_parameter(params[key], from_param, donot_map_params)

    if 'data' in params:
        if 'dimension' in kwargs and not isinstance(params['data'], list):
            kwargs['dimension'] = check_dimension(kwargs['dimension'])
        elif 'dimension' in kwargs:
            # Do not map 'dimension' for processes like `sum` and `apply`
            _ = kwargs.pop('dimension', None)
        _ = kwargs.pop('from_parameter', None)
        params = {**params, **kwargs}
    if 'save_result' in process_name:
            params['output_filepath'] = f"{job_id}_"
    params_str = create_param_string(params, process_name)
    return get_oeop_str(id, process_name, params_str)

# ----------------------------------------------------------------------------------
#                          convert_from_node_parameter
# ----------------------------------------------------------------------------------
def convert_from_node_parameter(args_in, from_par=None, donot_map_params: List[str] = None):
    """ Convert from_node and resolve from_parameter dependencies."""

    was_list = True
    if not isinstance(args_in, list):
        args_in = [args_in]
        was_list = False

    for k, item in enumerate(args_in):
        if isinstance(item, dict) and 'from_node' in item:
            args_in[k] = '_' + item['from_node']
        if from_par \
                and isinstance(item, dict) \
                and 'from_parameter' in item \
                and item['from_parameter'] in from_par.keys():
            if donot_map_params and item['from_parameter'] in donot_map_params:
                args_in[k] = item["from_parameter"]
            elif isinstance(from_par[item['from_parameter']], str):
                args_in[k] = '_' + from_par[item['from_parameter']]
            else:
                args_in[k] = from_par[item['from_parameter']]
        elif isinstance(item, dict) and 'from_parameter' in item:
            args_in[k] = item["from_parameter"]

    if len(args_in) == 1 and not was_list:
        args_in = args_in[0]

    return args_in

# ----------------------------------------------------------------------------------
#                                check_dimension
# ----------------------------------------------------------------------------------
def check_dimension(in_value):
    """ Convert common dimension names to a preset value."""

    if in_value in ('t', 'time', 'temporal'):
        return 'time'
    elif in_value in ('s', 'band', 'bands', 'spectral'):
        return 'bands'
    return in_value
