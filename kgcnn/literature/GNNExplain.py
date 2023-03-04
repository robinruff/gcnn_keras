"""
"Ying et al. - GNNExplainer: Generating Explanations for Graph Neural Networks"

**Changelog**

??.??.2022 - Initial implementation

30.01.2023 - Added the class "GnnExplainer" which supports RaggedTensors and can thus generate multiple
explanations at once, greatly improving time efficiency for explaining large batches of predictions. However
the new class does not implement visualization of the explanations. This will have to be realized on a
higher abstraction level.
"""
import time
import typing as t

import numpy as np
import tensorflow as tf
ks = tf.keras

from kgcnn.xai.base import ImportanceExplanationMethod

# Keep track of model version from commit date in literature.
# To be updated if model is changed in a significant way.
__model_version__ = "2023.01.30"


# == REDUCED, RAGGED TENSOR IMPLEMENTATION ==

class GnnExplainer(ImportanceExplanationMethod):
    """
    Implementation of "ImportanceExplanationMethod", which means that calling an instance of this class
    given a model, a ragged input tensor and output predictions, it should return the corresponding
    node and edge importance tensors, which provide an explanation by assigning each node and edge of the
    input graphs with a 0-1 importance value.

    By the nature of the base idea behind GNNExplainer, the number of explanations produced has to be equal
    to the number of prediction targets that are generated by the model. Each target will receive its own
    explanation.
    """
    def __init__(self,
                 channels: int,
                 epochs: int = 100,
                 learning_rate: float = 0.01,
                 node_sparsity_factor: float = 0.1,
                 edge_sparsity_factor: float = 0.1,
                 log_step: int = 10,
                 verbose: bool = True):
        super(GnnExplainer, self).__init__(channels=channels)
        self.epochs = epochs
        self.learning_rate = learning_rate
        self.log_step = log_step
        self.verbose = verbose
        self.node_sparsity_factor = node_sparsity_factor
        self.edge_sparsity_factor = edge_sparsity_factor

    def __call__(self,
                 model: ks.models.Model,
                 x: t.Tuple[tf.RaggedTensor, tf.RaggedTensor, tf.RaggedTensor],
                 y: np.ndarray):
        """Given a model, the input tensor and the output array, this method will return a tuple of two
        ragged tensors, which represent the node importances and the edge importances.

        Beware, that this method executes an entire training process and may take some time.

        Reference of tensor shapes. [Brackets] indicate ragged dimension

            - V: Number of nodes in graph
            - E: Number of edges in graph
            - K: Number of explanation channels given in constructor. This has to be equal to the number of
                prediction targets specified in the constructor.
            - N: Number of node attributes
            - M: Number of edge attributes
            - B: batch size

        Args:
            x: A tuple (node_input, edge_input, edge_indices) of 3 RaggedTensors

                - node_input: Shape ([B], [V], N)
                - edge_input: Shape ([B], [E], M)
                - edge_indices: Shape ([B], [E], 2)

            y: A numpy array of shape (B, K)
            model: Any compatible keras model, which means any model which accepts the previously described
                input tensors and returns output similar to the previously described output tensor.

        Returns:
            A tuple (node_importances, edge_importances) of RaggedTensors.

                - node_importances: Shape ([B], [V], K)
                - edge_importances: Shape ([B], [E], K)

        """
        # Generally the idea of the implementation is that we use the node_input and edge_input tensors as
        # templates to generate the mask variable tensors, which match the graph dimensions but differ in
        # the final dimension, which instead of the node / edge features we will use to represent the
        # number of importance channels (== number of prediction targets).

        node_input, edge_input, edge_indices = x

        # Here we reduce away the last dimension of node and edge input to get just the ragged graph sizes
        # But we run into a problem here with multiple channels: We cant actually use the last dimension to
        # represent the number of different explanation channels. Instead, we do a workaround here where for
        # each channel we extend the batch dimension. Aka we assume that all the different channels are just
        # additional graphs to be treated like the others. The reason why we have to do it like that is
        # because later on we need to multiply the masks with the inputs!
        node_mask_single = tf.reduce_mean(tf.ones_like(node_input), axis=-1, keepdims=True)
        node_mask_ragged = tf.concat([node_mask_single for _ in range(self.channels)], axis=0)
        node_mask_variables = tf.Variable(node_mask_ragged.flat_values, trainable=True, dtype=tf.float64)

        edge_mask_single = tf.reduce_mean(tf.ones_like(edge_input), axis=-1, keepdims=True)
        edge_mask_ragged = tf.concat([edge_mask_single for _ in range(self.channels)], axis=0)
        edge_mask_variables = tf.Variable(edge_mask_ragged.flat_values, trainable=True, dtype=tf.float64)

        optimizer = ks.optimizers.Nadam(learning_rate=self.learning_rate)

        # This is a logical extension of what was previously described. Since we treat the different
        # explanation channels as just a batch extension, we have to modify the input values and the output
        # values accordingly so that they have the same batch size so to say. Naturally we simply have to
        # duplicate the values.
        x_extended = (
            tf.concat([node_input for _ in range(self.channels)], axis=0),
            tf.concat([edge_input for _ in range(self.channels)], axis=0),
            tf.concat([edge_indices for _ in range(self.channels)], axis=0),
        )
        y_extended = []
        for c in range(self.channels):
            y_mod = np.zeros_like(y)
            y_mod[:, c] = y[:, c]
            y_extended.append(y_mod)

        y_extended = np.concatenate(y_extended)

        start_time = time.time()
        for epoch in range(self.epochs):

            with tf.GradientTape() as tape:
                node_mask = tf.RaggedTensor.from_nested_row_splits(
                    node_mask_variables,
                    nested_row_splits=node_mask_ragged.nested_row_splits
                )

                edge_mask = tf.RaggedTensor.from_nested_row_splits(
                    edge_mask_variables,
                    nested_row_splits=edge_mask_ragged.nested_row_splits
                )

                out = model([
                    x_extended[0] * node_mask,
                    x_extended[1] * edge_mask,
                    x_extended[2]
                ])

                # The loss can basically be summerized as: We try to find the smallest subset of nodes and
                # edges in the input, which will cause the network to get as close as possible to it's
                # original prediction!
                loss = tf.cast(tf.reduce_mean(tf.square(y_extended - out)), dtype=tf.float64)
                # Important detail: The reduce_sum here reduces over all the nodes / edges and is necessary!
                loss += self.node_sparsity_factor * tf.reduce_mean(tf.reduce_sum(tf.abs(node_mask), axis=1))
                loss += self.edge_sparsity_factor * tf.reduce_mean(tf.reduce_sum(tf.abs(edge_mask), axis=1))

            trainable_vars = [node_mask_variables, edge_mask_variables]
            gradients = tape.gradient(loss, trainable_vars)
            optimizer.apply_gradients(zip(gradients, trainable_vars))

            if self.verbose and epoch % self.log_step == 0:
                print(f' * epoch ({epoch}/{self.epochs}) '
                      f' - loss: {loss}'
                      f' - elapsed time: {time.time()-start_time:.2f} seconds')

        # For the training we had to treat the different explanation channels as a batch extension. As per
        # the interface we need to return the importances however such that the different explanation
        # channels are organized into the third dimension of the tensors.

        # Sadly this does not work in a more direct fashion. We get the number of elements of nodes and
        # edges that belong to one explanation channel. Iterate in chunks of that size and turn each of
        # those chunks into it's own explanation respectively. At the end we concatenate all of them in
        # the 3rd dimension to produce the desired result.
        num_elements_node = node_mask_single.flat_values.shape[0]
        num_elements_edge = edge_mask_single.flat_values.shape[0]
        node_importances_list = []
        edge_importances_list = []
        for c in range(self.channels):
            node_importances_part = tf.RaggedTensor.from_nested_row_splits(
                node_mask_variables[c*num_elements_node:(c+1)*num_elements_node, :],
                node_mask_single.nested_row_splits
            )
            node_importances_list.append(node_importances_part)

            edge_importances_part = tf.RaggedTensor.from_nested_row_splits(
                edge_mask_variables[c*num_elements_edge:(c+1)*num_elements_edge, :],
                edge_mask_single.nested_row_splits
            )
            edge_importances_list.append(edge_importances_part)

        return (
            tf.concat(node_importances_list, axis=-1),
            tf.concat(edge_importances_list, axis=-1)
        )


