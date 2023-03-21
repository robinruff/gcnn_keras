# Implementation details

The most general layers for `kgcnn` should accept (ragged) tensor input and are sorted as following: 

* The most general layers that kept maintained beyond different models with proper documentation are located in `kgcnn.layers`. These are:
    * `kgcnn.layers.attention` Layers for graph attention.
    * `kgcnn.layers.casting` Layers for casting tensor formats.
    * `kgcnn.layers.conv` Basic convolution layers.
    * `kgcnn.layers.gather` Layers around tf.gather.
    * `kgcnn.layers.geom` Geometry operations.
    * `kgcnn.layers.message` Message passing base layer.
    * `kgcnn.layers.mlp` Multi-layer perceptron for graphs.
    * `kgcnn.layers.modules` Keras layers and modules to support ragged tensor input.
    * `kgcnn.layers.norm` Normalization layers for graph tensors.
    * `kgcnn.layers.pooling` General layers for standard aggregation and pooling.
    * `kgcnn.layers.relational` Relational message processing.
    * `kgcnn.layers.set2set` Set2Set type architectures for e.g. pooling nodes.
    * `kgcnn.layers.update` Some node/edge update layers.
