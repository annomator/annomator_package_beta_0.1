# Copyright 2019 Annomator Written by Arend Smits
# Copyright 2019 The TensorFlow Authors. All Rights Reserved.
# Licensed under the Apache License, Version 2.0 (the "License")
# you may not use this file except in compliance with the License. You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the License.

# Python 2.7
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

print("Loading modules...")

import time

# Import first to prevent warning messages
import matplotlib; matplotlib.use('Agg')  # pylint: disable=multiple-statements

import os # for os file paths

# To prevent 'Out of memory' errors with GPU
#os.environ["CUDA_VISIBLE_DEVICES"] = "-1" # To turn off GPU

import numpy as np # for arrays and data manipulation

import tensorflow as tf

from collections import defaultdict # text - storing
from io import StringIO # text - translating
from matplotlib import pyplot as plt # for image display
from PIL import Image # for image import

from matplotlib import patches as patches # for visual only - mask is numpy

import sys
ANNO_REPO_DIR = os.path.join('..', 'anno_repo')
sys.path.append(ANNO_REPO_DIR)


import category_names # contains category_index
category_index = category_names.category_index
import image_utils
import tf_detections
import png_masks
from gen_functions import time_seconds_format as tsf

# For more models
# 'http://download.tensorflow.org/models/object_detection/'

FROZEN_GRAPH = os.path.join(os.path.abspath('./'), 'frozen_graph', 'frozen_inference_graph.pb')

TEST_IMAGES = os.path.join(os.path.abspath('./'), 'test_images')
OUTPUT_DIR = os.path.join(os.path.abspath('./'), 'output_masks')
BINARY_IMAGES_DIR = os.path.join(OUTPUT_DIR, "_binary_masks")

CONFIDENCE = 0.75
MAX_OBJECTS = 100

# Codec Options - offset, centric, metric_100, metric_offset
MASK_ENCODE = "metric_100"
MASK_DECODE = MASK_ENCODE 
CODEC_OFFSET = 100

# Resize all images
# Speed up detection and resize ready for training with clean scaling
# A copy will be made and all the masks, visuals and binaries will match
# Detects faster when all images are smaller and same
IMAGE_RESIZE = False # Longest XY if scale=0 (antialiased)
RESIZE_PADDING = True # Pad to XY - detection speed boost if all same
RESIZE_BORDER = 0 # pixels
SAVE_IMAGE_RESIZE = True # Needed for training and re-runs to match mask
RESIZE_SCALE = 0.0 # > 0.0 will override resize X Y - eg 0.5 all half size
# or set longest side max - X, Y generally the same
RESIZE_IMAGE_X = 512
RESIZE_IMAGE_Y = RESIZE_IMAGE_X


CREATE_VISUAL_IMAGE = True
VISUAL_BLEND = 0.5 # Mask visibility
# Proportion option.  Overides visual min/max if >0. 
VISUAL_RESIZE = 0.0 # >0.0 # 1 will return same size as original eg 0.5 = half size
# or set max to reduce, min to enlarge or set min to max to for same size
VISUAL_MAX = 10000 # pixels # Default 10000 (off bar huge) 1000 (on)
VISUAL_MIN = 100 # pixels # Default 100, number=enlarge or VISUAL_MAX


# Export binaries for use in another system
# Stay synchronized with mask and visual or export afterwards
# Note: you can use the condensed masks directly for training
# This will build binary pngs from compatible condensed masks.
# Annotated by filename: image, instance id, category id, category name and category count
# Searchable labels by score rank order with no external text or json needed.
CREATE_BINARY_IMAGES = False
BINARY_IMAGES_DIR = os.path.join('.', 'binary_masks')


################################################
# Code
################################################

start_time = time.time()

test_images = os.listdir(TEST_IMAGES)

if not os.path.exists(OUTPUT_DIR):
    os.mkdir(OUTPUT_DIR)
if CREATE_BINARY_IMAGES:
    if not os.path.exists(BINARY_IMAGES_DIR):
        os.mkdir(BINARY_IMAGES_DIR)
# status report
mask_count = 0
visual_count = 0
binary_count = 0
complete_count = 0

# Create image_dict
# Lists which files are complete or still need to be detected or rebuilt from mask
# It also checks the status of requested output files depending on settings.
# Allows:
# - Delete anything and re-run anytime.
# - Fix the mask just delete the visual to remake with your changes.
# - Delete the masks from one model, upgrade and rerun on difficult images

