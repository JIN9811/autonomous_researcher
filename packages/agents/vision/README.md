# Vision agent package

The Vision agent owns observation reasoning and depends on the installed
`camera_vision@1.0.0` and shared `lerobot@1.0.0` bridges. Robot camera movement,
ActiveCam, and rollout stop remain owned by the one registered LeRobot runtime;
this package reference does not create another bridge instance.
