import tensorflow as tf
import matplotlib.pyplot as plt
import numpy as np
import time
import os
import kgcnn.utils.learning
import argparse

from copy import deepcopy
from tensorflow_addons import optimizers
from sklearn.preprocessing import StandardScaler
from kgcnn.utils.loss import ScaledMeanAbsoluteError, ScaledRootMeanSquaredError
from sklearn.model_selection import KFold
from sklearn.utils import shuffle
from kgcnn.data.datasets.qm9 import QM9Dataset
from kgcnn.io.loader import NumpyTensorList
from kgcnn.utils.models import ModelSelection
from kgcnn.utils.data import save_json_file, load_json_file
from kgcnn.hyper.datasets import DatasetHyperSelection

# Input arguments from command line.
# A hyper-parameter file can be specified to be loaded containing a python dict for hyper.
parser = argparse.ArgumentParser(description='Train a graph network on QM9 dataset.')
parser.add_argument("--model", required=False, help="Graph model to train.", default="Schnet")
parser.add_argument("--hyper", required=False, help="Filepath to hyper-parameter config.", default=None)
args = vars(parser.parse_args())
print("Input of argparse:", args)

# Model identification
model_name = args["model"]
ms = ModelSelection()
make_model = ms.make_model(model_name)

# Hyper-parameter identification
if args["hyper"] is None:
    # Default hyper-parameter from DatasetHyperSelection if available
    hs = DatasetHyperSelection()
    hyper = hs.get_hyper("QM9", model_name)
else:
    hyper = load_json_file(args["hyper"])

# Loading QM9 Dataset
hyper_data = hyper['data']
dataset = QM9Dataset()
# Modifications to set range and angle indices.
if "range" in hyper_data:
    dataset.set_range(**hyper_data['range'])
if "requires_angles" in hyper_data:
    if hyper_data["requires_angles"]:
        dataset.set_angle()
data_name = dataset.dataset_name
data_length = dataset.length
target_names = dataset.target_names

# Prepare actual training data.
data_points_to_use = hyper_data['data_points_to_use'] if "data_points_to_use" in hyper_data else 133885
target_indices = np.array(hyper_data['target_indices'], dtype="int")
target_unit_conversion = np.array(hyper_data['target_unit_conversion'])
data_unit = hyper_data["target_unit"] if "target_unit" in hyper_data else [""]*len(target_indices)
data_selection = shuffle(np.arange(data_length))[:data_points_to_use]

# Using NumpyTensorList() to make tf.Tensor objects from a list of arrays.
dataloader = NumpyTensorList(*[getattr(dataset, x['name']) for x in hyper['model']['inputs']])[data_selection]
labels = dataset.graph_labels[data_selection][:, target_indices] * target_unit_conversion
target_names = [target_names[x] for x in target_indices]

# Data-set split
execute_splits = hyper_data['execute_splits']  # All splits may be too expensive for QM9
# For validation, use a KFold() split.
kf = KFold(n_splits=10, random_state=None, shuffle=True)
split_indices = kf.split(X=np.arange(len(labels))[:, None])

# Set learning rate and epochs
hyper_train = hyper['training']
epo = hyper_train['fit']['epochs']
epostep = hyper_train['fit']['validation_freq']
batch_size = hyper_train['fit']['batch_size']

