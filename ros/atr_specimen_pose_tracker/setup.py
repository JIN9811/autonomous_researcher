from setuptools import setup

package_name = "atr_specimen_pose_tracker"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/atr_specimen_pose_tracker"]),
        ("share/atr_specimen_pose_tracker", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="ATR",
    maintainer_email="local@atr.invalid",
    description="One-shot D455F specimen pose tracker",
    license="Proprietary",
    entry_points={"console_scripts": ["specimen_pose_node = atr_specimen_pose_tracker.specimen_pose_node:main"]},
)
