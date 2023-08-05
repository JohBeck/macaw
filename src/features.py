import cv2 as cv
import numpy as np

from imutils.video import FPS
import time

import utils

TRACKING_THRESHOLD = 0.95
MATCHING_THRESHOLD = 20
MATCH_DISTANCE = 0.7

TRACKING_THRESHOLDS = {"hauptgebaeude_right": TRACKING_THRESHOLD,
                       "hauptgebaeude_back": TRACKING_THRESHOLD,
                       "hauptgebaeude_left": TRACKING_THRESHOLD,
                       "hauptgebaeude_front": TRACKING_THRESHOLD,
                       "karo5_right": TRACKING_THRESHOLD,
                       "karo5_back": TRACKING_THRESHOLD,
                       "karo5_left": TRACKING_THRESHOLD,
                       "karo5_front": TRACKING_THRESHOLD,
                       "piloty_right": TRACKING_THRESHOLD,
                       "piloty_back": TRACKING_THRESHOLD,
                       "piloty_left": TRACKING_THRESHOLD,
                       "piloty_front": TRACKING_THRESHOLD,
                       "ULB_right": TRACKING_THRESHOLD,
                       "ULB_back": TRACKING_THRESHOLD,
                       "ULB_left": TRACKING_THRESHOLD,
                       "ULB_front": TRACKING_THRESHOLD}
MATCHING_THRESHOLDS = {"hauptgebaeude_right": MATCHING_THRESHOLD,
                       "hauptgebaeude_back": MATCHING_THRESHOLD,
                       "hauptgebaeude_left": MATCHING_THRESHOLD,
                       "hauptgebaeude_front": MATCHING_THRESHOLD,
                       "karo5_right": MATCHING_THRESHOLD,
                       "karo5_back": MATCHING_THRESHOLD,
                       "karo5_left": MATCHING_THRESHOLD,
                       "karo5_front": MATCHING_THRESHOLD,
                       "piloty_right": MATCHING_THRESHOLD,
                       "piloty_back": MATCHING_THRESHOLD,
                       "piloty_left": MATCHING_THRESHOLD,
                       "piloty_front": MATCHING_THRESHOLD,
                       "ULB_right": MATCHING_THRESHOLD,
                       "ULB_back": MATCHING_THRESHOLD,
                       "ULB_left": MATCHING_THRESHOLD,
                       "ULB_front": MATCHING_THRESHOLD}


def compute_features_sift(img: np.ndarray) -> tuple[cv.KeyPoint, np.ndarray]:
    # SIFT: https://docs.opencv.org/4.x/da/df5/tutorial_py_sift_intro.html

    sift = cv.SIFT_create()
    pic = cv.normalize(img, None, 0, 255, cv.NORM_MINMAX)
    kp, des = sift.detectAndCompute(pic, None)

    return kp, des


def compute_features_harris(img: np.ndarray, threshold=0.01):
    # Harris : https://docs.opencv.org/3.4/dc/d0d/tutorial_py_features_harris.html

    dst = cv.cornerHarris(img, 2, 3, 0.04)

    # result is dilated for marking the corners, not important
    dst = cv.dilate(dst, None)

    # Threshold for an optimal value, it may vary depending on the image.
    img2 = img.copy()
    img2[dst > threshold * dst.max()] = 0
    return np.argwhere(dst > threshold * dst.max()), img2


def compute_features_orb(img: np.ndarray) -> tuple[cv.KeyPoint, np.ndarray]:
    # ORB: https://docs.opencv.org/3.4/d1/d89/tutorial_py_orb.html

    # Initiate ORB detector
    orb = cv.ORB_create()

    # find the keypoints with ORB
    kp = orb.detect(img, None)

    # compute the descriptors with ORB
    kp, des = orb.compute(img, kp)
    # kp, des = orb.detectAndCompute(img, None)
    return kp, des


def get_points_from_matches(matches_accepted, kp, kp2):
    pts1 = np.float32([kp[m.queryIdx].pt for m in matches_accepted]).reshape(-1, 1, 2)
    pts2 = np.float32([kp2[m.trainIdx].pt for m in matches_accepted]).reshape(-1, 1, 2)
    return pts1, pts2


