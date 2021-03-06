import calc_BTD
from multi_tracker_improved import MultiTrackerImproved

import GOES
import numpy as np
import os
from skimage import feature
from skimage import transform
from cv2 import cv2
import copy

# New clustering method
from sklearn.model_selection import train_test_split
from sklearn.utils.metaestimators import if_delegate_has_method
from sklearn.base import BaseEstimator, clone
from sklearn.tree import DecisionTreeClassifier
from sklearn.cluster import DBSCAN

# Land masking system
import rasterio
from pyresample import SwathDefinition, kd_tree
from pyresample.geometry import AreaDefinition
from pyproj import CRS, Transformer, Proj
from affine import Affine
from rasterio import mask
import geopandas

class InductiveClusterer(BaseEstimator):
    def __init__(self, clusterer, classifier):
        self.clusterer = clusterer
        self.classifier = classifier

    def fit(self, X, y=None):
        self.clusterer_ = clone(self.clusterer)
        self.classifier_ = clone(self.classifier)
        y = self.clusterer_.fit_predict(X)
        self.classifier_.fit(X, y)
        return self

    @if_delegate_has_method(delegate='classifier_')
    def predict(self, X):
        return self.classifier_.predict(X)

    @if_delegate_has_method(delegate='classifier_')
    def decision_function(self, X):
        return self.classifier_.decision_function(X)


TIFF_DIR = "/Users/tschmidt/repos/tgs_honours/good_data/16-ch7-apr24-tiff/"
LAND_POLYGON_SHAPE = "/Users/tschmidt/repos/tgs_honours/good_data/coastlines_merc/land_polygons.shp"
# Defines the plot area
LLLon, URLon = -135, -116.5
LLLat, URLat = 28, 38.5

