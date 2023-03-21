import numpy as np
import tensorflow as tf


@tf.keras.utils.register_keras_serializable(package='kgcnn', name='LinearWarmupExponentialDecay')
class LinearWarmupExponentialDecay(tf.optimizers.schedules.LearningRateSchedule):
    r"""This schedule combines a linear warmup with an exponential decay.
    Combines :obj:` tf.optimizers.schedules.PolynomialDecay` with an actual increase during warmup
    and :obj:`tf.optimizers.schedules.ExponentialDecay` after.

    Introduced by `DimeNetPP <https://arxiv.org/abs/2011.14115>`__ .

    The closed-from learning rate schedule for learning rate :math:`\eta` for :math:`s_0` warmup and decay
    :math:`S_\tau` is given as a function of steps :math:`s` below (deduced from documentation of keras modules).

    .. math::

        \eta (s) = \eta_0 \;  \gamma ^ {s / S_\tau}  \; [1 - \frac{s_0-1}{s_0} \frac{s_0 - \text{min}(s_0, S)}{s_0}]

    This class has been updated to be compatible with `GemNet <https://arxiv.org/abs/2106.08903>`__ training.

    """

    def __init__(self, learning_rate, warmup_steps, decay_steps, decay_rate, staircase: bool = False):
        """Initialize class.

        Args:
            learning_rate: Learning rate to use.
            warmup_steps: Number of warmup steps.
            decay_steps: Number of which to decay the learning rate.
            decay_rate: Factor to reduce the learning rate.
            staircase (bool): If True use staircase decay and not (continuous) exponential decay.
        """
        super().__init__()
        self._input_config_settings = {"learning_rate": learning_rate, "warmup_steps": warmup_steps,
                                       "decay_steps": decay_steps, "decay_rate": decay_rate, "staircase": staircase}
        self.warmup = tf.optimizers.schedules.PolynomialDecay(
            1 / warmup_steps, warmup_steps, end_learning_rate=1)
        self.decay = tf.optimizers.schedules.ExponentialDecay(
            learning_rate, decay_steps, decay_rate, staircase=staircase)

    def __call__(self, step):
        """Decay learning rate as a functions of steps.

        Args:
            step: Current step of training.

        Returns:
            float: New learning rate.
        """
        return self.warmup(step) * self.decay(step)

    @property
    def initial_learning_rate(self):
        return self.decay.initial_learning_rate

    @initial_learning_rate.setter
    def initial_learning_rate(self, value):
        self.decay.initial_learning_rate = value

    def get_config(self):
        """Get config for this class."""
        config = {}
        config.update(self._input_config_settings)
        return config
