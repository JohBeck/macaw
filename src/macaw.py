import argparse
import sys

import methods.object_detection as object_detection
import methods.train as train
import methods.labeling as labeling
import utils_macaw as utils
import features
import rendering


import numpy as np
import cv2 as cv
import time

from methods.viewing import ImageViewer
from methods.eval import TorchImageProvider, PredictionsProvider
from utils.weights_loader import WeightsLoader


def macaw(
        input_file,
        path_masks,
        path_overlays,
        feature_type,
        model_checkpoint,
        annotations_path,
        device,
):
    frame_width = 450
    masks = utils.load_masks(path_masks)
    overlays = utils.load_overlays(path_overlays, int(0.75 * frame_width))

    if type(input_file) is int:
        fvs = utils.webcam_handler()  #
    else:
        fvs = utils.vid_handler(input_file)

        match feature_type:
            case "ORB":
                compute_feature = features.compute_features_orb
            case "SIFT":
                compute_feature = features.compute_features_sift
            case _:
                compute_feature = features.compute_features_sift

    last_frame_gray = None  # gray  # cv.UMat((1, 1))
    pts_f = None
    pts_m = None
    mask_id = None
    matches = None

    count = -1

    matching_rate = 15
    # loop over frames from the video file stream
    model_predictor = PredictionsProvider(model_checkpoint, annotations_path, device)
    while True:  # fvs.more():
        count += 1
        bbox = None
        crop_offset = np.array([[[0, 0]]])

        # grab the frame from the threaded video file stream, resize
        # it, and convert it to grayscale (while still retaining 3
        # channels)
        time_start = time.time()

        frame = fvs.read()
        if frame is None:
            break

        frame = utils.resize(frame, width=frame_width)
        frame_size = frame.shape
        frame_umat = cv.UMat(frame)
        frame_gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        frame_gray = cv.UMat(cv.GaussianBlur(frame_gray, (5, 5), 0))

        valid = False

        # tracking:
        if count % matching_rate != 0 and pts_f is not None and len(pts_f) > 0:
            pts_f, pts_m, valid = features.track(
                last_frame_gray, frame_gray, pts_f, pts_m
            )
            bbox = features.calc_bounding_box(matches, masks[mask_id], pts_f, pts_m)

        last_frame_gray = frame_gray

        contours = []
        # Boxes are in the format XYXY
        if not valid:
            # todo: voting for labels of multiple previous frames
            hit, box_pixel, label, score = model_predictor(frame, silent=False)

            if hit and (box_pixel[2] - box_pixel[0]) * (box_pixel[3] - box_pixel[1]) > 0:
                # hit and non-zero patch
                # Add the predicted bounding box from the model to the list for rendering
                contours.append((
                    np.array([[[box_pixel[0], box_pixel[1]]],
                              [[box_pixel[2], box_pixel[1]]],
                              [[box_pixel[2], box_pixel[3]]],
                              [[box_pixel[0], box_pixel[3]]], ])
                    , (255, 0, 0)))

                # Crop the img
                crop_offset = np.array([[[box_pixel[0], box_pixel[1]]]])
                cropped = utils.crop_img(frame, *box_pixel)  # Test cropping and apply
                frame_gray = cv.UMat(
                    cv.GaussianBlur(cv.cvtColor(cropped, cv.COLOR_BGR2GRAY), (5, 5), 0)
                )

                # match the features of the cropped img
                kp, des = compute_feature(frame_gray)
                matches, mask_id = features.match(des, masks)
                pts_f, pts_m = features.get_points_from_matched_keypoints(
                    matches, kp, masks[mask_id].kp
                )

                # gt the bounding box (None, with/without homography -> depends on number of hits)
                bbox = features.calc_bounding_box(matches, masks[mask_id], pts_f, pts_m)

        if bbox is not None:
            bbox += crop_offset  # bbox is calculated of the cropped image -> global coordinates by adding the offset
            contours.append((np.int32(bbox), (0, 255, 0)))
            # frame = rendering.render_fill_contours(frame_umat, np.int32(bbox))

        # Render all contours
        for c in contours:
            frame_umat = rendering.render_contours(frame_umat, c[0], color=c[1])
            frame_umat = rendering.render_fill_contours(frame_umat, c[0], color=c[1])

        # Add Meta data:
        if len(contours) > 0:
            label = "mask_Hauptgebaeude_no_tree"  # TODO: remove when labels are fixed
            frame_umat = rendering.render_metadata(frame_umat, label, overlays[label])  # label

        # show the frame and update the FPS counter
        rendering.render_text(frame_umat, "FPS: {:.2f}".format(1.0 / (time.time() - time_start)),
                              (10, frame_size[0] - 10),)

        # display the size of the queue on the frame
        cv.imshow("frame", frame_umat)
        cv.waitKey(1)

    # do a bit of cleanup
    cv.destroyAllWindows()
    fvs.stop()
    return


if __name__ == "__main__":
    # macaw()
    parser = argparse.ArgumentParser("macaw")
    parser.add_argument("--config", help="The config file.")
    args = parser.parse_args()
    if "config" not in args:
        print("Failed to load config file.")
        exit(-1)
    cfg = utils.read_yaml(args.config)
    match cfg["METHOD"]["NAME"]:
        case "execute":
            weights_loader = WeightsLoader(cfg["VIDEO"]["MODEL_CHECKPOINT"])
            weights_loader()
            execute_cfg = dict(
                input_file=cfg["VIDEO"]["FILE_NAME"],
                path_masks=cfg["VIDEO"]["MASKS_PATH"],
                path_overlays=cfg["VIDEO"]["OVERLAYS_PATH"],
                feature_type=cfg["VIDEO"]["FEATURE_TYPE"],
                model_checkpoint=cfg["VIDEO"]["MODEL_CHECKPOINT"],
                annotations_path=cfg["VIDEO"]["ANNOTATIONS_PATH"],
                device=cfg["VIDEO"]["DEVICE"],
            )
            macaw(**execute_cfg)
        case "train":
            object_detection.train(cfg)
        case "view":
            weights_loader = WeightsLoader(cfg["DATA"]["MODEL_CHECKPOINT"])
            weights_loader()
            eval_cfg = dict(
                annotations=cfg["DATA"]["ANNOTATIONS_PATH"],
                model_checkpoint=cfg["EVALUATION"]["MODEL_CHECKPOINT"],
                device=cfg["EVALUATION"]["DEVICE"],
                batch_size=cfg["EVALUATION"]["BATCH_SIZE"],
                num_workers=cfg["EVALUATION"]["NUM_WORKERS"],
            )
            image_provider = TorchImageProvider(**eval_cfg)
            viewer = ImageViewer(image_provider)
            viewer()
        case "label":
            labeler = labeling.Labeler(cfg["DATA"]["ANNOTATIONS_PATH"])
            # We NEED to load all data, otherwise we won't have correct labels
            labeler(
                cfg["DATA"]["PATH"],
                cfg["DATA"]["SUPERCATEGORIES"],
                cfg["DATA"]["SUBCATEGORIES"],
                cfg["METHOD"]["MODE"],
            )
        case _:
            print(
                f"Unknown method: {cfg['METHOD']['NAME']}. Please use one of the following: train, visualise, execute, label"
            )
            exit(-1)
