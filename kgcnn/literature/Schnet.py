import tensorflow.keras as ks

from kgcnn.layers.casting import ChangeTensorType
from kgcnn.layers.conv.schnet_conv import SchNetInteraction
from kgcnn.layers.geom import NodeDistanceEuclidean, GaussBasisLayer, NodePosition
from kgcnn.layers.modules import DenseEmbedding
from kgcnn.layers.mlp import GraphMLP, MLP
from kgcnn.layers.pooling import PoolingNodes
from kgcnn.utils.models import update_model_kwargs, generate_embedding

# Model Schnet as defined
# by Schuett et al. 2018
# https://doi.org/10.1063/1.5019779
# https://arxiv.org/abs/1706.08566  
# https://aip.scitation.org/doi/pdf/10.1063/1.5019779


model_default = {'name': "Schnet",
                 'inputs': [{'shape': (None,), 'name': "node_attributes", 'dtype': 'float32', 'ragged': True},
                            {'shape': (None, 3), 'name': "node_coordinates", 'dtype': 'float32', 'ragged': True},
                            {'shape': (None, 2), 'name': "edge_indices", 'dtype': 'int64', 'ragged': True}],
                 'input_embedding': {"node": {"input_dim": 95, "output_dim": 64}},
                 'output_embedding': 'graph',
                 'output_mlp': {"use_bias": [True, True], "units": [64, 1],
                                "activation": ['kgcnn>shifted_softplus', "linear"]},
                 'last_mlp': {"use_bias": [True, True], "units": [128, 64],
                              "activation": ['kgcnn>shifted_softplus', 'kgcnn>shifted_softplus']},
                 'interaction_args': {"units": 128, "use_bias": True,
                                      "activation": 'kgcnn>shifted_softplus', "cfconv_pool": 'sum'},
                 'node_pooling_args': {"pooling_method": "sum"},
                 'depth': 4,
                 'gauss_args': {"bins": 20, "distance": 4, "offset": 0.0, "sigma": 0.4},
                 "make_distance": True, 'expand_distance': True,
                 'verbose': 1
                 }


@update_model_kwargs(model_default)
def make_model(inputs=None,
               input_embedding=None,
               interaction_args=None,
               output_mlp=None,
               last_mlp=None,
               output_embedding=None,
               node_pooling_args=None,
               depth=None,
               gauss_args=None,
               expand_distance=None,
               make_distance=None,
               name=None,
               verbose=None):
    r"""Make Schnet graph network via functional API. Default parameters can be found in :obj:`model_default`.

    Args:
        inputs (list): List of dictionaries unpacked in :obj:`tf.keras.layers.Input`. Order must match model definition.
        input_embedding (dict): Dictionary of embedding arguments for nodes etc. unpacked in `Embedding` layers.
        output_embedding (str): Main embedding task for graph network. Either "node", ("edge") or "graph".
        output_mlp (dict): Dictionary of layer arguments unpacked in the final classification `MLP` layer block.
            Defines number of model outputs and activation.
        depth (int): Number of graph embedding units or depth of the network.
        interaction_args (dict): Dictionary of layer arguments unpacked in final `SchNetInteraction` layers.
        last_mlp (dict): Dictionary of layer arguments unpacked in last `MLP` layer before output or pooling.
        node_pooling_args (dict): Dictionary of layer arguments unpacked in `PoolingNodes` layers.
        gauss_args (dict): Dictionary of layer arguments unpacked in `GaussBasisLayer` layer.
        make_distance (bool): Whether input is distance or coordinates at in place of edges.
        expand_distance (bool): If the edge input are actual edges or node coordinates instead that are expanded to
            form edges with a gauss distance basis given edge indices indices. Expansion uses `gauss_args`.
        verbose (int): Level of verbosity.
        name (str): Name of the model.

    Returns:
        tf.keras.models.Model
    """
    # Make input
    node_input = ks.layers.Input(**inputs[0])
    xyz_input = ks.layers.Input(**inputs[1])
    edge_index_input = ks.layers.Input(**inputs[2])

    # embedding, if no feature dimension
    n = generate_embedding(node_input, inputs[0]['shape'], input_embedding['node'])
    edi = edge_index_input

    if make_distance:
        x = xyz_input
        pos1, pos2 = NodePosition()([x, edi])
        ed = NodeDistanceEuclidean()([pos1, pos2])
    else:
        ed = xyz_input

    if expand_distance:
        ed = GaussBasisLayer(**gauss_args)(ed)

    # Model
    n = DenseEmbedding(interaction_args["units"], activation='linear')(n)
    for i in range(0, depth):
        n = SchNetInteraction(**interaction_args)([n, ed, edi])

    n = GraphMLP(**last_mlp)(n)

    # Output embedding choice
    if output_embedding == 'graph':
        out = PoolingNodes(**node_pooling_args)(n)
        out = ks.layers.Flatten()(out)  # will be dense
        if output_mlp is not None:
            out = MLP(**output_mlp)(out)
        main_output = out
    elif output_embedding == 'node':
        out = n
        if output_mlp is not None:
            out = GraphMLP(**output_mlp)(out)
        # no ragged for distribution atm
        main_output = ChangeTensorType(input_tensor_type="ragged", output_tensor_type="tensor")(out)
    else:
        raise ValueError("Unsupported graph embedding for mode `SchNet`")

    model = ks.models.Model(inputs=[node_input, xyz_input, edge_index_input], outputs=main_output)
    return model