# == ORIGINAL IMPLEMENTATION ==

class GNNInterface:
    """An interface class which should be implemented by a Graph Neural Network (GNN) model to make it explainable.
    This class is just an interface, which is used by the `GNNExplainer` and should be implemented in a subclass.
    The implementation of this class could be a wrapper around an existing Tensorflow/Keras GNN.
    The output of the methods `predict` and `masked_predict` should be of same dimension and the output to be explained.

    """

    def predict(self, gnn_input, **kwargs):
        """Returns the prediction for the `gnn_input`.

        Args:
            gnn_input: The input graph to which a prediction should be made by the GNN.

        Raises:
            NotImplementedError: This is just an interface class, to indicate which methods should be implemented.
                Implement this method in a subclass.
        """
        raise NotImplementedError(
            "Implement this method in a specific subclass.")

    def masked_predict(self, gnn_input, edge_mask, feature_mask, node_mask, **kwargs):
        """Returns the prediction for the `gnn_input` when it is masked by the three given masks.

        Args:
            gnn_input: The input graph to which should be masked before a prediction should be made by the GNN.
            edge_mask: A `Tensor` of shape `[get_number_of_edges(self, gnn_input), 1]`,
                which should mask the edges of the input graph.
            feature_mask: A `Tensor` of shape `[get_number_of_node_features(self, gnn_input), 1]`,
                which should mask the node features in the input graph.
            node_mask: A `Tensor` of shape `[get_number_of_nodes(self, gnn_input), 1]`,
                which should mask the node features in the input graph.

        Raises:
            NotImplementedError: This is just an interface class, to indicate which methods should be implemented.
                Implement this method in a subclass.
        """
        raise NotImplementedError(
            "Implement this method in a specific subclass.")

    def get_number_of_nodes(self, gnn_input):
        """Returns the number of nodes in the `gnn_input` graph.

        Args:
            gnn_input: The input graph to which this function returns the number of nodes in.

        Raises:
            NotImplementedError: This is just an interface class, to indicate which methods should be implemented.
                Implement this method in a subclass.
        """
        raise NotImplementedError(
            "Implement this method in a specific subclass.")

    def get_number_of_edges(self, gnn_input):
        """Returns the number of edges in the `gnn_input` graph.

        Args:
            gnn_input: The input graph to which this function returns the number of edges in.

        Raises:
            NotImplementedError: This is just an interface class, to indicate which methods should be implemented.
                Implement this method in a subclass.
        """
        raise NotImplementedError(
            "Implement this method in a specific subclass.")

    def get_number_of_node_features(self, gnn_input):
        """Returns the number of node features to the corresponding `gnn_input`.

        Args:
            gnn_input: The input graph to which this function returns the number of node features in.

        Raises:
            NotImplementedError: This is just an interface class, to indicate which methods should be implemented.
                Implement this method in a subclass.
        """
        raise NotImplementedError(
            "Implement this method in a specific subclass.")

    def get_explanation(self, gnn_input, edge_mask, feature_mask, node_mask, **kwargs):
        """Takes the graph input and the masks learned by the GNNExplainer and combines them to some sort of explanation
        The form of explanation could e.g. consist of a networkx graph,
        which has mask values as labels to nodes/edge and a dict for the feature explanation values.

        Args:
            gnn_input: The input graph to which should the masks were found by the GNNExplainer.
            edge_mask: A `Tensor` of shape `[get_number_of_edges(self, gnn_input), 1]`,
                which was found by the GNNExplainer.
            feature_mask: A `Tensor` of shape `[get_number_of_node_features(self, gnn_input), 1]`,
                which was found by the GNNExplainer.
            node_mask: A `Tensor` of shape `[get_number_of_nodes(self, gnn_input), 1]`,
                which was found by the GNNExplainer.

        Raises:
            NotImplementedError: This is just an interface class, to indicate which methods should be implemented.
                Implement this method in a subclass.
        """
        raise NotImplementedError(
            "Implement this method in a specific subclass.")

    def present_explanation(self, explanation, **kwargs):
        """Takes an explanation, which was generated by `get_explanation` and presents it to the user in a suitable way.
        The presentation of an explanation largely depends on the data domain and targeted user group.
        Examples for presentations:

        * A visualization of the most relevant subgraph(s) to the decision
        * A visualization of the whole graph with highlighted parts
        * Bar diagrams for feature explanations
        * ...

        Args:
            explanation: An explanation for the GNN decision,
                which is of the form the `get_explanation` method returns an explanation.
        Raises:
            NotImplementedError: This is just an interface class, to indicate which methods should be implemented.
                Implement this method in a subclass.
        """
        raise NotImplementedError(
            "Implement this method in a specific subclass.")