train_loss = []
test_loss = []
mae_5fold = []
splits_done = 0
model, scaler, xtest, ytest, mae_valid = None, None, None, None, None
for train_index, test_index in split_indices:
    # Only do execute_splits out of the 10-folds
    if splits_done >= execute_splits:
        break
    # Make model.
    model = make_model(**hyper['model'])

    # Select train and test data.
    is_ragged = [x['ragged'] for x in hyper['model']['inputs']]
    xtrain, ytrain = dataloader[train_index].tensor(ragged=is_ragged), labels[train_index]
    xtest, ytest = dataloader[test_index].tensor(ragged=is_ragged), labels[test_index]

    # Normalize training and test targets. We will expand this to distinguish between all targets of QM9 in the future.
    scaler = StandardScaler(with_std=True, with_mean=True, copy=True)
    ytrain = scaler.fit_transform(ytrain)
    ytest = scaler.transform(ytest)

    # Set optimizer from serialized hyper-dict.
    optimizer = tf.keras.optimizers.get(deepcopy(hyper_train['optimizer']))
    cbks = [tf.keras.utils.deserialize_keras_object(x) for x in hyper_train['callbacks']]

    # Compile Metrics and loss. Use a scaled metric to logg the unscaled targets in fit().
    mae_metric = ScaledMeanAbsoluteError((1, 3))
    rms_metric = ScaledRootMeanSquaredError((1, 3))
    if scaler.scale_ is not None:
        mae_metric.set_scale(np.expand_dims(scaler.scale_, axis=0))
        rms_metric.set_scale(np.expand_dims(scaler.scale_, axis=0))
    model.compile(loss='mean_absolute_error',
                  optimizer=optimizer,
                  metrics=[mae_metric, rms_metric])
    print(model.summary())

    # Start and time training
    start = time.process_time()
    hist = model.fit(xtrain, ytrain,
                     callbacks=cbks,
                     validation_data=(xtest, ytest),
                     **hyper_train['fit']
                     )
    stop = time.process_time()
    print("Print Time for taining: ", stop - start)

    # Get loss from history
    train_mae = np.array(hist.history['mean_absolute_error'])
    train_loss.append(train_mae)
    val_mae = np.array(hist.history['val_mean_absolute_error'])
    test_loss.append(val_mae)
    mae_valid = np.mean(val_mae[-5:], axis=0)
    mae_5fold.append(mae_valid)

    splits_done += 1

# Make output directories
os.makedirs(data_name, exist_ok=True)
filepath = os.path.join(data_name, hyper['model']['name'])
os.makedirs(filepath, exist_ok=True)

# Plot training- and test-loss vs epochs for all splits.
plt.figure()
for x in train_loss:
    plt.plot(np.arange(x.shape[0]), x, c='red', alpha=0.85)
for y in test_loss:
    plt.plot((np.arange(len(y)) + 1) * epostep, y, c='blue', alpha=0.85)
plt.scatter([train_loss[-1].shape[0]], [np.mean(mae_5fold)],
            label=r"Test: {0:0.4f} $\pm$ {1:0.4f} ".format(np.mean(mae_5fold), np.std(mae_5fold)), c='blue')
plt.xlabel('Epochs')
plt.ylabel('Accuracy')
plt.title('QM9 Loss')
plt.legend(loc='upper right', fontsize='medium')
plt.savefig(os.path.join(filepath, 'mae_qm9.png'))
plt.show()

# Plot predicted targets vs actual targets for last split. This will be adapted for all targets in the future.
true_test = scaler.inverse_transform(ytest)
pred_test = scaler.inverse_transform(model.predict(xtest))
mae_last = np.mean(np.abs(true_test - pred_test), axis=0)
plt.figure()
for i in range(true_test.shape[-1]):
    plt.scatter(pred_test[:, i], true_test[:, i], alpha=0.3,
                label=target_names[i] + " MAE: {0:0.4f} ".format(mae_last[i]) + "[" + data_unit[i] + "]")
plt.plot(np.arange(np.amin(true_test), np.amax(true_test), 0.05),
         np.arange(np.amin(true_test), np.amax(true_test), 0.05), color='red')
plt.xlabel('Predicted Last Split')
plt.ylabel('Actual')
plt.legend(loc='upper left', fontsize='x-small')
plt.savefig(os.path.join(filepath, 'predict_qm9.png'))
plt.show()

# Save hyper-parameter again, which were used for this fit.
save_json_file(hyper, os.path.join(filepath, "hyper.json"))

# Save keras-model to output-folder.
model.save(os.path.join(filepath, "model"))

# Save original data indices of the splits.
all_test_index = []
for train_index, test_index in split_indices:
    all_test_index.append([data_selection[train_index], data_selection[test_index]])
np.savez(os.path.join(filepath, "kfold_splits.npz"), all_test_index)