def bounding_box(pts: list[np.array((2, 1))]) -> np.array((-1, 1, 2)):
    br = cv.boundingRect(np.array(pts, dtype='int32').reshape((-1, 2)))
    return np.array([[[br[0], br[1]]], [[br[2], br[1]]], [[br[2], br[3]]], [[br[0], br[3]]]])


def convex_hull(pts: list[np.array((2, 1))]) -> np.array((-1, 1, 2)):
    return cv.convexHull(np.array(pts, dtype='int32').reshape((-1, 2)))  # .reshape((-1, 2))


# https://docs.opencv.org/3.4/d1/de0/tutorial_py_feature_homography.html
def match_flann_SIFT(des, des2):
    FLANN_INDEX_KDTREE = 1
    index_params = dict(algorithm=FLANN_INDEX_KDTREE, trees=5)
    search_params = dict(checks=50)

    flann = cv.FlannBasedMatcher(index_params, search_params)
    matches_accepted = []

    matches = flann.knnMatch(des, des2, k=2)
    # store all the good matches as per Lowe's ratio test.
    for m, n in matches:
        if m.distance < MATCH_DISTANCE * n.distance:
            matches_accepted.append(m)
    return matches_accepted


def match_flann_ORB(des, des2):
    search_params = {}
    index_params = dict(algorithm=6,
                        table_number=6,  # was 12
                        key_size=12,  # was 20
                        multi_probe_level=1)  # was 2

    flann = cv.FlannBasedMatcher(index_params, search_params)
    matches_accepted = []

    matches = flann.knnMatch(des, des2, k=2)
    # store all the good matches as per Lowe's ratio test.
    for tmp in matches:
        if len(tmp) != 2:
            continue
        m, n = tmp
        if m.distance < MATCH_DISTANCE * n.distance:
            matches_accepted.append(m)
    return matches_accepted


def estimate_homography(pts_src, points_st):
    m, mask = cv.findHomography(pts_src, points_st, cv.RANSAC, 5.0, confidence=0.95)  # returns M, mask
    return m, mask


def match(des, masks, feature_type):
    matches_best = None
    matches_best_nr = -1
    mask_id = 0

    for idx, mask in enumerate(masks):
        if feature_type == 'SIFT':
            matches_accepted = match_flann_SIFT(des, mask.des)
        else:
            matches_accepted = match_flann_ORB(des, mask.des)

        if len(matches_accepted) > matches_best_nr:
            matches_best = matches_accepted
            matches_best_nr = len(matches_accepted)
            mask_id = idx

    return matches_best, mask_id  # Support for list of masks -> return best match


def calc_bounding_box(matches_accepted, mask, src_pts, mask_pts, label):
    threshold = MATCHING_THRESHOLD

    if label in MATCHING_THRESHOLDS:
        threshold = MATCHING_THRESHOLDS[label]

    # With enough matches: Estimate Homography
    if len(matches_accepted) > 2 * threshold:
        m, msk = estimate_homography(src_pts, mask_pts)
        dst = cv.perspectiveTransform(mask.box_points, np.linalg.pinv(m))
        return dst

    # TODO: If there is no homography use detector
    # With slightly fewer hits: Fit bounding box
    if len(matches_accepted) > int(0.75 * threshold):
        return bounding_box(mask_pts)

    # Else: No matches
    return None


def track(img_old, img_new, pts_old, pts_mask_old, label):
    threshold = TRACKING_THRESHOLD

    if label in TRACKING_THRESHOLDS:
        threshold = TRACKING_THRESHOLDS[label]

    pts_new, st, err = cv.calcOpticalFlowPyrLK(img_old, img_new, pts_old, None, minEigThreshold=0.1)
    good_new = None
    mask_new = None

    valid = False  # Check if enough points are tracked
    if pts_new is not None:
        good_new = pts_new.get()[st.get()[:, 0] == 1]
        mask_new = pts_mask_old[st.get()[:, 0] == 1]

    # TODO: Check succesfull tracking condition  again
    # TODO: Maybe try to track detector results as well!
    if float(len(good_new))/float(len(pts_old)) >= threshold and len(good_new) > 15:
        valid = True

    return good_new, mask_new, valid