class GNNExplainer:
    """`GNNExplainer` explains the decisions of a GNN, which implements `GNNInterface`.

    See Ying et al. (https://arxiv.org/abs/1903.03894) for details on how such an explanation is found.
    Note that this implementation is inspired by the paper by Ying et al., but differs in some aspects.
    """

    def __init__(self, gnn, gnnexplaineroptimizer_options=None,
                 compile_options=None, fit_options=None, **kwargs):
        """Constructs a GNNExplainer instance for the given `gnn`.

        Args:
            gnn: An instance of a class which implements the `GNNInterface`.
            gnnexplaineroptimizer_options (dict, optional): Parameters in this dict are forwarded to the constructor
                of the `GNNExplainerOptimizer` (see docstring of `GNNExplainerOptimizer.__init__`).
                Defaults to {}.
            compile_options (dict, optional): Parameters in ths dict are forwarded to the `keras.Model.compile` method
                of the `GNNExplainerOpimizer`. Can be used to customize the optimization process of the
                `GNNExplainerOptimizer`.
                Defaults to {}.
            fit_options (dict, optional): Parameters in ths dict are forwarded to the `keras.Model.fit` method
                of the `GNNExplainerOpimizer`.
                Defaults to {}.
        """
        if gnnexplaineroptimizer_options is None:
            gnnexplaineroptimizer_options = {}
        if compile_options is None:
            compile_options = {}
        if fit_options is None:
            fit_options = {}
        self.gnn = gnn
        self.gnnx_optimizer = None
        self.graph_instance = None
        self.gnnexplaineroptimizer_options = gnnexplaineroptimizer_options
        self.compile_options = compile_options
        self.fit_options = fit_options

    def explain(self, graph_instance, output_to_explain=None, inspection=False, **kwargs):
        """Finds the masks to the decision of the `self.gnn` on the given `graph_instance`.
        This method does not have a return value, but only has side effects.
        To get the explanation which was found, call `get_explanation` after calling this method.
        This method just instantiates a `GNNExplainerOptimizer`,
        which then finds the masks for the explanation via gradient descent.

        Args:
            graph_instance: The graph input to the GNN to which an explanation should be found.
            output_to_explain (optional): Set this parameter to the output which should be explained.
                By default the GNNExplainer explains the output the `self.gnn` on the given `graph_instance`.
                Defaults to None.
            inspection (optional): If `inspection` is set to True this function will return information
                about the optimization process in a dictionary form.
                Be aware that inspections results in longer runtimes.
                Defaults to False.
        """

        self.graph_instance = graph_instance

        # Add inspection callback to fit options, if inspection is True
        fit_options = self.fit_options.copy()
        if inspection:
            inspection_callback = self.InspectionCallback(self.graph_instance)
            if 'callbacks' in self.fit_options.keys():
                fit_options['callbacks'].append(inspection_callback)
            else:
                fit_options['callbacks'] = [inspection_callback]

        # Set up GNNExplainerOptimizer and optimize with respect to masks
        gnnx_optimizer = GNNExplainerOptimizer(
            self.gnn, graph_instance, **self.gnnexplaineroptimizer_options)
        self.gnnx_optimizer = gnnx_optimizer
        if output_to_explain is not None:
            gnnx_optimizer.output_to_explain = output_to_explain
        gnnx_optimizer.compile(**self.compile_options)
        gnnx_optimizer.fit(graph_instance, **fit_options)

        # Read out information from inspection_callback
        if inspection:
            dict_fields = ['predictions',
                           'total_loss',
                           'edge_mask_loss',
                           'feature_mask_loss',
                           'node_mask_loss']
            inspection_information = {}
            for field in dict_fields:
                if hasattr(inspection_callback, field) and len(getattr(inspection_callback, field)) > 0:
                    inspection_information[field] = getattr(inspection_callback, field)
            return inspection_information

    def get_explanation(self, **kwargs):
        """Returns the explanation (derived from the learned masks) to a decision on the graph,
        which was passed to the `explain` method before.
        Important: The `explain` method should always be called before calling this method.
        Internally this method just calls the `GNNInterface.get_explanation` method
        implemented by the `self.gnn` with the masks found by the `GNNExplainerOptimizer` as parameters.

        Raises:
            Exception: If the `explain` method is not called before, this method raises an Exception.
        Returns:
            The explanation which is returned by `GNNInterface.get_explanation` implemented by the `self.gnn`,
            parametrized by the learned masks.
        """
        if self.graph_instance is None or self.gnnx_optimizer is None:
            raise Exception(
                "You must first call explain on the GNNExplainer instance.")

        edge_mask = self.gnnx_optimizer.get_mask("edge")
        feature_mask = self.gnnx_optimizer.get_mask("feature")
        node_mask = self.gnnx_optimizer.get_mask("node")

        return self.gnn.get_explanation(self.graph_instance,
                                        edge_mask,
                                        feature_mask,
                                        node_mask, **kwargs)

    def present_explanation(self, explanation, **kwargs):
        """Takes an explanation, which was generated by `get_explanation` and presents it.
        Internally this method just calls the `GNNInterface.present_explanation` method
        implemented by the `self.gnn`.

        Args:
            explanation: The explanation (obtained by `get_explanation`) which should be presented.
        Returns:
            A presentation of the given explanation.
        """
        return self.gnn.present_explanation(explanation, **kwargs)

    class InspectionCallback(ks.callbacks.Callback):
        """Callback class to get the inspection information,
        if 'inspection' is set to true for the 'GNNExplainer.explain' method.
        """

        def __init__(self, graph_instance):
            super(GNNExplainer.InspectionCallback, self).__init__()
            self.graph_instance = graph_instance
            self.predictions = []
            self.total_loss = []
            self.edge_mask_loss = []
            self.feature_mask_loss = []
            self.node_mask_loss = []

        def on_epoch_begin(self, epoch, logs=None):
            masked = self.model.call(self.graph_instance).numpy()[0]
            self.predictions.append(masked)

        def on_epoch_end(self, epoch, logs=None):
            """After epoch."""
            index = 0
            losses_list = [loss_iter.numpy() for loss_iter in self.model.losses]
            if self.model.edge_mask_loss_weight > 0:
                self.edge_mask_loss.append(losses_list[index])
                index = index + 1
            if self.model.feature_mask_loss_weight > 0:
                self.feature_mask_loss.append(losses_list[index])
                index = index + 1
            if self.model.node_mask_loss_weight > 0:
                self.node_mask_loss.append(losses_list[index])
            self.total_loss.append(logs['loss'])


