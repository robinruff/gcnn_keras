import typing as t

import numpy as np
import tensorflow as tf

from tensorflow.python.keras.engine import compile_utils
from kgcnn.layers.base import GraphBaseLayer
from kgcnn.layers.modules import Dense, OptionalInputEmbedding
from kgcnn.layers.modules import Activation, Dropout
from kgcnn.layers.modules import LazyConcatenate, LazyAverage
from kgcnn.layers.attention import MultiHeadGATV2Layer
from kgcnn.layers.pooling import PoolingLocalEdges
from kgcnn.layers.pooling import PoolingWeightedNodes, PoolingNodes
from kgcnn.xai.base import ImportanceExplanationMixin

ks = tf.keras

# Keep track of model version from commit date in literature.
# To be updated if model is changed in a significant way.
__model_version__ = "2022.12.15"


def shifted_sigmoid(x, shift=5, multiplier=1):
    return ks.backend.sigmoid((x - shift) / multiplier)


class ExplanationSparsityRegularization(GraphBaseLayer):

    def __init__(self,
                 factor: float = 1.0,
                 **kwargs):
        super(ExplanationSparsityRegularization, self).__init__(**kwargs)
        self.factor = factor

    def call(self, inputs, **kwargs):
        r"""Computes a loss from importance scores.

        Args:
            inputs: Importance tensor of shape ([batch], [N], K) .

        Returns:
            None.
        """
        # importances: ([batch], [N], K)
        importances = inputs

        loss = tf.reduce_mean(tf.math.abs(importances))
        self.add_loss(loss * self.factor)


