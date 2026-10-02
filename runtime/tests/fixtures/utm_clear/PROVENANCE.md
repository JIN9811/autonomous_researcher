# Immutable UTM positive image references

Exact byte-for-byte copies, 2026-09-06. Neither image has been edited.

- `upright_raw.png`: source `runs/run-20260906T122533Z-c0effd/vision/frame-0-vision/utm_completion/utm-frame-1788698517866_raw.png`; SHA256 `048fe6dd413d310d9bfc775b12c7155dff45bf7d9c13b9827e5575562e68c49f`. Actual same-camera Verification 1 image; expected default largest red component 3336 px, bbox [256,290,320,352].
- `compressed_raw.png`: source `artifacts/utm_presence_calibration/compressed-20260906/compressed-present-current_raw.png`; SHA256 `a3220ea140583c2a8cca9f3d56822c4ab4bc00200c23ed4e884037f1ab308436`. User-confirmed actual compressed specimen; expected largest red component 1540 px, bbox [257,318,316,350]. Root read-only capture was from `/camera/image_rect`, 640x480, camera_utm_primary.

These are positive residual-sensitivity references, not fresh clearance evidence.
Tests supply synthetic timing only to exercise the decision code. Generated
empty, fragmented and noise scenes in the tests are explicitly synthetic.
No actual empty-hardware negative or metric pixel/mm calibration is claimed.
