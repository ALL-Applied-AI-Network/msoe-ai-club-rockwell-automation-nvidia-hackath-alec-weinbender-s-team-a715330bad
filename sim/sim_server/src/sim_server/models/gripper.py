from pydantic import BaseModel, ConfigDict


class GripperGeometry(BaseModel):
    """The twin's gripper dimensions that the gripper frame G depends on, in metres. Built from scene_config by
    robot/gripper_frame.geometry_from_twin() (so this module never imports the twin), never typed in by hand."""

    model_config = ConfigDict(frozen=True)

    carriage_x: float  # flange (J6_link origin) to the jaw bodies' origin, along TOOL_AXIS: cell.gripper_layout()[0]
    finger_x: float  # flange to the stock finger root: cell.gripper_layout()[1]
    finger_length: float
    finger_width: float
    finger_thick: float
    jaw_open: float  # per-jaw opening from closed: 0 closed, JAW_STROKE (6 mm) fully open
    jaw_closed: float
    finger_inner_tip: float  # how far outside the straight inner face the stock hook tip sits (about 2.0 mm)
    tip_clearance: float  # the twin's cube grasp height, fingertips above the surface (CUBE_TIP_CLEARANCE, 2.5 mm)
    surface_dz: float  # work surface height in the robot base frame (SURFACE_DZ, -5.1 mm)
    table_top_z: float  # world z of the robot base frame (TABLE_TOP_Z)

    @property
    def tip_offset(self) -> float:
        """Flange to fingertips along the tool axis: the TCP the twin's IK uses (cell.tip_offset(), 0.293 m)."""
        return self.finger_x + self.finger_length

    @property
    def open_tip_gap(self) -> float:
        """Distance between the stock hooked tips with the jaws fully open (about 16 mm)."""
        return 2 * (self.jaw_open + self.finger_inner_tip)