class MEGAN(ks.models.Model, ImportanceExplanationMixin):
    """
    MEGAN: Multi Explanation Graph Attention Network

    This model currently supports graph regression and graph classification problems. It was mainly designed
    with a focus on explainable AI (XAI). Along the main prediction, this model is able to output multiple
    attention-based explanations for that prediction. More specifically, the model outputs node and edge
    attributional explanations (assigning [0, 1] values to ever node / edge of the input graph) in K
    separate explanation channels, where K can be chosen as an independent model parameter.
    """
    __kgcnn_model_version__ = __model_version__

    def __init__(self,
                 # convolutional network related arguments
                 units: t.List[int],
                 activation: str = "kgcnn>leaky_relu",
                 use_bias: bool = True,
                 dropout_rate: float = 0.0,
                 use_edge_features: bool = True,
                 input_embedding: dict = None,
                 # node/edge importance related arguments
                 importance_units: t.List[int] = [],
                 importance_channels: int = 2,
                 importance_activation: str = "sigmoid",  # do not change
                 importance_dropout_rate: float = 0.0,  # do not change
                 importance_factor: float = 0.0,
                 importance_multiplier: float = 10.0,
                 sparsity_factor: float = 0.0,
                 concat_heads: bool = True,
                 # mlp tail end related arguments
                 final_units: t.List[int] = [1],
                 final_dropout_rate: float = 0.0,
                 final_activation: str = 'linear',
                 final_pooling: str = 'sum',
                 regression_limits: t.Optional[t.Tuple[float, float]] = None,
                 regression_reference: t.Optional[float] = None,
                 return_importances: bool = True,
                 **kwargs):
        """
        Args:
            units: A list of ints where each element configures an additional attention layer. The numeric
                value determines the number of hidden units to be used in the attention heads of that layer
            activation: The activation function to be used within the attention layers of the network
            use_bias: Whether the layers of the network should use bias weights at all
            dropout_rate: The dropout rate to be applied after *each* of the attention layers of the network.
            input_embedding: Dictionary of embedding kwargs for input embedding layer.
            use_edge_features: Whether edge features should be used. Generally the network supports the
                usage of edge features, but if the input data does not contain edge features, this should be
                set to False.
            importance_units: A list of ints where each element configures another dense layer in the
                subnetwork that produces the node importance tensor from the main node embeddings. The
                numeric value determines the number of hidden units in that layer.
            importance_channels: The int number of explanation channels to be produced by the network. This
                is the value referred to as "K". Note that this will also determine the number of attention
                heads used within the attention subnetwork.
            importance_factor: The weight of the explanation-only train step. If this is set to exactly
                zero then the explanation train step will not be executed at all (less computationally
                expensive)
            importance_multiplier: An additional hyperparameter of the explanation-only train step. This
                is essentially the scaling factor that is applied to the values of the dataset such that
                the target values can reasonably be approximated by a sum of [0, 1] importance values.
            sparsity_factor: The coefficient for the sparsity regularization of the node importance
                tensor.
            concat_heads: Whether to concat the heads of the attention subnetwork. The default is True. In
                that case the output of each individual attention head is concatenated and the concatenated
                vector is then used as the input of the next attention layer's heads. If this is False, the
                vectors are average pooled instead.
            final_units: A list of ints where each element configures another dense layer in the MLP
                at the tail end of the network. The numeric value determines the number of the hidden units
                in that layer. Note that the final element in this list has to be the same as the dimension
                to be expected for the samples of the training dataset!
            final_dropout_rate: The dropout rate to be applied after *every* layer of the final MLP.
            final_activation: The activation to be applied at the very last layer of the MLP to produce the
                actual output of the network.
            final_pooling: The pooling method to be used during the global pooling phase in the network.
            regression_limits: A tuple where the first value is the lower limit for the expected value range
                of the regression task and teh second value the upper limit.
            regression_reference: A reference value which is inside the range of expected values (best if
                it was in the middle, but does not have to). Choosing different references will result
                in different explanations.
            return_importances: Whether the importance / explanation tensors should be returned as an output
                of the model. If this is True, the output of the model will be a 3-tuple:
                (output, node importances, edge importances), otherwise it is just the output itself
        """
        super(MEGAN, self).__init__(self, **kwargs)
        self.units = units
        self.activation = activation
        self.use_bias = use_bias
        self.dropout_rate = dropout_rate
        self.use_edge_features = use_edge_features
        self.input_embedding = input_embedding
        self.importance_units = importance_units
        self.importance_channels = importance_channels
        self.importance_activation = importance_activation
        self.importance_dropout_rate = importance_dropout_rate
        self.importance_factor = importance_factor
        self.importance_multiplier = importance_multiplier
        self.sparsity_factor = sparsity_factor
        self.concat_heads = concat_heads
        self.final_units = final_units
        self.final_dropout_rate = final_dropout_rate
        self.final_activation = final_activation
        self.final_pooling = final_pooling
        self.regression_limits = regression_limits
        self.regression_reference = regression_reference
        self.return_importances = return_importances

        # ~ MAIN CONVOLUTIONAL / ATTENTION LAYERS
        if self.input_embedding:
            self.embedding_nodes = OptionalInputEmbedding(**self.input_embedding["node"])
        self.attention_layers: t.List[GraphBaseLayer] = []
        for u in self.units:
            lay = MultiHeadGATV2Layer(
                units=u,
                num_heads=self.importance_channels,
                use_edge_features=self.use_edge_features,
                activation=self.activation,
                use_bias=self.use_bias,
                has_self_loops=True,
                concat_heads=self.concat_heads
            )
            self.attention_layers.append(lay)

        self.lay_dropout = Dropout(rate=self.dropout_rate)

        # ~ EDGE IMPORTANCES
        self.lay_act_importance = Activation(activation=self.importance_activation)
        self.lay_concat_alphas = LazyConcatenate(axis=-1)

        self.lay_pool_edges_in = PoolingLocalEdges(pooling_method='mean', pooling_index=0)
        self.lay_pool_edges_out = PoolingLocalEdges(pooling_method='mean', pooling_index=1)
        self.lay_average = LazyAverage()

        # ~ NODE IMPORTANCES
        self.node_importance_units = importance_units + [self.importance_channels]
        self.node_importance_acts = ['relu' for _ in importance_units] + ['linear']
        self.node_importance_layers = []
        for u, act in zip(self.node_importance_units, self.node_importance_acts):
            lay = Dense(
                units=u,
                activation=act,
                use_bias=use_bias
            )
            self.node_importance_layers.append(lay)
            
        self.lay_sparsity = ExplanationSparsityRegularization(factor=self.sparsity_factor)

        # ~ OUTPUT / MLP TAIL END
        self.lay_pool_out = PoolingNodes(pooling_method=self.final_pooling)
        self.lay_concat_out = LazyConcatenate(axis=-1)
        self.lay_final_dropout = Dropout(rate=self.final_dropout_rate)

        self.final_acts = ["relu" for _ in self.final_units]
        self.final_acts[-1] = self.final_activation
        self.final_biases = [True for _ in self.final_units]
        self.final_biases[-1] = False
        self.final_layers = []
        for u, act, bias in zip(self.final_units, self.final_acts, self.final_biases):
            lay = Dense(
                units=u,
                activation=act,
                use_bias=use_bias
            )
            self.final_layers.append(lay)

        # ~ EXPLANATION ONLY TRAIN STEP
        self.bce_loss = ks.losses.BinaryCrossentropy()
        self.compiled_classification_loss = compile_utils.LossesContainer(self.bce_loss)

        self.mse_loss = ks.losses.MeanSquaredError()
        self.mae_loss = ks.losses.MeanAbsoluteError()
        self.compiled_regression_loss = compile_utils.LossesContainer(self.mae_loss)

        if self.regression_limits is not None:
            self.regression_width = np.abs(self.regression_limits[1] - self.regression_limits[0])

    def get_config(self):
        config = super(MEGAN, self).get_config()
        config.update({
            "units": self.units,
            "activation": self.activation,
            "use_bias": self.use_bias,
            "dropout_rate": self.dropout_rate,
            "use_edge_features": self.use_edge_features,
            "importance_units": self.importance_units,
            "importance_channels": self.importance_channels,
            "importance_activation": self.importance_activation,
            "importance_dropout_rate": self.importance_dropout_rate,
            "importance_factor": self.importance_factor,
            "importance_multiplier": self.importance_multiplier,
            "sparsity_factor": self.sparsity_factor,
            "concat_heads": self.concat_heads,
            "final_units": self.final_units,
            "final_dropout_rate": self.final_dropout_rate,
            "final_activation": self.final_activation,
            "final_pooling": self.final_pooling,
            "regression_limits": self.regression_limits,
            "regression_reference": self.regression_reference,
            "return_importances": self.return_importances,
            "input_embedding": self.input_embedding
        })

        return config

    @property
    def doing_regression(self) -> bool:
        return self.regression_limits is not None

    def call(self,
             inputs,
             training: bool = False,
             return_importances: bool = False):

        node_input, edge_input, edge_index_input = inputs

        if self.input_embedding:
            node_input = self.embedding_nodes(node_input, training=training)
        # First of all we apply all the graph convolutional / attention layers. Each of those layers outputs
        # the attention logits alpha additional to the node embeddings. We collect all the attention logits
        # in a list so that we can later sum them all up.
        alphas = []
        x = node_input
        for lay in self.attention_layers:
            # x: ([batch], [N], F)
            # alpha: ([batch], [M], K, 1)
            x, alpha = lay([x, edge_input, edge_index_input])
            if training:
                x = self.lay_dropout(x, training=training)

            alphas.append(alpha)

        # We sum up all the individual layers attention logit tensors and the edge importances are directly
        # calculated by applying a sigmoid on that sum.
        alphas = self.lay_concat_alphas(alphas)
        edge_importances = tf.reduce_sum(alphas, axis=-1, keepdims=False)
        edge_importances = self.lay_act_importance(edge_importances)

        # Part of the final node importance tensor is actually the pooled edge importances, so that is what
        # we are doing here. The caveat here is that we assume undirected edges as two directed edges in
        # opposing direction. To now achieve a symmetric pooling of these edges we have to pool in both
        # directions and then use the average of both.
        pooled_edges_in = self.lay_pool_edges_in([node_input, edge_importances, edge_index_input])
        pooled_edges_out = self.lay_pool_edges_out([node_input, edge_importances, edge_index_input])
        pooled_edges = self.lay_average([pooled_edges_out, pooled_edges_in])

        node_importances_tilde = x
        for lay in self.node_importance_layers:
            node_importances_tilde = lay(node_importances_tilde)

        node_importances_tilde = self.lay_act_importance(node_importances_tilde)

        node_importances = node_importances_tilde * pooled_edges
        self.lay_sparsity(node_importances)

        # Here we apply the global pooling. It is important to note that we do K separate pooling operations
        # were each time we use the same node embeddings x but a different slice of the node importances as
        # the weights! We concatenate all the individual results in the end.
        outs = []
        for k in range(self.importance_channels):
            node_importance_slice = tf.expand_dims(node_importances[:, :, k], axis=-1)
            out = self.lay_pool_out(x * node_importance_slice)

            outs.append(out)

        # out: ([batch], F*K)
        out = self.lay_concat_out(outs)

        # Now "out" is a graph embedding vector of known dimension so we can simply apply the normal dense
        # mlp to get the final output value.
        for lay in self.final_layers:
            out = lay(out)
            if training:
                self.lay_final_dropout(out, training=training)

        if self.doing_regression:
            reference = tf.ones_like(out) * self.regression_reference
            out = out + reference

        # Usually, the node and edge importance tensors would be direct outputs of the model as well, but
        # we need the option to just return the output alone to be compatible with the standard model
        # evaluation pipeline already implemented in the library.
        if self.return_importances or return_importances:
            return out, node_importances, edge_importances
        else:
            return out

    def regression_augmentation(self,
                                out_true: tf.RaggedTensor):
        """
        Given the tensor ([B], 1) of true regression target values, this method will return two derived
        tensors: The first one is a ([B], 2) tensor of normalized distances of the corresponding true
        values to ``self.regression_reference`` and the second is a ([B], 2) boolean mask tensor.
        Args:
            out_true: A tensor of shape ([B], 1) of the true target values of the current batch.
        Returns:
            A tuple of two tensors each with the shape ([B], 2)
        """
        center_distances = tf.abs(out_true - self.regression_reference)
        center_distances = (center_distances * self.importance_multiplier) / (
                0.5 * self.regression_width)

        # So we need two things: a "samples" tensor and a "mask" tensor. We are going to use the samples
        # tensor as the actual ground truth which acts as the regression target during the explanation
        # train step. The binary values of the mask will determine at which positions a loss should
        # actually be calculated for both of the channels

        # The "lower" part is all the samples which have a target value below the reference value.
        lo_mask = tf.where(out_true < self.regression_reference, 1.0, 0.0)
        # The "higher" part all of the samples above reference
        hi_mask = tf.where(out_true > self.regression_reference, 1.0, 0.0)

        samples = tf.concat([center_distances, center_distances], axis=-1)
        mask = tf.concat([lo_mask, hi_mask], axis=-1)

        return samples, mask

    def train_step(self, data):
        """The method which is called for each individual batch of the training step. In this method a forward
        pass of the input data of the batch is performed, the loss is calculated, the gradients of this loss
        w.r.t to the model parameters are calculated and these gradients are used to update the weights of
        the model.

        This custom train step implements the "explanation co-training": Additionally to the main prediction
        loss there is also a loss term which uses only the node importance values to approximate a
        normalized versions of the target values.

        Args:
            data: Tuple of two tensors (X, Y) where X is the batch tensor of all the inputs and Y is the
                batch tensor of the target output values.

        Returns:
            A dictionary whose keys are the names of metrics and the values are the corresponding values
            of these metrics for this iteration of the training.

        """
        if len(data) == 3:
            x, y, sample_weight = data
        else:
            sample_weight = None
            x, y = data

        with tf.GradientTape() as tape:
            if self.return_importances:
                out_true, ni_true, ei_true = y
            else:
                out_true = y

            y_pred = self(x, training=True, return_importances=True)
            out_pred, ni_pred, ei_pred = y_pred
            loss = self.compiled_loss(
                y,
                y_pred if self.return_importances else out_pred,
                sample_weight=sample_weight,
                regularization_losses=self.losses,
            )

            exp_metrics = {}
            if self.importance_factor != 0:
                # ~ explanation loss
                # First of all we need to assemble the approximated model output, which is simply calculated
                # by applying a global pooling operation on the corresponding slice of the node importances.
                # So for each slice (each importance channel) we get a single value, which we then
                # concatenate into an output vector with K dimensions.
                outs = []
                for k in range(self.importance_channels):
                    node_importances_slice = tf.expand_dims(ni_pred[:, :, k], axis=-1)
                    out = self.lay_pool_out(node_importances_slice)

                    outs.append(out)

                # outs: ([batch], K)
                outs = self.lay_concat_out(outs)

                if self.doing_regression:
                    out_true, mask = self.regression_augmentation(out_true)
                    out_pred = outs
                    exp_loss = self.importance_channels * self.compiled_regression_loss(out_true * mask,
                                                                                        out_pred * mask)

                else:
                    out_pred = shifted_sigmoid(
                        outs,

                        # shift=self.importance_multiplier,
                        # multiplier=(self.importance_multiplier / 5)

                        shift=self.importance_multiplier,
                        multiplier=1,
                    )
                    exp_loss = self.compiled_classification_loss(out_true, out_pred)

                exp_loss *= self.importance_factor
                exp_metrics['exp_loss'] = exp_loss
                loss += exp_loss

        trainable_vars = self.trainable_variables
        gradients = tape.gradient(loss, trainable_vars)

        self.optimizer.apply_gradients(zip(gradients, trainable_vars))

        self.compiled_metrics.update_state(
            y,
            out_pred if not self.return_importances else [out_pred, ni_pred, ei_pred],
            sample_weight=sample_weight
        )

        # Return a dict mapping metric names to current value.
        # Note that it will include the loss (tracked in self.metrics).
        return {
            **{m.name: m.result() for m in self.metrics},
            **exp_metrics
        }

    def explain_importances(self,
                            x: t.Sequence[tf.Tensor],
                            **kwargs
                            ) -> t.Tuple[tf.RaggedTensor, tf.RaggedTensor]:
        y, node_importances, edge_importances = self(x, return_importances=True)
        return node_importances, edge_importances
