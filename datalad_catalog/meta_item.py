# from abc import ABC, abstractmethod
from pathlib import Path
from . import constants as cnst
from .webcatalog import WebCatalog, Node, getNode
from .utils import read_json_file
from datalad.interface.results import get_status_dict
import logging

lgr = logging.getLogger('datalad.catalog.meta_item')


class MetaItem(object):
    """
    A single metadata item input to datalad catalog in its raw state and translated
    into a node, set of nodes, and/or child of a node.

    This class takes care of the delineation of a metadata item into nodes based on
    the item type (dataset / file) and the path of the item.
    """

    # get validated item
    # check whether file or dataset
    # dataset:
    # - create/get dataset node
    # - loop through metaitem keys, copy values
    # - loop through subdatasets, create children and directory nodes
    # file:
    # - create/get parent dataset node
    # - loop through keys, copy values
    # - create children and directory nodes

    def __init__(self, catalog: WebCatalog, meta_item: dict) -> None:
        # Get dataset id and version
        d_id = meta_item[cnst.DATASET_ID]
        d_version = meta_item[cnst.DATASET_VERSION]
        item_type = meta_item[cnst.TYPE]
        self.metadata = meta_item
        # For both type dataset and type file, we need the dataset Node instance
        # Here we fetch or create this Node instance:
        dataset_instance = getNode("dataset", dataset_id=d_id, dataset_version=d_version)
        # Set parent catalog of dataset Node instance
        if not hasattr(dataset_instance, 'parent_catalog') or not dataset_instance.parent_catalog:
            dataset_instance.parent_catalog = catalog
        # Then do things based on metadata object type (dataset or file)
        if meta_item[cnst.TYPE] == cnst.TYPE_DATASET:
            # Dataset
            self.process_dataset(dataset_instance, meta_item, catalog)
        else:
            # File
            # TODO: confirm what to do if meta_item for file from dataset arrives before meta_item for dataset
            # For now: creating node for dataset, even if via file meta_item.
            self.process_file(dataset_instance, meta_item, catalog)

    def __call__(self):
        """
        """
        pass
        
    def process_dataset(self, dataset_instance: Node, meta_item: dict, catalog: WebCatalog):
        """"""
        # 1. If "subdatasets" field exists and the array is not empty,
        # add subdatasets as children and create Nodes
        if cnst.SUBDATASETS in meta_item and meta_item[cnst.SUBDATASETS]:
            for subds in meta_item[cnst.SUBDATASETS]:
                # Grab id, version, path, dirsfrompath
                subds_id = subds[cnst.DATASET_ID]
                subds_version = subds[cnst.DATASET_VERSION]
                # Add DIRSFROMPATH field -> does not exist in metadata yet (not specified in schema)
                p = Path(subds[cnst.DATASET_PATH].lstrip('/'))
                parts_in_path = list(p.parts)
                subds.update({cnst.DIRSFROMPATH: parts_in_path})
                # Create node per directory in subdataset
                if len(parts_in_path) > 1:
                    self.subdataset_path_to_nodes(dataset_instance, parts_in_path, subds_id, subds_version)
                else:
                    # If no nodes, just add as child
                    subds_dict = {
                        cnst.TYPE: cnst.TYPE_DATASET,
                        cnst.NAME: parts_in_path[0],
                        cnst.DATASET_ID: subds[cnst.DATASET_ID],
                        cnst.DATASET_VERSION: subds[cnst.DATASET_VERSION],
                    }
                    dataset_instance.add_child(subds_dict)
        
        # 2. Add fields to node instance; TODO: handle duplications (overwrite for now)
        dataset_instance.add_attribrutes(meta_item, overwrite=True)
    
    def process_file(self, dataset_instance: Node, meta_item: dict, catalog: WebCatalog):
        """"""
        #  Create standard node per path part; TODO: when adding file as child, also add translated_dict
        f_path = meta_item[cnst.PATH]
        parts_in_path = list(Path(f_path.lstrip('/')).parts)
        nr_parts = len(parts_in_path)
        nr_dirs = nr_parts-1 # this excludes the last part, which is the actual filename
        incremental_path = Path('')
        paths = []
        # Assume for now that we're working purely with class instances during operation, then write to file at end
        # IMPORTANT: this does not account for files that already exist, and their content ==> TODO
        for i, part in enumerate(parts_in_path):
            # Get node path
            incremental_path = incremental_path / part
            paths.append(incremental_path)
            file_dict = {
                # cnst.TYPE: cnst.TYPE_FILE,
                cnst.NAME: part,
                # cnst.PATH: str(incremental_path),
            }
            dir_dict = {
                cnst.TYPE: cnst.TYPE_DIRECTORY,
                cnst.NAME: part,
                cnst.PATH: str(incremental_path),
                cnst.DATASET_ID: dataset_instance.dataset_id,
                cnst.DATASET_VERSION: dataset_instance.dataset_version,
            }
            if i == 0 and nr_parts == 1:
                # If the file has no parent directories other than the dataset,
                # add file as child to dataset node
                meta_item.update(file_dict)
                dataset_instance.add_child(meta_item)
                break

            # If the file has one or more parent directories
            if i == 0:
                # first dir in path, add as child to dataset node
                dataset_instance.add_child(dir_dict)
            elif 0 < i < nr_dirs:
                # 2nd...(N-1)th dir in path: create node for N-1, add current as child (dir) to node: bv i=1, create node for i=0
                node_instance = getNode("directory",
                                        dataset_id=dataset_instance.dataset_id,
                                        dataset_version=dataset_instance.dataset_version,
                                        path=paths[i-1])
                node_instance.parent_catalog = catalog
                node_instance.add_child(dir_dict)
            else:
                # Nth (last) part in path = file: create node for N-1, add current as child (file) to node
                meta_item.update(file_dict)
                node_instance = getNode("directory",
                                        dataset_id=dataset_instance.dataset_id,
                                        dataset_version=dataset_instance.dataset_version,
                                        path=paths[i-1])
                node_instance.parent_catalog = catalog
                node_instance.add_child(meta_item)

    
    def subdataset_path_to_nodes(self, dataset_instance: Node, parts_in_path, subds_id, subds_version):
        """
        Add parts of subdataset paths as nodes and children where relevant
        Function used when path to subdataset (relative to parent dataset) has multiple parts
        """
        # print("In CoreTranslator.subdataset_path_to_nodes")
        nr_parts = len(parts_in_path)
        incremental_path = Path('')
        paths = []
        # IMPORTANT: this does not account for files that already exist, and their content ==> TODO
        for i, part in enumerate(parts_in_path):
            # Create dictionary of type directory
            incremental_path = incremental_path / part
            paths.append(incremental_path)
            dir_dict = {
                cnst.TYPE: cnst.TYPE_DIRECTORY,
                cnst.NAME: part,
                cnst.PATH: str(incremental_path),
            }
            if i == 0:
                # first dir in path, add as child to dataset node
                dataset_instance.add_child(dir_dict)
            elif i < nr_parts-1:
                # 2nd...(N-1)th dir in path: create node for N-1, add current as child (dir) to node: e.g. i=1, create node for i=0
                # path for i: parent_dirs[nr_parts-1-i]
                node_instance = getNode("directory",
                                        dataset_id=dataset_instance.dataset_id,
                                        dataset_version=dataset_instance.dataset_version,
                                        path=paths[i-1])
                node_instance.add_child(dir_dict)
            else:
                # Nth (last) part in path = sub-dataset: create node for N-1, add current as child (dataset) to node
                subds_dict = {
                    cnst.TYPE: cnst.TYPE_DATASET,
                    cnst.NAME: part,
                    cnst.PATH: str(incremental_path),
                    cnst.DATASET_ID: subds_id,
                    cnst.DATASET_VERSION: subds_version,
                }
                node_instance = getNode("directory",
                                        dataset_id=dataset_instance.dataset_id,
                                        dataset_version=dataset_instance.dataset_version,
                                        path=paths[i-1])
                node_instance.add_child(subds_dict)