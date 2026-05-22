"""Export target maps (.npz) for grasp training — future extension."""


def export_target_maps(
    dataset_path, output_dir=None, map_size=(320, 240),
):
    """
    FUTURE: Generate .npz files with Q_map, sin2θ_map, cos2θ_map, width_map.

    Not implemented in MVP.
    """
    raise NotImplementedError(
        "Target map export is a future extension. "
        "This will generate per-pixel grasp parameter maps for training Model B."
    )