def run(input_dir, output_dir):
    DATA_DIR_2 = os.path.join(input_dir, "ch2")
    DATA_DIR_6 = os.path.join(input_dir, "ch6")
    DATA_DIR_7 = os.path.join(input_dir, "ch7")
    DATA_DIR_14 = os.path.join(input_dir, "ch14")

    # Get contents of data dir for ch 7
    data_list_7 = os.listdir(DATA_DIR_7)
    if ".DS_Store" in data_list_7:
        data_list_7.remove(".DS_Store") # For mac users
    data_list_7 = sorted(data_list_7)

    # Get contents of data dir for ch14
    data_list_14 = os.listdir(DATA_DIR_14)
    if ".DS_Store" in data_list_14:
        data_list_14.remove(".DS_Store") # For mac users
    data_list_14 = sorted(data_list_14)

    # Get contents of data dir for ch 2
    data_list_2 = os.listdir(DATA_DIR_2)
    if ".DS_Store" in data_list_2:
        data_list_2.remove(".DS_Store") # For mac users
    data_list_2 = sorted(data_list_2)

    # Get contents of data dir for ch 6
    data_list_6 = os.listdir(DATA_DIR_6)
    if ".DS_Store" in data_list_6:
        data_list_6.remove(".DS_Store") # For mac users
    data_list_6 = sorted(data_list_6)

    # Load ch7 for projection constants
    first_ds_name = data_list_7[0]
    first_ds_path = os.path.join(DATA_DIR_7, first_ds_name)
    first_ds = GOES.open_dataset(first_ds_path)
    var_ch02, lons, lats = first_ds.image("Rad", domain=[LLLon, URLon, LLLat, URLat])
    var_ch02, lons, lats = var_ch02.data, lons.data, lats.data
    HEIGHT = var_ch02.shape[0]
    WIDTH = var_ch02.shape[1]

    # Setup projection constants used throughout the script.
    tiff_path = os.path.join(TIFF_DIR, "0.tif")
    p_crs = CRS.from_epsg(3857)
    p_latlon = CRS.from_proj4("+proj=latlon")
    crs_transform = Transformer.from_crs(p_latlon,p_crs)
    ll_x, ll_y = crs_transform.transform(LLLon, LLLat)
    ur_x, ur_y = crs_transform.transform(URLon, URLat)
    area_extent = (ll_x, ll_y, ur_x, ur_y)
    ul_x = ll_x # Why these?
    ul_y = ur_y
    area_id = "California Coast"
    description = "See area ID"
    proj_id = "Mercator"
    pixel_size_x = (ur_x - ll_x)/(WIDTH - 1)
    pixel_size_y = (ur_y - ll_y)/(HEIGHT - 1)
    new_affine = Affine(pixel_size_x, 0.0, ul_x, 0.0, -pixel_size_y, ul_y)
    area_def = AreaDefinition(area_id, description, proj_id, p_crs,
                                WIDTH, HEIGHT, area_extent)
    fill_value = np.nan

    # Load ch7 for land masking
    first_ds_name = data_list_7[0]
    first_ds_path = os.path.join(DATA_DIR_7, first_ds_name)
    first_ds = GOES.open_dataset(first_ds_path)
    var_ch07, lons, lats = first_ds.image("Rad", domain=[LLLon, URLon, LLLat, URLat])
    var_ch07, lons, lats = var_ch07.data, lons.data, lats.data
    swath_def = SwathDefinition(lons, lats)
    first_ds = None # Free the memory from these big datasets
    var_ch07 = kd_tree.resample_nearest(
        swath_def,
        var_ch07.ravel(),
        area_def,
        radius_of_influence=5000,
        nprocs=2,
        fill_value=fill_value
    )

    ###### New land masking system #######################
    with rasterio.open(
        tiff_path,
        "w",
        driver="GTiff",
        height=HEIGHT,
        width=WIDTH,
        count=1, #????
        dtype=var_ch07.dtype,
        crs=p_crs,
        transform=new_affine,
        nodata=fill_value,
    ) as dst:
        dst.write(np.reshape(var_ch07,(1,HEIGHT,WIDTH)))

    src = rasterio.open(tiff_path, mode='r+')
    geodf = geopandas.read_file(LAND_POLYGON_SHAPE)
    land_masking, other_affine = mask.mask(src, geodf[['geometry']].values.flatten(), invert=True, filled=False)
    land_masking = np.ma.getmask(land_masking)
    land_masking = np.reshape(land_masking, (HEIGHT,WIDTH))
    src.close() # Free memory
    src = None
    geodf = None
    ############################################################

    # Init multi-tracker
    trackers = MultiTrackerImproved(cv2.TrackerCSRT_create)

    image_list = []
    # BTD_list = []
    refl_ch2_list = []
    refl_ch6_list = []

    i = 0
    for ds_name_7 in data_list_7:
        ds_name_14 = data_list_14[i]
        ds_name_2 = data_list_2[i]
        ds_name_6 = data_list_6[i]
        ds_path_7 = os.path.join(DATA_DIR_7, ds_name_7)
        ds_path_14 = os.path.join(DATA_DIR_14, ds_name_14)
        ds_path_2 = os.path.join(DATA_DIR_2, ds_name_2)
        ds_path_6 = os.path.join(DATA_DIR_6, ds_name_6)

        # Load channel 2
        ds_2 = GOES.open_dataset(ds_path_2)
        var_ch02, lons, lats = ds_2.image("Rad", domain=[LLLon, URLon, LLLat, URLat])
        var_ch02, lons, lats = var_ch02.data, lons.data, lats.data
        swath_def = SwathDefinition(lons, lats)
        var_ch02 = kd_tree.resample_nearest(
            swath_def,
            var_ch02.ravel(),
            area_def,
            radius_of_influence=5000,
            nprocs=2,
            fill_value=fill_value
        )

        # Load channel 2 reflectivity
        ds_2 = GOES.open_dataset(ds_path_2)
        refl_var_ch02, lons, lats = ds_2.image("Rad", up_level=True, domain=[LLLon, URLon, LLLat, URLat])
        refl_var_ch02 = refl_var_ch02.refl_fact_to_refl(lons, lats).data
        swath_def = SwathDefinition(lons.data, lats.data)
        refl_var_ch02 = kd_tree.resample_nearest(
            swath_def,
            refl_var_ch02.ravel(),
            area_def,
            radius_of_influence=5000,
            nprocs=2,
            fill_value=fill_value
        )

        # Load channel 6 reflectivity
        ds_6 = GOES.open_dataset(ds_path_6)
        refl_var_ch06, lons, lats = ds_6.image("Rad", up_level=True, domain=[LLLon, URLon, LLLat, URLat])
        refl_var_ch06 = refl_var_ch06.refl_fact_to_refl(lons, lats).data
        swath_def = SwathDefinition(lons.data, lats.data)
        refl_var_ch06 = kd_tree.resample_nearest(
            swath_def,
            refl_var_ch06.ravel(),
            area_def,
            radius_of_influence=5000,
            nprocs=2,
            fill_value=fill_value
        )

        # Load channel 7
        ds_7 = GOES.open_dataset(ds_path_7)
        var_ch07, lons, lats = ds_7.image("Rad", domain=[LLLon, URLon, LLLat, URLat])
        var_ch07, lons, lats = var_ch07.data, lons.data, lats.data
        swath_def = SwathDefinition(lons, lats)
        var_ch07 = kd_tree.resample_nearest(
            swath_def,
            var_ch07.ravel(),
            area_def,
            radius_of_influence=5000,
            nprocs=2,
            fill_value=fill_value
        )

        # Load channel 14
        ds_14 = GOES.open_dataset(ds_path_14)
        var_ch14, lons, lats = ds_14.image("Rad", domain=[LLLon, URLon, LLLat, URLat])
        var_ch14, lons, lats = var_ch14.data, lons.data, lats.data
        swath_def = SwathDefinition(lons, lats)
        var_ch14 = kd_tree.resample_nearest(
            swath_def,
            var_ch14.ravel(),
            area_def,
            radius_of_influence=5000,
            nprocs=2,
            fill_value=fill_value
        )

        # Make BTD
        var = calc_BTD.main_func(var_ch14, var_ch07, 14, 7)

        # Skip day if it has bad data
        if np.isnan(var).any():
            i = i + 1
            continue

        # Make copy of the BTD for use as a backround in cv2 image output
        # Maps the BTD values to a range of [0,255]
        # BTD = copy.deepcopy(var)
        BTD_img = copy.deepcopy(var)
        min_BTD = np.nanmin(BTD_img)
        if min_BTD < 0:
            BTD_img = BTD_img + np.abs(min_BTD)
        max_BTD = np.nanmax(BTD_img)
        BTD_img = BTD_img/max_BTD
        # BTD_img = cv2.cvtColor(BTD_img*255, cv2.COLOR_GRAY2BGR)
        # BTD_img_trackers = copy.deepcopy(BTD_img) # Next two lines are for new BTD data for trackers
        # BTD_img_trackers = np.array(BTD_img_trackers).astype('uint8') # Since it seems the trackers need images of type uint8

        # Filter out the land
        var[land_masking] = np.nan

        # Create mask array for the highest clouds
        high_cloud_mask = calc_BTD.bt_ch14_temp_conv(var_ch14) < 5 # TODO: Make this more robust

        #### Use reflectivity of channel 2 and BT of channel 14 to filter out open ocean data ###########
        BT = calc_BTD.bt_ch14_temp_conv(var_ch14)

        BT = BT[np.logical_and(np.logical_not(land_masking), np.logical_not(high_cloud_mask))] # Filter out the land since golden arches works best when only over water
        var_ch02 = var_ch02[np.logical_and(np.logical_not(land_masking), np.logical_not(high_cloud_mask))] # Filter out the land since golden arches works best when only over water

        BT_and_CH02 = np.vstack((BT, var_ch02)).T
        BT_and_CH02_sample, _ = train_test_split(BT_and_CH02, train_size=10000)

        clusterer = DBSCAN(eps=1.5, min_samples=100) # Found through extensive testing
        classifier = DecisionTreeClassifier()
        inductive_cluster = InductiveClusterer(clusterer, classifier).fit(BT_and_CH02_sample)
        IC_labels = inductive_cluster.predict(BT_and_CH02) + 1
        
        all_labels = np.unique(IC_labels)
        min_refl = np.Inf
        open_ocean_label = 0
        for j in all_labels:
            labeled_refl_array = var_ch02[IC_labels==j]
            mean_refl = np.nanmean(labeled_refl_array)
            if mean_refl < min_refl:
                open_ocean_label = j
                min_refl = mean_refl
        golden_arch_mask_ocean = IC_labels == open_ocean_label

        golden_arch_mask = np.zeros(var.shape, dtype=bool)
        golden_arch_mask[np.logical_and(np.logical_not(land_masking), np.logical_not(high_cloud_mask))] = golden_arch_mask_ocean

        var = np.where(golden_arch_mask, np.nan, var)
        ###############################################################################################

        #Filter out the cold high altitude clouds
        var = np.where(high_cloud_mask, np.nan, var)

        var = feature.canny(var, sigma = 2.2, low_threshold = 0, high_threshold = 1.2)
        var = np.where(var == np.nan, 0, var)

        ## Skimage hough line transform #################################
        var = np.array(var).astype('uint8')
        img = cv2.cvtColor(var*255, cv2.COLOR_GRAY2BGR)

        # Was 0, 30, 1
        threshold = 0
        minLineLength = 30
        maxLineGap = 2
        theta = np.linspace(-np.pi, np.pi, 1000)

        lines = transform.probabilistic_hough_line(var, threshold=threshold, line_length=minLineLength, line_gap=maxLineGap, theta=theta)
        #############################################################

        #### TRACKER #################
        trackers.update(img, i)

        if lines is not None:
            for line in lines:
                p0, p1 = line
                x1 = p0[0]
                y1 = p0[1]
                x2 = p1[0]
                y2 = p1[1]

                min_x = np.minimum(x1,x2)
                min_y = np.minimum(y1,y2)
                max_x = np.maximum(x1,x2)
                max_y = np.maximum(y1,y2)

                rect = (min_x-2, min_y-2, max_x-min_x + 4, max_y-min_y + 4) #TODO: Maybe expand the size of the boxes a bit?
                trackers.add_tracker(img, rect, len(data_list_7))
        ###############################
        
        image_list.append(BTD_img)
        # BTD_list.append(BTD)
        refl_ch2_list.append(refl_var_ch02)
        refl_ch6_list.append(refl_var_ch06)

        print("Image " + str(i) + " Calculated")
        i = i + 1


    # TODO: Remove BTD_list in all areas if I am not using it for real final pngs
    for i in range(len(image_list)):
        label_name = "labels"
        data_name = "data"
        filename = str(i) + ".tif"
        data_file_path = os.path.join(output_dir, data_name, filename)
        label_file_path = os.path.join(output_dir, label_name, filename)
        boxes = trackers.get_boxes(i)

        BTD_img = image_list[i]
        # BTD = BTD_list[i]
        refl_var_ch02 = refl_ch2_list[i]
        refl_var_ch06 = refl_ch6_list[i]

        # Make box plots for trackers
        # Also make and highlight the labels
        labels = np.zeros([BTD_img.shape[0], BTD_img.shape[1]], dtype=np.float32)
        for box in boxes:
            (x, y, w, h) = [int(v) for v in box]

            if w > 0 and h > 0 and x >= 0 and y >= 0 and y+h <= BTD_img.shape[0] and x+w <= BTD_img.shape[1] and y < BTD_img.shape[0] and x < BTD_img.shape[1]:
                ch2_slice = refl_var_ch02[y:y+h, x:x+w]
                ch6_slice = refl_var_ch06[y:y+h, x:x+w]

                labels_slice = labels[y:y+h, x:x+w]
                labels_slice = np.where(np.logical_and(ch6_slice >= 0.28, ch2_slice >= 0.3), 1.0, labels_slice)
                labels[y:y+h, x:x+w] = labels_slice # Add red for labels

        with rasterio.open(
            data_file_path,
            "w",
            driver="GTiff",
            height=HEIGHT,
            width=WIDTH,
            count=1, #????
            dtype=BTD_img.dtype,
            crs=p_crs,
            transform=new_affine,
            nodata=fill_value,
        ) as dst:
            dst.write(np.reshape(BTD_img,(1,HEIGHT,WIDTH)))

        with rasterio.open(
            label_file_path,
            "w",
            driver="GTiff",
            height=HEIGHT,
            width=WIDTH,
            count=1, #????
            dtype=labels.dtype,
            crs=p_crs,
            transform=new_affine,
            nodata=fill_value,
        ) as dst:
            dst.write(np.reshape(labels,(1,HEIGHT,WIDTH)))

        # BTD_img = cv2.addWeighted(BTD_img, 1.0, labels, 0.5, 0)

        # cv2.imwrite(file_path, BTD_img)

        print("Image " + str(i) + " Complete")