class GNNExplainerOptimizer(ks.Model):
    """The `GNNExplainerOptimizer` solves the optimization problem which is used to find masks,
    which then can be used to explain decisions by GNNs.
    """

    def __init__(self, gnn_model, graph_instance,
                 edge_mask_loss_weight=1e-4,
                 edge_mask_norm_ord=1,
                 feature_mask_loss_weight=1e-4,
                 feature_mask_norm_ord=1,
                 node_mask_loss_weight=0.0,
                 node_mask_norm_ord=1,
                 **kwargs):
        """Constructs a `GNNExplainerOptimizer` instance with the given parameters.

        Args:
            gnn_model (GNNInterface): An instance of a class which implements the methods of the `GNNInterface`.
            graph_instance: The graph to which the masks should be found.
            edge_mask_loss_weight (float, optional): The weight of the edge mask loss term in the optimization problem.
                Defaults to 1e-4.
            edge_mask_norm_ord (float, optional): The norm p value for the p-norm, which is used on the edge mask.
                Smaller values encourage sparser masks.
                Defaults to 1.
            feature_mask_loss_weight (float, optional): The weight of the feature mask loss term in the optimization
                problem.
                Defaults to 1e-4.
            feature_mask_norm_ord (float, optional): The norm p value for the p-norm, which is used on the feature mask.
                Smaller values encourage sparser masks.
                Defaults to 1.
            node_mask_loss_weight (float, optional): The weight of the node mask loss term in the optimization problem.
                Defaults to 0.0.
            node_mask_norm_ord (float, optional): The norm p value for the p-norm, which is used on the feature mask.
                Smaller values encourage sparser masks.
                Defaults to 1.
        """
        super(GNNExplainerOptimizer, self).__init__(**kwargs)
        self.gnn_model = gnn_model
        self._edge_mask_dim = self.gnn_model.get_number_of_edges(
            graph_instance)
        self._feature_mask_dim = self.gnn_model.get_number_of_node_features(
            graph_instance)
        self._node_mask_dim = self.gnn_model.get_number_of_nodes(
            graph_instance)
        self.edge_mask = self.add_weight('edge_mask',
                                         shape=[self._edge_mask_dim, 1],
                                         initializer=ks.initializers.Constant(
                                             value=5.),
                                         dtype=tf.float32,
                                         trainable=True)
        self.feature_mask = self.add_weight('feature_mask',
                                            shape=[self._feature_mask_dim, 1],
                                            initializer=ks.initializers.Constant(
                                                value=5.),
                                            dtype=tf.float32,
                                            trainable=True)
        self.node_mask = self.add_weight('node_mask',
                                         shape=[self._node_mask_dim, 1],
                                         initializer=ks.initializers.Constant(
                                             value=5.),
                                         dtype=tf.float32,
                                         trainable=True)
        self.output_to_explain = gnn_model.predict(graph_instance)

        # Configuration Parameters
        self.edge_mask_loss_weight = edge_mask_loss_weight
        self.edge_mask_norm_ord = edge_mask_norm_ord
        self.feature_mask_loss_weight = feature_mask_loss_weight
        self.feature_mask_norm_ord = feature_mask_norm_ord
        self.node_mask_loss_weight = node_mask_loss_weight
        self.node_mask_norm_ord = node_mask_norm_ord

    def call(self, graph_input, training: bool = False, **kwargs):
        """Call GNN model.

        Args:
            graph_input: Graph input.
            training (bool): If training mode. Default is False.

        Returns:
            tf.tensor: Masked prediction of GNN model.
        """
        edge_mask = self.get_mask("edge")
        feature_mask = self.get_mask("feature")
        node_mask = self.get_mask("node")
        return self.gnn_model.masked_predict(graph_input, edge_mask, feature_mask, node_mask, training=training)

    def train_step(self, data):
        """Train step."""

        graph_input = data[0]

        with tf.GradientTape() as tape:
            y_pred = self(graph_input, training=True)  # Forward pass

            # edge_mask loss
            if self.edge_mask_loss_weight > 0:
                self.add_loss(lambda: tf.norm(tf.sigmoid(
                    self.edge_mask), ord=self.edge_mask_norm_ord) * self.edge_mask_loss_weight)
            # feature_mask loss
            if self.feature_mask_loss_weight > 0:
                self.add_loss(lambda: tf.norm(tf.sigmoid(
                    self.feature_mask), ord=self.feature_mask_norm_ord) * self.feature_mask_loss_weight)
            # node_mask loss
            if self.node_mask_loss_weight > 0:
                self.add_loss(lambda: tf.norm(tf.sigmoid(
                    self.node_mask), ord=self.node_mask_norm_ord) * self.node_mask_loss_weight)

            loss = self.compiled_loss(
                self.output_to_explain, y_pred, regularization_losses=self.losses)

        trainable_vars = []
        if self.edge_mask_loss_weight > 0:
            trainable_vars.append(self.edge_mask)
        if self.feature_mask_loss_weight > 0:
            trainable_vars.append(self.feature_mask)
        if self.node_mask_loss_weight > 0:
            trainable_vars.append(self.node_mask)

        gradients = tape.gradient(loss, trainable_vars)
        self.optimizer.apply_gradients(zip(gradients, trainable_vars))
        self.compiled_metrics.update_state(self.output_to_explain, y_pred)
        return {m.name: m.result() for m in self.metrics}

    def get_mask(self, mask_identifier):
        if mask_identifier == "edge":
            return self._get_mask(self.edge_mask, self.edge_mask_loss_weight)
        elif mask_identifier == "feature":
            return self._get_mask(self.feature_mask, self.feature_mask_loss_weight)
        elif mask_identifier == "node":
            return self._get_mask(self.node_mask, self.node_mask_loss_weight)
        raise Exception("mask_identifier must be 'edge', 'feature' or 'node'")

    def _get_mask(self, mask, weight):
        if weight > 0:
            return tf.sigmoid(mask)
        return tf.ones_like(mask)
