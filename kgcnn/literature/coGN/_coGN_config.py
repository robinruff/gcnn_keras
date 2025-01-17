from copy import deepcopy

units = 128
depth = 5

input_block_cfg = {'node_size': units,
                   'edge_size': units,
                   'atomic_mass': True,
                   'atomic_radius': True,
                   'electronegativity': True,
                   'ionization_energy': True,
                   'oxidation_states': True,
                   'edge_embedding_args': {'bins_distance': 32,
                                           'max_distance': 8.0,
                                           'distance_log_base': 1.0,
                                           'bins_voronoi_area': None,
                                           'max_voronoi_area': None}}

processing_block_cfg = {'edge_mlp': {'units': [units] * 5,
                                     'activation': ['swish'] * 5},
                        'node_mlp': {'units': [units] * 1,
                                     'activation': ['swish'] * 1},
                        'global_mlp': None,
                        'nested_blocks_cfgs': None,
                        'aggregate_edges_local': 'sum',
                        'aggregate_edges_global': None,
                        'aggregate_nodes': None,
                        'return_updated_edges': False,
                        'return_updated_nodes': True,
                        'return_updated_globals': True,
                        'edge_attention_mlp_local': {'units': [32, 1],
                                                     'activation': ['swish', 'swish']},
                        'edge_attention_mlp_global': {'units': [32, 1],
                                                      'activation': ['swish', 'swish']},
                        'node_attention_mlp': {'units': [32, 1], 'activation': ['swish', 'swish']},
                        'edge_gate': None,
                        'node_gate': None,
                        'global_gate': None,
                        'residual_node_update': True,
                        'residual_edge_update': False,
                        'residual_global_update': False,
                        'update_edges_input': [True, True, True, False],
                        'update_nodes_input': [True, False, False],
                        'update_global_input': [False, True, False],
                        'multiplicity_readout': False}

output_block_cfg = {'edge_mlp': None,
                    'node_mlp': None,
                    'global_mlp': {'units': [1],
                                   'activation': ['linear']},
                    'nested_blocks_cfgs': None,
                    'aggregate_edges_local': 'sum',
                    'aggregate_edges_global': None,
                    'aggregate_nodes': 'mean',
                    'return_updated_edges': False,
                    'return_updated_nodes': True,
                    'return_updated_globals': True,
                    'edge_attention_mlp_local': {'units': [32, 1],
                                                 'activation': ['swish', 'swish']},
                    'edge_attention_mlp_global': {'units': [32, 1],
                                                  'activation': ['swish', 'swish']},
                    'node_attention_mlp': {'units': [32, 1], 'activation': ['swish', 'swish']},
                    'edge_gate': None,
                    'node_gate': None,
                    'global_gate': None,
                    'residual_node_update': False,
                    'residual_edge_update': False,
                    'residual_global_update': False,
                    'update_edges_input': [True, True, True, False],
                    'update_nodes_input': [True, False, False],
                    'update_global_input': [False, True, False],
                    'multiplicity_readout': True}

output_block_cfg_no_multiplicity = deepcopy(output_block_cfg)
output_block_cfg_no_multiplicity['multiplicity_readout'] = False


crystal_asymmetric_unit_graphs = {
    "inputs": {
        "offset": {"shape": (None, 3), "name": "offset", "dtype": "float32", "ragged": True},
        "cell_translation": None,
        "affine_matrix": None,
        "voronoi_ridge_area": None,
        "atomic_number": {"shape": (None,), "name": "atomic_number", "dtype": "int32", "ragged": True},
        "frac_coords": None,
        "coords": None,
        "multiplicity": {"shape": (None, ), "name": "multiplicity", "dtype": "int32", "ragged": True},
        "lattice_matrix": None,
        "edge_indices": {"shape": (None, 2), "name": "edge_indices", "dtype": "int32", "ragged": True},
        "line_graph_edge_indices": None,
    },
    "input_block_cfg": input_block_cfg,
    "processing_blocks_cfg": [deepcopy(processing_block_cfg) for _ in range(depth)],
    "output_block_cfg": output_block_cfg,
}

crystal_unit_graphs = {
    "inputs": {
        "offset": {"shape": (None, 3), "name": "offset", "dtype": "float32", "ragged": True},
        "cell_translation": None,
        "affine_matrix": None,
        "voronoi_ridge_area": None,
        "atomic_number": {"shape": (None,), "name": "atomic_number", "dtype": "int32", "ragged": True},
        "frac_coords": None,
        "coords": None,
        "multiplicity": None,
        "lattice_matrix": None,
        "edge_indices": {"shape": (None, 2), "name": "edge_indices", "dtype": "int32", "ragged": True},
        "line_graph_edge_indices": None,
    },
    "input_block_cfg": input_block_cfg,
    "processing_blocks_cfg": [deepcopy(processing_block_cfg) for _ in range(depth)],
    "output_block_cfg": output_block_cfg_no_multiplicity,
}
molecular_graphs = crystal_unit_graphs

crystal_unit_graphs_coord_input = {
    "inputs": {
        "offset": None,
        "cell_translation": {"shape": (None,3), "dtype": "float32", "name": "cell_translation", "ragged": True},
        "affine_matrix": None,
        "voronoi_ridge_area": None,
        "atomic_number": {"shape": (None,), "name": "atomic_number", "dtype": "int32", "ragged": True},
        "frac_coords": {"shape": (None,3), "dtype": "float32", "name": "frac_coords", "ragged": True},
        "coords": None,
        "multiplicity": None,
        "lattice_matrix": {"shape": (3,3), "dtype": "float32", "name": "lattice_matrix"},
        "edge_indices": {"shape": (None, 2), "name": "edge_indices", "dtype": "int32", "ragged": True},
        "line_graph_edge_indices": None,
    },
    "input_block_cfg": input_block_cfg,
    "processing_blocks_cfg": [deepcopy(processing_block_cfg) for _ in range(depth)],
    "output_block_cfg": output_block_cfg_no_multiplicity,
}

molecular_graphs_coord_input = {
    "inputs": {
        "offset": None,
        "cell_translation": None,
        "affine_matrix": None,
        "voronoi_ridge_area": None,
        "atomic_number": {"shape": (None,), "name": "atomic_number", "dtype": "int32", "ragged": True},
        "frac_coords": None,
        "coords": {"shape": (None,3), "dtype": "float32", "name": "coords", "ragged": True},
        "multiplicity": None,
        "lattice_matrix": None,
        "edge_indices": {"shape": (None, 2), "name": "edge_indices", "dtype": "int32", "ragged": True},
        "line_graph_edge_indices": None,
    },
    "input_block_cfg": input_block_cfg,
    "processing_blocks_cfg": [deepcopy(processing_block_cfg) for _ in range(depth)],
    "output_block_cfg": output_block_cfg_no_multiplicity,
}

model_default = crystal_asymmetric_unit_graphs
