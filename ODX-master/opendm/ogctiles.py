import os
import sys
import shutil
import json
import tempfile
from opendm.utils import double_quote
from opendm import io
from opendm import log
from opendm import system
from opendm.entwine import build_entwine
from opendm.ogc_enu import create_enu_obj
from opendm.boundary import boundary_offset
from opendm.mesh_clipper import clip_obj_by_boundary


def build_textured_model(input_obj, output_path, reference_lla = None, rerun=False,
                         source_srs=None, source_offset=None, boundary=None):
    if not os.path.isfile(input_obj):
        log.WARNING("No input OBJ file to process")
        return

    if rerun and io.dir_exists(output_path):
        log.WARNING("Removing previous 3D tiles directory: %s" % output_path)
        shutil.rmtree(output_path)

    log.INFO("Generating OGC 3D Tiles textured model")
    lat = lon = alt = 0
    reference_lla_values = None
    
    # Read reference_lla.json (if provided)
    if reference_lla is not None and os.path.isfile(reference_lla):
        try:
            with open(reference_lla) as f:
                reference_lla_values = json.loads(f.read())
                lat = reference_lla_values['latitude']
                lon = reference_lla_values['longitude']
                alt = reference_lla_values['altitude']
        except Exception as e:
            log.WARNING("Cannot read %s: %s" % (reference_lla, str(e)))

    clipped_obj = None
    enu_obj = None
    try:
        obj2tiles_input = input_obj
        if boundary is not None:
            with tempfile.NamedTemporaryFile(prefix=".odm_textured_model_clipped_", suffix=".obj",
                                             dir=os.path.dirname(input_obj), delete=False) as temp:
                clipped_obj = temp.name
            log.INFO("Clipping textured model to reconstruction boundary")
            kept_faces = clip_obj_by_boundary(input_obj, clipped_obj, boundary)
            if kept_faces == 0:
                raise RuntimeError("Boundary clipping removed all textured model faces")
            log.INFO("Boundary-clipped textured model: kept %s faces" % kept_faces)
            obj2tiles_input = clipped_obj

        if source_srs is not None and source_offset is not None and reference_lla_values is not None:
            with tempfile.NamedTemporaryFile(prefix=".odm_textured_model_enu_", suffix=".obj",
                                             dir=os.path.dirname(input_obj), delete=False) as temp:
                enu_obj = temp.name
            log.INFO("Converting textured model from projected coordinates to local ENU")
            create_enu_obj(obj2tiles_input, enu_obj, source_srs, source_offset, reference_lla_values)
            obj2tiles_input = enu_obj

        kwargs = {
            'input': obj2tiles_input,
            'output': output_path,
            'lat': lat,
            'lon': lon,
            'alt': alt,
        }
        system.run('Obj2Tiles "{input}" "{output}" --octree --divisions 0 --lods 4 '
                   '--split-strategy VertexMedian --lod-texture-scale 0.5 --error 40 '
                   '--lat {lat} --lon {lon} --alt {alt} --y-up-to-z-up '.format(**kwargs))

        tileset = os.path.join(output_path, "tileset.json")
        if not os.path.isfile(tileset):
            raise RuntimeError("Obj2Tiles completed without creating %s" % tileset)

    except Exception as e:
        log.WARNING("Cannot build 3D tiles textured model: %s" % str(e))
    finally:
        if enu_obj is not None and os.path.isfile(enu_obj):
            os.unlink(enu_obj)
        if clipped_obj is not None and os.path.isfile(clipped_obj):
            os.unlink(clipped_obj)

def build_pointcloud(input_pointcloud, output_path, max_concurrency, rerun=False):
    if not os.path.isfile(input_pointcloud):
        log.WARNING("No input point cloud file to process")
        return

    if rerun and io.dir_exists(output_path):
        log.WARNING("Removing previous 3D tiles directory: %s" % output_path)
        shutil.rmtree(output_path)

    log.INFO("Generating OGC 3D Tiles point cloud")
    
    try:
        if not os.path.isdir(output_path):
            os.mkdir(output_path)

        tmpdir = os.path.join(output_path, "tmp")
        entwine_output = os.path.join(output_path, "entwine")
        
        build_entwine([input_pointcloud], tmpdir, entwine_output, max_concurrency, "EPSG:4978")
        
        kwargs = {
            'input': entwine_output,
            'output': output_path,
        }
        system.run('entwine convert -i "{input}" -o "{output}"'.format(**kwargs))

        for d in [tmpdir, entwine_output]:
            if os.path.isdir(d):
                shutil.rmtree(d)
    except Exception as e:
        log.WARNING("Cannot build 3D tiles point cloud: %s" % str(e))


def build_3dtiles(args, tree, reconstruction, rerun=False, boundary=None):
    tiles_output_path = tree.ogc_tiles
    model_output_path = os.path.join(tiles_output_path, "model")
    pointcloud_output_path = os.path.join(tiles_output_path, "pointcloud")

    if rerun and os.path.exists(tiles_output_path):
        shutil.rmtree(tiles_output_path)

    if not os.path.isdir(tiles_output_path):
        os.mkdir(tiles_output_path)

    # Model

    model_tileset = os.path.join(model_output_path, "tileset.json")
    if not os.path.isfile(model_tileset) or rerun:
        reference_lla = os.path.join(tree.opensfm, "reference_lla.json")

        input_obj = os.path.join(tree.odm_texturing, tree.odm_textured_model_obj)
        if not os.path.isfile(input_obj):
            input_obj = os.path.join(tree.odm_25dtexturing, tree.odm_textured_model_obj)

        build_textured_model(input_obj, model_output_path, reference_lla,
                             rerun or os.path.isdir(model_output_path),
                             reconstruction.get_proj_srs(), reconstruction.get_proj_offset(),
                             boundary_offset(boundary, reconstruction.get_proj_offset()))
    else:
        log.WARNING("OGC 3D Tiles model %s already generated" % model_output_path)

    # Point cloud
    
    if not os.path.isdir(pointcloud_output_path) or rerun:
        build_pointcloud(tree.odm_georeferencing_model_laz, pointcloud_output_path, args.max_concurrency, rerun)
    else:
        log.WARNING("OGC 3D Tiles model %s already generated" % model_output_path)
