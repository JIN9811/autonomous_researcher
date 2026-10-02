# Camera / Vision bridge

This installed bridge groups ATR's existing observation runtimes, state observer,
pose tracker, optional RealSense adapter and camera tool registration. Existing
flat imports remain compatibility aliases to these same modules and objects.

`camera.capture` intentionally retains its simulator-backed behavior. Live robot
camera motion belongs to the shared LeRobot bridge, while UTM protocol execution
belongs to Equipment. The graph runtime alias is `camera_utm_bridge`.

The camera inspection and virtual current-STL helpers use NumPy, Pillow,
scikit-image and trimesh. Optional live
routes require the existing ROS 2 environment, pyrealsense2, cv_bridge and
OpenCV, plus the external UTM checkout at
`~/external_repos/UTM` unless configured otherwise.
