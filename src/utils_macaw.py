import os
import torchvision.transforms as transforms
import numpy as np
import yaml
import features
import glob
from pathlib import Path

from PIL import Image

import argparse
from imutils.video import FileVideoStream
from imutils.video import WebcamVideoStream

import cv2 as cv
import pickle
import imutils
from collections import namedtuple

Mask = namedtuple("Mask", ["name", "kp", "des", "box", "box_points"])
DATA = namedtuple("DATA", ["name", "id", "address", "info", "box_size"])

METADATA = {}


def vid_handler(file):
    return FileVideoStream(file, queue_size=128).start()


def webcam_handler():
    return WebcamVideoStream(src=0).start()


def save_descriptor_to_file(file, data):
    pickle.dump(file, data)


def load_descriptor_from_file(file):
    return pickle.load(file)


def load_img(filename: str, size: tuple = None) -> tuple[np.ndarray, np.ndarray]:
    img = cv.imread(filename)
    if size:
        img = resize(img, size[1])
        # scale_percent = int(100 * size[0] / img.shape[0])
        # scale_percent = max(scale_percent, int(100 * size[1] / img.shape[1]))
        #
        # width = int(img.shape[1] * scale_percent / 100)
        # height = int(img.shape[0] * scale_percent / 100)
        #
        # img = cv.resize(img, (width, height), interpolation=cv.INTER_AREA)

    # gray = cv.cvtColor(img,cv.COLOR_BGR2GRAY)
    gray = np.float32(cv.cvtColor(img, cv.COLOR_BGR2GRAY))
    return img, gray


def crop_img(
    img: np.ndarray, min_x: int, min_y: int, max_x: int, max_y: int
) -> np.ndarray:
    """
    min_y: int, min_x: int, max_y: int, max_x: int
    """
    return img[min_x:max_x, min_y:max_y, :]


def resize(img, width):
    return imutils.resize(img, width=width)


def to_grayscale(img):
    return cv.cvtColor(img, cv.COLOR_BGR2GRAY)


def load_masks(path, compute_feature=features.compute_features_sift):
    """
    Load all images from 'path', calculate keypoints and feature-descriptors and return them aas list(MASK)
    """
    masks = {}
    for filename in glob.glob(path + "*.jpg"):
        img_mask, gray_mask = load_img(filename)
        kp_mask, des_mask = compute_feature(img_mask)
        h, w = gray_mask.shape
        name = Path(filename).stem
        masks[name] = Mask(
            name,
            kp_mask,
            des_mask,
            img_mask.shape[:2],
            np.float32([[0, 0], [0, h - 1], [w - 1, h - 1], [w - 1, 0]]).reshape(
                -1, 1, 2
            ),
        )
        METADATA[name] = DATA(
            "Dummy", "-1", "Holzweg 42", "Geht dich gar nichts an!", (200, 90)
        )
    return masks


def load_overlays(path, width=None):
    overlays = {}
    for filename in glob.glob(path + "*.png"):
        img, _ = load_img(filename)
        if width is not None:
            img = resize(img, width=width)
        overlays[Path(filename).stem] = img
    return overlays


def load_data(path_to_data):
    """
    This function loads all images from the data directory.
    Each new directory creates a new label, so images from
    the same category should be in the same directory
    """
    labels = []
    images = []
    label = -1
    subdir = ""
    for subdirs, _, files in os.walk(path_to_data):
        if subdirs != "data":
            for file in files:
                if subdirs != subdir:
                    label += 1
                    subdir = subdirs
                image = Image.open(os.path.join(subdirs, file))
                preprocess = transforms.Compose(
                    [
                        transforms.Resize(299),
                        transforms.CenterCrop(299),
                        transforms.ToTensor(),
                        transforms.Normalize(-127.5, 127.5),
                    ]
                )
                input_tensor = preprocess(image).to("cuda")
                if input_tensor.shape != (3, 299, 299):
                    continue
                labels.append(label)
                images.append(input_tensor)
    return images, np.array(labels)


def gen_triplet_dataset(labels, batch_size, batch_amount):
    """
    This function generates a dataset based on triplets. It returns
    a numpy array of size [batch_amount, batch_size, 3]. Each entry
    is an index describing the position of the data based on the
    labels input
    """
    dataset = []
    max_label = np.max(labels)
    for _ in range(batch_amount):
        batch = []
        for b in range(batch_size):
            label1 = np.random.randint(0, max_label + 1)
            label2 = np.random.randint(0, max_label + 1)
            while label1 == label2:
                label2 = np.random.randint(0, max_label + 1)
            label1_pos = np.where(labels == label1)
            l1_min = np.min(label1_pos)
            l1_max = np.max(label1_pos)
            label2_pos = np.where(labels == label2)
            l2_min = np.min(label2_pos)
            l2_max = np.max(label2_pos)
            anchor = np.random.randint(l1_min, l1_max + 1)
            positive = np.random.randint(l1_min, l1_max + 1)
            while positive == anchor and l1_min != l1_max:
                positive = np.random.randint(l1_min, l1_max + 1)
            negative = np.random.randint(l2_min, l2_max + 1)
            batch.append([anchor, positive, negative])
        dataset.append(np.array(batch))
    return np.array(dataset)


def read_yaml(filepath):
    """
    Reads in a yaml config file from a filepath
    """
    with open(filepath, "r") as file:
        data = yaml.safe_load(file)
    return data