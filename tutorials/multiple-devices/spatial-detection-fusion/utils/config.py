bev_width = 800
bev_height = 800
bev_scale = 100.0 # pixels per meter
trail_length = 150 # Number of historical points to show for object trails

HTTP_PORT = 8082
calibration_data_dir = "calibration_data"

nn_model_slug = "luxonis/yolov6-nano:r2-coco-512x288" 

nn_input_size = (512, 288) # Should match the chosen YOLOv6 model's input size

# specific labels to show in the BEV / empty labels to show all
bev_labels = []
# bev_labels = ['person'] # example showing just labels with person
