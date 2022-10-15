import os
import numpy as np
import pandas as pd
from typing import Union, Callable, List, Dict
from collections import defaultdict
from kgcnn.mol.base import MolGraphInterface
from kgcnn.scaler.mol import QMGraphLabelScaler
from sklearn.preprocessing import StandardScaler
from kgcnn.data.base import MemoryGraphDataset
from kgcnn.mol.io import parse_list_to_xyz_str, read_xyz_file, \
    write_mol_block_list_to_sdf, read_mol_list_from_sdf_file, write_list_to_xyz_file
from kgcnn.mol.module_babel import convert_xyz_to_mol_openbabel, MolecularGraphOpenBabel
from kgcnn.data.utils import pandas_data_frame_columns_to_numpy
from kgcnn.mol.methods import global_proton_dict, inverse_global_proton_dict
from kgcnn.data.moleculenet import MolGraphCallbacks


class QMDataset(MemoryGraphDataset, MolGraphCallbacks):
    r"""This is a base class for QM (quantum mechanical) datasets.

    It generates graph properties from a xyz-file, which stores atomic coordinates.
    Additionally, loading multiple single xyz-files into one file is supported. The file names and labels are given
    by a CSV or table file. The table file must have one line of header with column names!

    .. code-block:: type

        ├── data_directory
            ├── file_directory
            │   ├── *.xyz
            │   ├── *.xyz
            │   └── ...
            ├── file_name.csv
            ├── file_name.xyz
            ├── file_name.sdf
            └── dataset_name.kgcnn.pickle

    Further, it should be possible to generate approximate chemical bonding information via `openbabel`, if this
    additional package is installed. The class inherits from :obj:`MemoryGraphDataset`.
    """

    _global_proton_dict = global_proton_dict
    _inverse_global_proton_dict = inverse_global_proton_dict
    _default_loop_update_info = 5000

    def __init__(self, data_directory: str = None, dataset_name: str = None, file_name: str = None,
                 verbose: int = 10, file_directory: str = None):
        r"""Default initialization. File information on the location of the dataset on disk should be provided here.

        Args:
            data_directory (str): Full path to directory of the dataset. Default is None.
            file_name (str): Filename for reading into memory. This must be the base-name of a '.xyz' file.
                Or additionally the name of a '.csv' formatted file that has a list of file names.
                Files are expected to be in :obj:`file_directory`. Default is None.
            file_directory (str): Name or relative path from :obj:`data_directory` to a directory containing sorted
                '.xyz' files. Only used if :obj:`file_name` is None. Default is None.
            dataset_name (str): Name of the dataset. Important for naming and saving files. Default is None.
            verbose (int): Logging level. Default is 10.
        """
        MemoryGraphDataset.__init__(self, data_directory=data_directory, dataset_name=dataset_name,
                                    file_name=file_name, verbose=verbose,
                                    file_directory=file_directory)
        self.label_units = None
        self.label_names = None

    @property
    def file_path_mol(self):
        """Try to determine a file name for the mol information to store."""
        return os.path.splitext(self.file_path)[0] + ".sdf"

    @property
    def file_path_xyz(self):
        """Try to determine a file name for the mol information to store."""
        return os.path.splitext(self.file_path)[0] + ".xyz"

    @classmethod
    def _make_mol_list(cls, atoms_coordinates_xyz: list):
        """Make mol-blocks from list of multiple molecules.

        Args:
            atoms_coordinates_xyz (list): Nested list of xyz information for each molecule such as
                `[[['C', 'H', ... ], [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], ... ]], ... ]`.

        Returns:
            list: A list of mol-blocks as string.
        """
        mol_list = []
        for x in atoms_coordinates_xyz:
            xyz_str = parse_list_to_xyz_str(x)
            mol_str = convert_xyz_to_mol_openbabel(xyz_str)
            mol_list.append(mol_str)
        return mol_list

    def get_geom_from_xyz_file(self, file_path: str):
        if file_path is None:
            file_path = self.file_path_xyz
        return read_xyz_file(file_path)

    def get_mol_blocks_from_sdf_file(self, file_path: str):
        if file_path is None:
            file_path = self.file_path_mol
        if not os.path.exists(file_path):
            raise FileNotFoundError("Can not load SDF for dataset %s" % self.dataset_name)
        # Loading the molecules and the csv data
        mol_list = read_mol_list_from_sdf_file(file_path)
        if mol_list is None:
            self.warning("Failed to load bond information from SDF file.")
        return mol_list

    def prepare_data(self, overwrite: bool = False, xyz_column_name: str = None, make_sdf: bool = True):
        r"""Pre-computation of molecular structure information in a sdf-file from a xyz-file or a folder of xyz-files.

        If there is no single xyz-file, it will be created with the information of a csv-file with the same name.

        Args:
            overwrite (bool): Overwrite existing database SDF file. Default is False.
            xyz_column_name (str): Name of the column in csv file with list of xyz-files located in file_directory
            make_sdf (bool): Whether to try to make a sdf file from xyz information via OpenBabel.

        Returns:
            self
        """
        if os.path.exists(self.file_path_mol) and not overwrite:
            self.info("Found SDF-file %s of pre-computed structures." % self.file_path_mol)
            return self

        # Try collect single xyz files in directory
        xyz_list = None
        if not os.path.exists(self.file_path_xyz):
            xyz_list = self.collect_files_in_file_directory(
                file_column_name=xyz_column_name, table_file_path=None,
                read_method_file=self.get_geom_from_xyz_file, update_counter=self._default_loop_update_info,
                append_file_content=True, read_method_return_list=True
            )
            write_list_to_xyz_file(self.file_path_xyz, xyz_list)

        # Additionally, try to make SDF file. Requires openbabel.
        if make_sdf:
            if xyz_list is None:
                self.info("Reading single xyz-file.")
                xyz_list = self.get_geom_from_xyz_file(self.file_path_xyz)
            self.info("Converting xyz to mol information.")
            write_mol_block_list_to_sdf(self._make_mol_list(xyz_list), self.file_path_mol)
        return self

    def read_in_memory_xyz(self, file_path: str = None):
        """Read XYZ-file with geometric information into memory.

        Args:
            file_path (str): Filepath to xyz file.

        Returns:
            self
        """
        xyz_list = self.get_geom_from_xyz_file(file_path)
        symbol = [np.array(x[0]) for x in xyz_list]
        coord = [np.array(x[1], dtype="float")[:, :3] for x in xyz_list]
        nodes = [np.array([self._global_proton_dict[x] for x in y[0]], dtype="int") for y in xyz_list]
        self.assign_property("node_coordinates", coord)
        self.assign_property("node_symbol", symbol)
        self.assign_property("node_number", nodes)
        return self

    def read_in_memory_sdf(self, file_path: str = None):
        """Read SDF-file with chemical structure information into memory.

        Args:
            file_path (str): Filepath to SDF file.

        Returns:
            self
        """
        callbacks = {
            "node_symbol": lambda mg, ds: mg.node_symbol,
            "node_number": lambda mg, ds: mg.node_number,
            "edge_indices": lambda mg, ds: mg.edge_number[0],
            "edge_number": lambda mg, ds: np.array(mg.edge_number[1], dtype='int'),
        }
        self._map_molecule_callbacks(
            self.get_mol_blocks_from_sdf_file(file_path),
            self.read_in_table_file().data_frame,
            callbacks=callbacks,
            add_hydrogen=True,
            custom_transform=None,
            make_directed=False,
            mol_interface_class=MolecularGraphOpenBabel
        )
        return self

    def read_in_memory(self, label_column_name: Union[str, list] = None):
        """Read xyz-file geometric information into memory. Optionally read also mol information. And try to find CSV
        file with graph labels if a column is specified by :obj:`label_column_name`.

        Returns:
            self
        """
        # 1. Read labels.
        self.read_in_table_file()
        if self.data_frame is not None and label_column_name is not None:
            labels = self.data_frame[label_column_name]
            self.assign_property("graph_labels", [x for x in labels])
        else:
            self.warning("Can not read '%s' from CSV table for assigning graph labels." % label_column_name)
        # 2. Read geometries from xyz.
        if os.path.exists(self.file_path_xyz):
            self.read_in_memory_xyz()
        else:
            self.error("Can not read .xyz from file, no file '%s' found." % self.file_path_xyz)
        # 3. Read also structure from SDF file.
        if os.path.exists(self.file_path_mol):
            self.read_in_memory_sdf()
        else:
            self.error("Can not read .sdf from file, no file '%s' found." % self.file_path_mol)
        return self
