import numpy as np
from cv2 import cv2

class MultiTrackerImproved:
    def __init__(self, tracker_type):
        self.trackers = []
        self.previous_states = []
        self.previous_positions = []
        self.number_of_successes = []
        self.boxes = []
        self.tracker_type = tracker_type

    def update(self, img):
        trackers_to_delete = []
        i = 0

        for tracker in self.trackers:
            success, box = tracker.update(img)
            is_deleted = False

            if success:
                self.number_of_successes[i] = self.number_of_successes[i] + 1

            ##### Original check-if-2-success system ###########
            # if not success and not self.previous_states[i]:
            #     trackers_to_delete.append(i)
            #     is_deleted = True
            # elif success and self.previous_states[i]:
            #     self.previous_states[i] = success
            #     if self.number_of_successes[i] >= 4:
            #         self.boxes[i] = box
            # else:
            #     self.previous_states[i] = success
            #     if not success:
            #         self.boxes[i] = None
            ####################################################

            ###### other system ########################
            if not success:
                trackers_to_delete.append(i)
                is_deleted = True
            else:
                if self.number_of_successes[i] >= 4:
                    self.boxes[i] = box
            ###########################################
            
            (x, y, w, h) = [int(v) for v in box]

            if not is_deleted and (np.abs(x - self.previous_positions[i][0]) > 5 or np.abs(y - self.previous_positions[i][1]) > 5):
                trackers_to_delete.append(i)
                is_deleted = True
            
            self.previous_positions[i] = (x, y)
            
            i = i + 1

        boxes_np = np.empty((len(self.boxes),), dtype=object) # Because self.boxes is a list of tuples
        boxes_np[:] = self.boxes
        previous_positions_np = np.empty((len(self.previous_positions),), dtype=object) # Because self.previous_positions is a list of tuples
        previous_positions_np[:] = self.previous_positions

        self.trackers = np.delete(self.trackers, trackers_to_delete).tolist()
        self.previous_states = np.delete(self.previous_states, trackers_to_delete).tolist()
        self.boxes = np.delete(boxes_np, trackers_to_delete).tolist()
        self.previous_positions = np.delete(previous_positions_np, trackers_to_delete).tolist()
        self.number_of_successes = np.delete(self.number_of_successes, trackers_to_delete).tolist()

    def add_tracker(self, img, rect):
        tracker = self.tracker_type()
        tracker.init(img, rect)

        self.trackers.append(tracker)
        self.previous_states.append(False)
        self.previous_positions.append((rect[0], rect[1]))
        self.number_of_successes.append(0)
        self.boxes.append(None)

    # This may add an extra loop iteration unnecessarily
    def get_boxes(self):
        boxes = []

        for box in self.boxes:
            if box is not None:
                boxes.append(box)

        return boxes