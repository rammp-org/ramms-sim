"""The test robot's "editor-side adapter" for tests/test_course_session.py: runner_op.py loads an adapter by file, and
this one hands back the robot the test put in its stand-in world."""


def find(world, wheels):
    return getattr(world, "robot", None)