image_count = 0
image_dicts = []
for test_image in test_images:
    image_dict = {}
    image_path = os.path.join(TEST_IMAGES, test_image)
    image_name, ext = os.path.splitext(test_image)
    if ext != ".jpg" and ext != ".png":
        continue # skip if not jpg or png (could be folder, hidden or not image)
    if image_name[-5:] == "_mask":
        continue # skip masks if images and masks in one folder
    if image_name[-7:] == "_visual":
        continue # skip visuals if images and visuals in one folder
      
    image_count +=1
    
    mask_file_path = os.path.join(OUTPUT_DIR, image_name + "_mask.png")
    mask_visual_path = os.path.join(OUTPUT_DIR, image_name + "_visual.png")
    binary_masks_image_dir = os.path.join(BINARY_IMAGES_DIR, image_name)
    # Use image_id if you have an external image id.  Only used for reporting. 
    image_dict['image_id'] = image_count # count / reporting id / external id
    image_dict['image_name'] = image_name 
    image_dict['image_complete'] = True
    image_dict['image_path'] = image_path
    image_dict['mask_path'] = mask_file_path
    image_dict['mask_exists'] = False
    image_dict['visual_path'] = mask_visual_path
    image_dict['visual_exists'] = False
    image_dict['binary_dir'] = binary_masks_image_dir
    image_dict['binary_exists'] = False

    # Check and count paths of possible creations
    if os.path.exists(image_dict['mask_path']):
        mask_count +=1
        image_dict['mask_exists'] = True
    else:
        image_dict['image_complete'] = False
    if CREATE_VISUAL_IMAGE:
        if os.path.exists(image_dict['visual_path']):
            visual_count += 1
            image_dict['visual_exists'] = True
        else:
            image_dict['image_complete'] = False
    if CREATE_BINARY_IMAGES:
        # Checks for folder of binary masks only
        # Folder may be incomplete on interrupt
        if os.path.exists(image_dict['binary_dir']):
            bimgs = os.listdir(image_dict['binary_dir'])
            binary_count += 1
            image_dict['binary_exists'] = True
        else:
            complete_count = False
            image_dict['image_complete'] = False
    image_dicts.append(image_dict)


# Status report string
report_string = "Status: Images " + str(image_count)
report_string += " Masks " + str(mask_count)
if CREATE_VISUAL_IMAGE:
    report_string += " Visuals " + str(visual_count)
if CREATE_BINARY_IMAGES:
    report_string += " Binaries " + str(binary_count)
print(report_string)

detection_graph = tf_detections.load_frozen_graph(FROZEN_GRAPH)

with detection_graph.as_default():
    with tf.Session() as session:
        cache_image_size = (0,0)
        tensor_dict_cache = {}
        for image_dict in image_dicts:
            if image_dict['image_complete']:
                continue
            image_start = time.time()
            image = Image.open(image_dict['image_path'])
            
            if IMAGE_RESIZE:
                image = image_utils.resize_image(
                    image, "image", 
                    RESIZE_SCALE, RESIZE_IMAGE_X, RESIZE_IMAGE_Y,
                    RESIZE_PADDING, RESIZE_BORDER)
                if SAVE_IMAGE_RESIZE:
                    resized_filename = os.path.basename(image_dict['image_path'])
                    image.save(os.path.join(OUTPUT_DIR, resized_filename))
            if image.size != cache_image_size:
                # Reset tensor dict cache
                cache_image_size = image.size
                tensor_dict_cache = {}
            image_np = image_utils.numpy_from_image(image)
            if image_dict['mask_exists']:
                mask = Image.open(image_dict['mask_path'])
                mask_np = image_utils.numpy_from_image(mask)
                built_dict = png_masks.rebuild_from_mask(
                    mask_np, MASK_DECODE, CODEC_OFFSET, category_index)
            else:
                output_dict, tensor_dict_cache = tf_detections.detect_numpy_for_cached_session(
                    image_np, session, tensor_dict_cache)
                if output_dict.get('detection_masks') is None:
                    print("No masks found for current graph")
                    break
                # Added category index to limit output by category index
                mask_np, built_dict = png_masks.create_mask_from_detection(
                    image_np, output_dict, category_index, 
                    MAX_OBJECTS, CONFIDENCE, MASK_ENCODE, CODEC_OFFSET)
                # Safer handover and access to image and numpy
                mask = image_utils.image_from_numpy(mask_np)
                mask.save(image_dict['mask_path'])
            # Now should have image, image_np, mask, mask_np and built_dict
            if CREATE_VISUAL_IMAGE:
                image_utils.create_visual_from_built(
                    image_dict['visual_path'], built_dict, image_np, mask_np, category_index, 
                    VISUAL_MIN, VISUAL_MAX, VISUAL_BLEND, VISUAL_RESIZE)
            if CREATE_BINARY_IMAGES:
                image_utils.create_binaries_from_built(
                    BINARY_IMAGES_DIR, image_dict['image_name'], built_dict, category_index)
            plt.close('all') # clear images
            image_dict['codecs'] = built_dict['codecs']
            image_name = os.path.basename(image_dict['image_path'])
            print(image_dict['image_id'], image_name, "complete", tsf(time.time() - image_start))

# image_dict now contains codec_dict for each image processed
# No checks have been made so 'exists' flags are initial state
# From here you can check the files, detections or rebuilds
# You can also export reports to json or text file. 
print('-'*50)
print("Processed", image_count, "images.  Total time", tsf(time.time() - start_time))
print('-'*50)

