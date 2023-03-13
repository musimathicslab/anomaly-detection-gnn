from typing import final
import numpy as np
import argparse
import os

import torch
import torch.nn as nn
from torch.optim import Adadelta
from sklearn.utils import class_weight

from pre_processing import MAPPING
from utils.dataset import AnomalyDetectionNodeClassificationDataset
from torch_geometric.loader import RandomNodeLoader

from utils.nc_model import NodeClassificator
from utils.nc_model import train
from utils.nc_model import predict

from sklearn.metrics import accuracy_score
from sklearn.metrics import recall_score
from sklearn.metrics import classification_report
from sklearn.metrics import balanced_accuracy_score
from sklearn.metrics import confusion_matrix

from utils import SEPARATOR
from utils import str2bool
from utils import get_path_of_all
from utils.util import create_directory
from utils.util import plot_confusion_matrix
from utils.util import plot_recall
from utils.util import setup_logger

NAME_DIR: final = '01 - Node Classification'


def node_classification(dataset_path: str, n_neigh, augmentation, hid, num_convs):
    # Get path of all file
    log_path, log_file_path, log_train_path, model_path, result_path, \
        confusion_matrix_path, detection_rate_path = get_path_of_all(
            NAME_DIR, num_neigh=n_neigh, hid=hid, n_convs=num_convs, augmentation=augmentation)

    for directory in [log_path, model_path, confusion_matrix_path, detection_rate_path]:
        create_directory(directory)

    # Init logger
    logger = setup_logger('logger', log_file_path)
    train_logger = setup_logger('training', log_train_path)

    # Create path of training and test dataset
    _file_name_training = 'UNSW-NB15-train.csv'
    _file_path_training = os.path.join(dataset_path, 'raw', _file_name_training)
    _file_name_val = 'UNSW-NB15-val.csv'
    _file_name_testing = 'UNSW-NB15-test.csv'

    # Create training, val and test dataset
    train_dataset = AnomalyDetectionNodeClassificationDataset(
        root=dataset_path,
        file_name=_file_name_training,
        num_neighbors=n_neigh,
        augmentation=augmentation,
        val=False,
        test=False
    )
    val_dataset = AnomalyDetectionNodeClassificationDataset(
        root=dataset_path,
        file_name=_file_name_val,
        num_neighbors=n_neigh,
        val=True,
        test=False
    )
    test_dataset = AnomalyDetectionNodeClassificationDataset(
        root=dataset_path,
        file_name=_file_name_testing,
        num_neighbors=n_neigh,
        val=False,
        test=True
    )

    logger.info(f'Number of features: {train_dataset.num_features}')
    logger.info(f'Number of classes: 10')
    logger.info(SEPARATOR)

    # Define train, val and test loader
    train_data = train_dataset[0]
    val_data = val_dataset[0]
    test_data = test_dataset[0]

    # Log info of train, val and test
    logger.info(train_data)
    logger.info(val_data)
    logger.info(test_data)
    logger.info(SEPARATOR)

    # Define train, val and test loader
    train_loader = RandomNodeLoader(train_data, num_parts=64, shuffle=True)
    val_loader = RandomNodeLoader(val_data, num_parts=64, shuffle=True)
    test_loader = RandomNodeLoader(test_data, num_parts=64, shuffle=True)

    # Define model
    logger.info(f'N. Convs: {num_convs}')
    logger.info(f'N. Hidden Channels: {hid}')
    logger.info(SEPARATOR)
    train_logger.info(f'N. Convs: {num_convs}')
    train_logger.info(f'N. Hidden Channels: {hid}')
    train_logger.info(SEPARATOR)
    model = NodeClassificator(
        dataset=train_data,
        num_classes=2,
        num_convs=num_convs,
        hid=hid,
        alpha=0.5,
        theta=0.7,
        dropout=0.5
    )

    # Use GPU
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model.to(device)
    logger.info(model)
    logger.info(SEPARATOR)

    # Define loss function and optmizer
    y = train_dataset[0].y.numpy()
    class_weights = class_weight.compute_class_weight('balanced', classes=np.unique(y), y=y)
    class_weights = torch.tensor(class_weights, dtype=torch.float)
    criterion = nn.CrossEntropyLoss(weight=class_weights.to(device))
    y_val = val_dataset[0].y.numpy()
    class_weights_val = class_weight.compute_class_weight('balanced', classes=np.unique(y_val), y=y_val)
    class_weights_val = torch.tensor(class_weights_val, dtype=torch.float)
    criterion_val = nn.CrossEntropyLoss(weight=class_weights_val.to(device))

    optimizer = Adadelta(model.parameters())

    # Check if model is trained
    model_name = f'gc_model_test_attack_{n_neigh}_hid_{hid}_convs_{num_convs}{"_aug" if augmentation else ""}'
    model_trained_path = os.path.join(model_path, f'{model_name}.h5')
    if os.path.exists(model_trained_path):
        model.load_state_dict(torch.load(model_trained_path))
    # Train model if is not trained
    else:
        train(
            model,
            train_loader,
            criterion,
            criterion_val,
            optimizer,
            device,
            model_path,
            logger=train_logger,
            epochs=1000,
            model_name=model_name,
            evaluation=True,
            val_dataloader=val_loader,
            patience=20
        )
        train_logger.info(SEPARATOR)

    # Test model
    y_true, y_pred = predict(
        model,
        test_loader,
        device
    )

    logger.info(f'Accuracy on test: {accuracy_score(y_true, y_pred)}')
    logger.info(f'Balanced accuracy on test: {balanced_accuracy_score(y_true, y_pred)}')
    logger.info(f'\n{classification_report(y_true, y_pred, digits=3)}')

    # Plot results
    image_name = f'node-classification_{n_neigh}' \
                 f'_{proto_type}' \
                 f'_hid_{hid}_convs_{num_convs}' \
                 f'{"_aug" if augmentation else ""}' \
                 f'.png'
    # Confusion Matrix
    cm = confusion_matrix(y_true, y_pred, normalize="true")
    plot_confusion_matrix(cm, MAPPING.keys(), os.path.join(confusion_matrix_path, image_name))
    # Detection rate
    recall = recall_score(y_true, y_pred, average=None)
    plot_recall(MAPPING.keys(), recall, os.path.join(detection_rate_path, image_name))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument('-aug', dest='aug', action='store',
                        type=str2bool, default=True, help='apply or not augmentation on data')
    parser.add_argument('-neigh', dest='neigh', action='store',
                        type=int, default=0, help='define number of neighborhood')
    parser.add_argument('-hid', dest='hid', action='store',
                        type=int, default=2048, help='define number of hidden channels')
    parser.add_argument('-n_convs', dest='n_convs', action='store',
                        type=int, default=16, help='define number of convolution blocks')

    args = parser.parse_args()

    node_classification(os.path.join(os.getcwd(), 'dataset'), args.neigh, args.aug, args.hid, args.n_convs)
